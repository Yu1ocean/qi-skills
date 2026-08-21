#!/usr/bin/env python3
"""Decision Registry 本地 SSOT -> 飞书镜像台账同步脚本。

功能：
1. 解析 memory/topics/decision-registry.md 中的 YAML 决策记录块
2. 读取飞书表格现有数据（通过 lark-cli / MCP 链路）
3. 以 id 为主键做 upsert / drift 检测 / orphan 告警
4. 写后执行 RAW 回捞校验
5. 输出同步日志与 JSON 摘要
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = ROOT / "memory/topics/decision-registry.md"
DEFAULT_WIKI_URL = "https://bytedance.larkoffice.com/wiki/PnnDwYr13imUyVkVPshc46ICnVh"
DEFAULT_SHEET_NAME = "Decision Registry"
EXPECTED_HEADERS = [
    "ID",
    "标题",
    "类型",
    "作用域",
    "状态",
    "决策背景",
    "最终选择",
    "选择理由",
    "已知代价",
    "升格目标",
    "创建时间",
    "最后更新",
]
ID_PATTERN = re.compile(r"^DEC-\d{8}-\d{3}$")
YAML_BLOCK_PATTERN = re.compile(r"```yaml\n(.*?)\n```", re.DOTALL)
WIKI_TOKEN_PATTERN = re.compile(r"/wiki/([A-Za-z0-9]+)")
SHEET_TOKEN_PATTERN = re.compile(r"/sheets/([A-Za-z0-9]+)")


class SyncError(RuntimeError):
    pass


@dataclass
class ActionLog:
    action: str
    decision_id: str
    detail: str
    row_index: Optional[int] = None


@dataclass
class SyncResult:
    local_count: int = 0
    remote_count: int = 0
    inserted: List[ActionLog] = field(default_factory=list)
    updated: List[ActionLog] = field(default_factory=list)
    skipped: List[ActionLog] = field(default_factory=list)
    drifted: List[ActionLog] = field(default_factory=list)
    orphans: List[ActionLog] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.drifted or self.orphans)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "local_count": self.local_count,
            "remote_count": self.remote_count,
            "inserted": [vars(x) for x in self.inserted],
            "updated": [vars(x) for x in self.updated],
            "skipped": [vars(x) for x in self.skipped],
            "drifted": [vars(x) for x in self.drifted],
            "orphans": [vars(x) for x in self.orphans],
            "warnings": self.warnings,
        }


def run_cmd(args: List[str]) -> Dict[str, Any]:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SyncError(
            f"命令执行失败（exit={proc.returncode}）\nCMD: {' '.join(args)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )

    text = (proc.stdout or "").strip()
    if not text:
        raise SyncError(f"命令无输出：{' '.join(args)}")

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise SyncError(f"命令输出不是 JSON：{' '.join(args)}\n{text}")

    payload = json.loads(text[start : end + 1])
    ok = payload.get("ok")
    code = payload.get("code")
    if ok is False or (code not in (None, 0)):
        raise SyncError(f"命令返回失败：{' '.join(args)}\n{json.dumps(payload, ensure_ascii=False, indent=2)}")
    return payload


def extract_token(url: str, pattern: re.Pattern[str], kind: str) -> str:
    match = pattern.search(url)
    if not match:
        raise SyncError(f"无法从 {kind} URL 解析 token: {url}")
    return match.group(1)


def resolve_sheet_url(url: str) -> Tuple[str, str, str]:
    if "/wiki/" in url:
        wiki_token = extract_token(url, WIKI_TOKEN_PATTERN, "wiki")
        payload = run_cmd([
            "lark-cli",
            "wiki",
            "spaces",
            "get_node",
            "--params",
            json.dumps({"token": wiki_token}, ensure_ascii=False),
        ])
        node = payload["data"]["node"]
        if node["obj_type"] != "sheet":
            raise SyncError(f"目标 wiki 不是电子表格，实际类型：{node['obj_type']}")
        token = node["obj_token"]
        title = node.get("title", "")
        return f"https://bytedance.larkoffice.com/sheets/{token}", token, title

    if "/sheets/" in url:
        token = extract_token(url, SHEET_TOKEN_PATTERN, "sheet")
        return url.split("?")[0], token, ""

    raise SyncError(f"暂不支持的飞书链接：{url}")


def get_sheet_meta(sheet_url: str) -> Dict[str, Any]:
    payload = run_cmd(["lark-cli", "sheets", "+info", "--url", sheet_url])
    sheets = payload["data"]["sheets"]["sheets"]
    if not sheets:
        raise SyncError("目标表格没有任何工作表")
    sheet = sheets[0]
    return {
        "sheet_id": sheet["sheet_id"],
        "sheet_title": sheet["title"],
        "spreadsheet_token": payload["data"]["spreadsheet"]["spreadsheet"]["token"],
        "spreadsheet_title": payload["data"]["spreadsheet"]["spreadsheet"]["title"],
    }


def read_range(sheet_url: str, sheet_id: str, cell_range: str) -> List[List[Any]]:
    payload = run_cmd([
        "lark-cli",
        "sheets",
        "+read",
        "--url",
        sheet_url,
        "--sheet-id",
        sheet_id,
        "--range",
        cell_range,
    ])
    return payload["data"]["valueRange"].get("values", [])


def write_range(sheet_url: str, sheet_id: str, cell_range: str, values: List[List[Any]]) -> Dict[str, Any]:
    return run_cmd([
        "lark-cli",
        "sheets",
        "+write",
        "--url",
        sheet_url,
        "--sheet-id",
        sheet_id,
        "--range",
        cell_range,
        "--values",
        json.dumps(values, ensure_ascii=False),
    ])


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def format_sheet_time(value: Any) -> str:
    return normalize_text(value)


def parse_registry(path: Path) -> List[Dict[str, Any]]:
    content = path.read_text(encoding="utf-8")
    records: List[Dict[str, Any]] = []
    seen_ids = set()

    for block in YAML_BLOCK_PATTERN.findall(content):
        parsed = yaml.safe_load(block)
        if not isinstance(parsed, list):
            continue
        for item in parsed:
            if not isinstance(item, dict):
                continue
            decision_id = normalize_text(item.get("id"))
            if not ID_PATTERN.match(decision_id):
                continue
            if decision_id in seen_ids:
                raise SyncError(f"本地决策 ID 重复：{decision_id}")
            seen_ids.add(decision_id)
            records.append(item)

    if not records:
        raise SyncError(f"未从 {path} 解析到任何有效决策记录")

    records.sort(key=lambda x: normalize_text(x.get("id")))
    return records


def local_record_to_sheet_row(record: Dict[str, Any]) -> List[str]:
    return [
        normalize_text(record.get("id")),
        normalize_text(record.get("title")),
        normalize_text(record.get("type")),
        normalize_text(record.get("scope")),
        normalize_text(record.get("status")),
        normalize_text(record.get("context")),
        normalize_text(record.get("chosen")),
        normalize_text(record.get("rationale")),
        normalize_text(record.get("tradeoffs")),
        normalize_text(record.get("upgrade_path")),
        format_sheet_time(record.get("created_at")),
        format_sheet_time(record.get("updated_at")),
    ]


def build_remote_index(values: List[List[Any]]) -> Tuple[Dict[str, Dict[str, Any]], int]:
    if not values:
        raise SyncError("飞书表格为空，至少需要表头")

    headers = [normalize_text(x) for x in values[0]]
    if headers[: len(EXPECTED_HEADERS)] != EXPECTED_HEADERS:
        raise SyncError(
            "飞书表头与预期不一致\n"
            f"期望：{EXPECTED_HEADERS}\n"
            f"实际：{headers}"
        )

    index: Dict[str, Dict[str, Any]] = {}
    last_nonempty_row = 1
    for row_num, row in enumerate(values[1:], start=2):
        row = list(row) + [None] * (len(EXPECTED_HEADERS) - len(row))
        row = row[: len(EXPECTED_HEADERS)]
        normalized = [normalize_text(x) for x in row]
        if any(normalized):
            last_nonempty_row = row_num
        decision_id = normalized[0]
        if not decision_id:
            continue
        if decision_id in index:
            raise SyncError(f"飞书表中发现重复 ID：{decision_id}（至少两行）")
        index[decision_id] = {
            "row_num": row_num,
            "values": normalized,
        }
    return index, last_nonempty_row


def diff_fields(local_row: List[str], remote_row: List[str]) -> List[str]:
    diffs = []
    for idx, (lv, rv) in enumerate(zip(local_row, remote_row), start=1):
        if normalize_text(lv) != normalize_text(rv):
            diffs.append(f"{EXPECTED_HEADERS[idx-1]}: local={lv!r} remote={rv!r}")
    return diffs


def raw_verify(sheet_url: str, sheet_id: str, row_num: int, expected: List[str]) -> List[List[Any]]:
    time.sleep(2)
    fetched = read_range(sheet_url, sheet_id, f"A{row_num}:L{row_num}")
    actual_row = []
    if fetched:
        padded_row = (list(fetched[0]) + [None] * (len(EXPECTED_HEADERS) - len(fetched[0])))[: len(EXPECTED_HEADERS)]
        actual_row = [normalize_text(x) for x in padded_row]
    if actual_row != [normalize_text(x) for x in expected]:
        raise SyncError(
            "RAW 回捞校验失败\n"
            f"expected={json.dumps([expected], ensure_ascii=False)}\n"
            f"actual={json.dumps(fetched, ensure_ascii=False)}"
        )
    return fetched


def sync_registry(
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    sheet_url: str = DEFAULT_WIKI_URL,
    apply: bool = True,
    verbose: bool = True,
) -> SyncResult:
    result = SyncResult()
    local_records = parse_registry(registry_path)
    result.local_count = len(local_records)

    resolved_sheet_url, _, _ = resolve_sheet_url(sheet_url)
    meta = get_sheet_meta(resolved_sheet_url)
    sheet_id = meta["sheet_id"]

    # 预读较大范围，覆盖当前 4 条记录与后续扩展；若未来超过 1000 行，可继续扩展。
    values = read_range(resolved_sheet_url, sheet_id, "A1:L1000")
    remote_index, last_nonempty_row = build_remote_index(values)
    result.remote_count = len(remote_index)

    local_index = {}
    for record in local_records:
        row = local_record_to_sheet_row(record)
        local_index[row[0]] = row

    for decision_id, remote in remote_index.items():
        if decision_id not in local_index:
            log = ActionLog("orphan", decision_id, "飞书存在但本地不存在；按约定不删除，仅报警", remote["row_num"])
            result.orphans.append(log)
            result.warnings.append(f"orphan: {decision_id} @ row {remote['row_num']}")
            if verbose:
                print(f"[WARN] orphan 行保留：{decision_id} (row={remote['row_num']})")

    next_row = last_nonempty_row + 1
    for decision_id in sorted(local_index.keys()):
        local_row = local_index[decision_id]
        remote = remote_index.get(decision_id)
        if remote is None:
            target_row = next_row
            next_row += 1
            diffs = [f"新增行 -> A{target_row}:L{target_row}"]
            result.drifted.append(ActionLog("insert", decision_id, "; ".join(diffs), target_row))
            if apply:
                write_range(resolved_sheet_url, sheet_id, f"A{target_row}:L{target_row}", [local_row])
                raw = raw_verify(resolved_sheet_url, sheet_id, target_row, local_row)
                result.inserted.append(ActionLog("inserted", decision_id, f"RAW={json.dumps(raw, ensure_ascii=False)}", target_row))
                if verbose:
                    print(f"[INSERT] {decision_id} -> row {target_row}")
                    print(json.dumps(raw, ensure_ascii=False))
            else:
                result.skipped.append(ActionLog("dry-run-insert", decision_id, "; ".join(diffs), target_row))
                if verbose:
                    print(f"[DRY-RUN][INSERT] {decision_id} -> row {target_row}")
            continue

        diffs = diff_fields(local_row, remote["values"])
        if not diffs:
            result.skipped.append(ActionLog("skip", decision_id, "无差异，跳过", remote["row_num"]))
            if verbose:
                print(f"[SKIP] {decision_id} 无差异")
            continue

        target_row = remote["row_num"]
        result.drifted.append(ActionLog("update", decision_id, " | ".join(diffs), target_row))
        if apply:
            write_range(resolved_sheet_url, sheet_id, f"A{target_row}:L{target_row}", [local_row])
            raw = raw_verify(resolved_sheet_url, sheet_id, target_row, local_row)
            result.updated.append(ActionLog("updated", decision_id, f"RAW={json.dumps(raw, ensure_ascii=False)}", target_row))
            if verbose:
                print(f"[UPDATE] {decision_id} -> row {target_row}")
                for diff in diffs:
                    print(f"  - {diff}")
                print(json.dumps(raw, ensure_ascii=False))
        else:
            result.skipped.append(ActionLog("dry-run-update", decision_id, " | ".join(diffs), target_row))
            if verbose:
                print(f"[DRY-RUN][UPDATE] {decision_id} -> row {target_row}")
                for diff in diffs:
                    print(f"  - {diff}")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="同步 Decision Registry 到飞书镜像台账")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY_PATH), help="本地 registry 文件路径")
    parser.add_argument("--sheet-url", default=DEFAULT_WIKI_URL, help="飞书 wiki/sheet 链接")
    parser.add_argument("--dry-run", action="store_true", help="仅对账，不实际写入")
    parser.add_argument("--quiet", action="store_true", help="减少过程日志")
    args = parser.parse_args()

    try:
        result = sync_registry(
            registry_path=Path(args.registry),
            sheet_url=args.sheet_url,
            apply=not args.dry_run,
            verbose=not args.quiet,
        )
        print("[SUMMARY]" + json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        if result.orphans:
            print(f"[WARN] 发现 orphan 共 {len(result.orphans)} 条（未删除）")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
