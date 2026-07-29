#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

try:
    import yaml
except Exception as exc:  # pragma: no cover
    raise RuntimeError("缺少 PyYAML 依赖，无法解析 YAML / Markdown YAML 代码块。") from exc


class SyncError(RuntimeError):
    pass


class SyncBlockedError(SyncError):
    pass


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def ephemeral_pool_dir() -> Path:
    return workspace_root() / ".ephemeral_pool"


def slugify_topic(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "topic"
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", raw)
    slug = slug.strip("_")
    return slug[:80] or "topic"


def ensure_task_flow_engine_importable() -> None:
    skill_root = workspace_root() / "user_skills" / "task-flow-engine"
    if not skill_root.exists():
        raise SyncBlockedError(f"⚠️[SYNC_BLOCKED: TASK_FLOW_ENGINE_MISSING] 找不到 task-flow-engine：{skill_root}")
    skill_root_str = str(skill_root)
    if skill_root_str not in sys.path:
        sys.path.insert(0, skill_root_str)


@dataclass(frozen=True)
class SheetInfo:
    sheet_id: str
    title: str
    row_count: int
    column_count: int


@dataclass
class DiffItem:
    primary_key: str
    status: str
    local_record: Optional[Dict[str, Any]] = None
    remote_record: Optional[Dict[str, Any]] = None
    changed_fields: Optional[Dict[str, Dict[str, Any]]] = None
    remote_row_index: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "primary_key": self.primary_key,
            "status": self.status,
        }
        if self.local_record is not None:
            payload["local_record"] = self.local_record
        if self.remote_record is not None:
            payload["remote_record"] = self.remote_record
        if self.changed_fields:
            payload["changed_fields"] = self.changed_fields
        if self.remote_row_index is not None:
            payload["remote_row_index"] = self.remote_row_index
        return payload


class LarkSheetsCLI:
    def __init__(self, cli_path: Optional[str | Path] = None):
        self.cli_path = Path(cli_path) if cli_path else self._auto_find_cli()

    def _auto_find_cli(self) -> Path:
        env = os.environ.get("LARK_SHEETS_CLI")
        candidates: List[Path] = []
        if env:
            candidates.append(Path(env))
        for cmd in ("lark-sheets-cli", "lark-cli"):
            resolved = shutil.which(cmd)
            if resolved:
                candidates.append(Path(resolved))
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise SyncBlockedError("⚠️[SYNC_BLOCKED: MCP_UNAVAILABLE] 找不到 lark-sheets-cli / lark-cli。")

    def _run(self, args: Sequence[str]) -> Dict[str, Any]:
        cmd = [str(self.cli_path), *args]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            combined = "\n".join(part for part in [stdout, stderr] if part)
            raise SyncBlockedError(
                "⚠️[SYNC_BLOCKED: MCP_UNAVAILABLE] lark-cli 执行失败\n"
                f"cmd: {' '.join(cmd)}\n{combined}"
            )
        obj = self._parse_json(proc.stdout)
        if isinstance(obj, dict) and obj.get("ok") is False:
            raise SyncBlockedError(
                "⚠️[SYNC_BLOCKED: MCP_UNAVAILABLE] lark-cli 返回 ok=false\n"
                f"{json.dumps(obj, ensure_ascii=False)}"
            )
        if isinstance(obj, dict) and "code" in obj and obj.get("code") not in (0, "0"):
            raise SyncBlockedError(
                "⚠️[SYNC_BLOCKED: MCP_UNAVAILABLE] lark-cli 返回 code!=0\n"
                f"{json.dumps(obj, ensure_ascii=False)}"
            )
        return obj

    @staticmethod
    def _parse_json(text: str) -> Any:
        text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text or "").strip()
        if not text:
            raise SyncBlockedError("⚠️[SYNC_BLOCKED: MCP_UNAVAILABLE] lark-cli 返回空输出。")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for line in reversed(lines):
            if not re.match(r"^[\[{]", line):
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        decoder = json.JSONDecoder()
        for match in re.finditer(r"\{|\[", text):
            try:
                obj, _ = decoder.raw_decode(text[match.start() :])
                return obj
            except json.JSONDecodeError:
                continue
        raise SyncBlockedError("⚠️[SYNC_BLOCKED: MCP_UNAVAILABLE] 无法解析 lark-cli JSON 输出。")

    def wiki_get_node(self, wiki_token: str) -> Dict[str, Any]:
        return self._run(["wiki", "spaces", "get_node", "--params", json.dumps({"token": wiki_token}, ensure_ascii=False)])

    def resolve_spreadsheet_token(self, url_or_token: str) -> str:
        text = (url_or_token or "").strip()
        if not text:
            raise SyncError("feishu_sheet_url 不能为空")
        if not text.startswith("http"):
            return text
        wiki_match = re.search(r"/wiki/([A-Za-z0-9]+)", text)
        if wiki_match:
            node = self.wiki_get_node(wiki_match.group(1))
            node_data = node.get("data", {}).get("node", {})
            if node_data.get("obj_type") != "sheet":
                raise SyncError(
                    f"给定 wiki 链接解析后不是电子表格，而是 {node_data.get('obj_type')}。"
                )
            obj_token = str(node_data.get("obj_token") or "").strip()
            if not obj_token:
                raise SyncError("wiki 节点缺少 obj_token，无法继续读取电子表格。")
            return obj_token
        sheet_match = re.search(r"/sheets/([A-Za-z0-9]+)", text)
        if sheet_match:
            return sheet_match.group(1)
        raise SyncError(f"无法从 feishu_sheet_url 解析 spreadsheet token: {text}")

    def info(self, spreadsheet_token: str) -> List[SheetInfo]:
        obj = self._run(["sheets", "+info", "--spreadsheet-token", spreadsheet_token])
        sheets = obj.get("data", {}).get("sheets", {}).get("sheets", [])
        result: List[SheetInfo] = []
        for sheet in sheets:
            gp = sheet.get("grid_properties", {})
            result.append(
                SheetInfo(
                    sheet_id=str(sheet.get("sheet_id") or ""),
                    title=str(sheet.get("title") or ""),
                    row_count=int(gp.get("row_count", 0) or 0),
                    column_count=int(gp.get("column_count", 0) or 0),
                )
            )
        if not result:
            raise SyncError("目标飞书表格没有可用工作表。")
        return result

    def read_range(self, spreadsheet_token: str, a1_range: str) -> List[List[Any]]:
        obj = self._run(["sheets", "+read", "--spreadsheet-token", spreadsheet_token, "--range", a1_range])
        return obj.get("data", {}).get("valueRange", {}).get("values", [])

    def write_range(self, spreadsheet_token: str, a1_range: str, values: List[List[Any]]) -> Dict[str, Any]:
        return self._run(
            [
                "sheets",
                "+write",
                "--spreadsheet-token",
                spreadsheet_token,
                "--range",
                a1_range,
                "--values",
                json.dumps(values, ensure_ascii=False),
            ]
        )


def col_num_to_a1(col_num_1_based: int) -> str:
    if col_num_1_based <= 0:
        raise ValueError(f"invalid col num: {col_num_1_based}")
    letters: List[str] = []
    n = col_num_1_based
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


def load_field_mapping(raw: str) -> Dict[str, str]:
    text = (raw or "").strip()
    if not text:
        raise SyncError("field_mapping 不能为空")
    candidate_path = Path(text)
    if candidate_path.exists():
        content = candidate_path.read_text(encoding="utf-8")
    else:
        content = text
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = yaml.safe_load(content)
    if not isinstance(data, dict) or not data:
        raise SyncError("field_mapping 必须是非空字典（本地字段 -> 飞书列名）。")
    normalized: Dict[str, str] = {}
    for local_key, remote_col in data.items():
        lk = str(local_key).strip()
        rv = str(remote_col).strip()
        if not lk or not rv:
            raise SyncError("field_mapping 中不允许出现空字段名或空列名。")
        normalized[lk] = rv
    return normalized


def parse_local_records(local_path: Path) -> List[Dict[str, Any]]:
    if not local_path.exists():
        raise SyncError(f"本地文件不存在：{local_path}")
    content = local_path.read_text(encoding="utf-8")
    suffix = local_path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        return _coerce_records(yaml.safe_load(content), source=str(local_path))
    if suffix == ".md":
        return _parse_markdown_yaml_blocks(content, source=str(local_path))
    raise SyncError("local_path 仅支持 .md / .yaml / .yml 文件。")


def _parse_markdown_yaml_blocks(content: str, source: str) -> List[Dict[str, Any]]:
    pattern = re.compile(r"```(?:yaml|yml)\s*(.*?)```", re.IGNORECASE | re.DOTALL)
    blocks = pattern.findall(content)
    if not blocks:
        raise SyncError(f"本地 Markdown 未找到 YAML 代码块：{source}")
    records: List[Dict[str, Any]] = []
    for idx, block in enumerate(blocks, start=1):
        try:
            parsed = yaml.safe_load(block)
        except Exception as exc:
            raise SyncError(f"第 {idx} 个 YAML 代码块解析失败：{exc}") from exc
        records.extend(_coerce_records(parsed, source=f"{source}#block{idx}"))
    if not records:
        raise SyncError(f"本地 Markdown 虽包含 YAML 代码块，但未解析出记录：{source}")
    return records


def _coerce_records(parsed: Any, source: str) -> List[Dict[str, Any]]:
    if parsed is None:
        return []
    if isinstance(parsed, list):
        records = []
        for idx, item in enumerate(parsed, start=1):
            if not isinstance(item, dict):
                raise SyncError(f"{source} 第 {idx} 条记录不是对象，无法继续。")
            records.append(item)
        return records
    if isinstance(parsed, dict):
        if isinstance(parsed.get("records"), list):
            return _coerce_records(parsed.get("records"), source=source)
        return [parsed]
    raise SyncError(f"{source} 不是合法记录结构（需为 list[dict] / dict / dict.records）。")


def ensure_primary_key_uniqueness(records: List[Dict[str, Any]], primary_key: str, side: str) -> None:
    seen: Dict[str, int] = {}
    for idx, record in enumerate(records, start=1):
        key = str(record.get(primary_key) or "").strip()
        if not key:
            raise SyncError(f"{side} 第 {idx} 条记录缺少主键字段 {primary_key}。")
        if key in seen:
            raise SyncError(f"{side} 主键冲突：{primary_key}={key}（首次出现在第 {seen[key]} 条，第 {idx} 条重复）。")
        seen[key] = idx


def is_placeholder_primary_key(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    upper = text.upper()
    placeholder_tokens = ["YYYY", "MM", "DD", "NNN", "<", ">", "EXAMPLE", "示例"]
    return any(token in upper for token in placeholder_tokens)


def split_placeholder_records(
    records: List[Dict[str, Any]],
    primary_key: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    kept: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for record in records:
        if is_placeholder_primary_key(record.get(primary_key)):
            skipped.append(record)
        else:
            kept.append(record)
    return kept, skipped


def normalize_scalar(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def values_equal(left: Any, right: Any) -> bool:
    nl = normalize_scalar(left)
    nr = normalize_scalar(right)
    if nl == nr:
        return True
    sl = str(nl)
    sr = str(nr)
    date_only = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    datetime_like = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T].*$")
    if date_only.match(sl):
        m = datetime_like.match(sr)
        if m and m.group(1) == sl:
            return True
    if date_only.match(sr):
        m = datetime_like.match(sl)
        if m and m.group(1) == sr:
            return True
    return False


def select_best_sheet(cli: LarkSheetsCLI, spreadsheet_token: str, field_mapping: Dict[str, str]) -> Tuple[SheetInfo, List[Optional[str]]]:
    expected_headers = set(field_mapping.values())
    candidates: List[Tuple[int, SheetInfo, List[Optional[str]]]] = []
    for sheet in cli.info(spreadsheet_token):
        end_col = col_num_to_a1(max(sheet.column_count, 1))
        header_range = f"{sheet.sheet_id}!A1:{end_col}1"
        raw = cli.read_range(spreadsheet_token, header_range)
        header_row = raw[0] if raw else []
        padded: List[Optional[str]] = []
        for idx in range(sheet.column_count):
            if idx < len(header_row):
                cell = header_row[idx]
                cell_text = str(cell).strip() if cell is not None else ""
                padded.append(cell_text or None)
            else:
                padded.append(None)
        score = sum(1 for h in padded if h in expected_headers)
        candidates.append((score, sheet, padded))
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_score, best_sheet, best_header = candidates[0]
    if best_score <= 0:
        raise SyncError("飞书表格中没有任何工作表匹配 field_mapping 对应列名。")
    if len(candidates) > 1 and candidates[1][0] == best_score:
        raise SyncError(
            "多个工作表与 field_mapping 命中分数相同，无法自动判定目标 sheet，请人工收窄目标表。"
        )
    return best_sheet, best_header


def validate_required_columns(header: List[Optional[str]], field_mapping: Dict[str, str]) -> None:
    existing = {item for item in header if item}
    missing = [remote for remote in field_mapping.values() if remote not in existing]
    if missing:
        raise SyncError(
            "飞书表格缺少指定列，请人工先创建后再重试：" + ", ".join(missing)
        )


def map_local_to_remote(local_record: Dict[str, Any], field_mapping: Dict[str, str], primary_key: str) -> Dict[str, Any]:
    if primary_key not in local_record:
        raise SyncError(f"本地记录缺少主键字段：{primary_key}")
    remote: Dict[str, Any] = {}
    for local_field, remote_col in field_mapping.items():
        remote[remote_col] = local_record.get(local_field)
    return remote


def read_remote_rows(
    cli: LarkSheetsCLI,
    spreadsheet_token: str,
    sheet: SheetInfo,
    header: List[Optional[str]],
    primary_key_remote_col: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Tuple[Dict[str, Any], int]], Optional[int]]:
    end_col = col_num_to_a1(max(sheet.column_count, 1))
    value_range = f"{sheet.sheet_id}!A1:{end_col}{max(sheet.row_count, 2)}"
    values = cli.read_range(spreadsheet_token, value_range)
    rows: List[Dict[str, Any]] = []
    indexed: Dict[str, Tuple[Dict[str, Any], int]] = {}
    first_empty_row: Optional[int] = None
    pk_index = _header_index(header, primary_key_remote_col)
    for row_idx in range(2, sheet.row_count + 1):
        row = values[row_idx - 1] if row_idx - 1 < len(values) else []
        if _row_is_empty(row):
            if first_empty_row is None:
                first_empty_row = row_idx
            continue
        row_map = {}
        for col_idx, col_name in enumerate(header):
            if not col_name:
                continue
            cell = row[col_idx] if col_idx < len(row) else None
            row_map[col_name] = cell
        pk_value = str(row[pk_index] if pk_index < len(row) and row[pk_index] is not None else "").strip()
        if not pk_value:
            continue
        rows.append(row_map)
        if pk_value in indexed:
            prev_row = indexed[pk_value][1]
            raise SyncError(f"飞书表格主键冲突：{primary_key_remote_col}={pk_value}（第 {prev_row} 行与第 {row_idx} 行重复）。")
        indexed[pk_value] = (row_map, row_idx)
    return rows, indexed, first_empty_row


def _row_is_empty(row: Sequence[Any]) -> bool:
    return all(str(cell).strip() == "" for cell in row if cell is not None) and not any(cell is not None and str(cell).strip() for cell in row)


def _header_index(header: List[Optional[str]], target: str) -> int:
    for idx, col in enumerate(header):
        if col == target:
            return idx
    raise SyncError(f"表头中找不到列：{target}")


def build_aligned_row(header: List[Optional[str]], remote_record: Dict[str, Any]) -> List[Any]:
    row: List[Any] = [""] * len(header)
    for idx, col_name in enumerate(header):
        if not col_name:
            continue
        value = remote_record.get(col_name)
        row[idx] = "" if value is None else normalize_write_value(value)
    return row


def normalize_write_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def diff_records(
    local_records: List[Dict[str, Any]],
    remote_indexed: Dict[str, Tuple[Dict[str, Any], int]],
    primary_key: str,
    field_mapping: Dict[str, str],
) -> List[DiffItem]:
    diffs: List[DiffItem] = []
    seen_remote_keys: set[str] = set()
    primary_key_remote_col = field_mapping[primary_key]
    for local_record in local_records:
        pk = str(local_record.get(primary_key) or "").strip()
        mapped_local = map_local_to_remote(local_record, field_mapping, primary_key)
        if pk not in remote_indexed:
            diffs.append(
                DiffItem(primary_key=pk, status="new", local_record=local_record, changed_fields={})
            )
            continue
        remote_record, row_index = remote_indexed[pk]
        seen_remote_keys.add(pk)
        changed: Dict[str, Dict[str, Any]] = {}
        for local_field, remote_col in field_mapping.items():
            local_value = mapped_local.get(remote_col)
            remote_value = remote_record.get(remote_col)
            if not values_equal(local_value, remote_value):
                changed[local_field] = {
                    "column": remote_col,
                    "local": local_value,
                    "remote": remote_value,
                }
        if changed:
            diffs.append(
                DiffItem(
                    primary_key=pk,
                    status="updated",
                    local_record=local_record,
                    remote_record=remote_record,
                    changed_fields=changed,
                    remote_row_index=row_index,
                )
            )
        else:
            diffs.append(
                DiffItem(
                    primary_key=pk,
                    status="ok",
                    local_record=local_record,
                    remote_record=remote_record,
                    remote_row_index=row_index,
                )
            )
    local_keys = {str(item.get(primary_key) or "").strip() for item in local_records}
    for pk, (remote_record, row_index) in remote_indexed.items():
        if pk in local_keys:
            continue
        diffs.append(
            DiffItem(
                primary_key=pk,
                status="orphan",
                remote_record=remote_record,
                remote_row_index=row_index,
            )
        )
    status_order = {"new": 0, "updated": 1, "orphan": 2, "ok": 3}
    diffs.sort(key=lambda item: (status_order.get(item.status, 99), item.primary_key))
    return diffs


def verify_row_readback(
    cli: LarkSheetsCLI,
    spreadsheet_token: str,
    sheet_id: str,
    row_index: int,
    expected_row: List[Any],
) -> List[Any]:
    end_col = col_num_to_a1(len(expected_row))
    a1_range = f"{sheet_id}!A{row_index}:{end_col}{row_index}"
    time.sleep(2)
    values = cli.read_range(spreadsheet_token, a1_range)
    actual = values[0] if values else []
    padded_actual = list(actual) + [""] * max(0, len(expected_row) - len(actual))
    for idx, expected in enumerate(expected_row):
        actual_value = padded_actual[idx] if idx < len(padded_actual) else ""
        if not values_equal(expected, actual_value):
            raise SyncError(
                f"写后回捞校验失败：row={row_index}, col={idx + 1}, expected={expected!r}, actual={actual_value!r}"
            )
    return padded_actual[: len(expected_row)]


def maybe_mark_drift(
    cli: LarkSheetsCLI,
    spreadsheet_token: str,
    sheet: SheetInfo,
    header: List[Optional[str]],
    row_index: Optional[int],
) -> Optional[str]:
    if row_index is None:
        return None
    for candidate in ("同步状态", "sync_status", "巡检状态"):
        if candidate in header:
            col_idx = _header_index(header, candidate) + 1
            a1 = f"{sheet.sheet_id}!{col_num_to_a1(col_idx)}{row_index}"
            cli.write_range(spreadsheet_token, a1, [["⚠️[DRIFT_DETECTED]"]])
            return candidate
    return None


def write_sync_changes(
    cli: LarkSheetsCLI,
    spreadsheet_token: str,
    sheet: SheetInfo,
    header: List[Optional[str]],
    diffs: List[DiffItem],
    field_mapping: Dict[str, str],
    primary_key: str,
    mode: str,
    first_empty_row: Optional[int],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    applied: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    next_empty_row = first_empty_row or 2
    end_col = col_num_to_a1(len(header))
    for item in diffs:
        if item.status not in {"new", "updated"}:
            continue
        mapped = map_local_to_remote(item.local_record or {}, field_mapping, primary_key)
        aligned_row = build_aligned_row(header, mapped)
        row_index = item.remote_row_index if item.status == "updated" else next_empty_row
        target_range = f"{sheet.sheet_id}!A{row_index}:{end_col}{row_index}"
        old_snapshot = item.remote_record if item.remote_record is not None else {}
        try:
            cli.write_range(spreadsheet_token, target_range, [aligned_row])
            readback = verify_row_readback(cli, spreadsheet_token, sheet.sheet_id, row_index, aligned_row)
            applied.append(
                {
                    "primary_key": item.primary_key,
                    "action": item.status,
                    "row_index": row_index,
                    "old_remote": old_snapshot,
                    "new_remote": mapped,
                    "readback": readback,
                }
            )
            if item.status == "new":
                next_empty_row = row_index + 1
        except Exception as exc:
            drift_column = None
            if mode == "patrol":
                try:
                    drift_column = maybe_mark_drift(cli, spreadsheet_token, sheet, header, row_index)
                except Exception:
                    drift_column = None
            failures.append(
                {
                    "primary_key": item.primary_key,
                    "action": item.status,
                    "row_index": row_index,
                    "error": str(exc),
                    "drift_tag_column": drift_column,
                }
            )
    return applied, failures


def summarize_diffs(diffs: List[DiffItem]) -> Dict[str, int]:
    summary = {"new": 0, "updated": 0, "orphan": 0, "ok": 0}
    for item in diffs:
        summary[item.status] = summary.get(item.status, 0) + 1
    return summary


def build_report(
    *,
    local_path: Path,
    feishu_sheet_url: str,
    spreadsheet_token: str,
    sheet: SheetInfo,
    primary_key: str,
    field_mapping: Dict[str, str],
    mode: str,
    diffs: List[DiffItem],
    applied: List[Dict[str, Any]],
    failures: List[Dict[str, Any]],
    skipped_placeholders: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "mode": mode,
        "local_path": str(local_path),
        "feishu_sheet_url": feishu_sheet_url,
        "spreadsheet_token": spreadsheet_token,
        "sheet": {
            "sheet_id": sheet.sheet_id,
            "title": sheet.title,
            "row_count": sheet.row_count,
            "column_count": sheet.column_count,
        },
        "primary_key": primary_key,
        "field_mapping": field_mapping,
        "skipped_placeholders": skipped_placeholders,
        "summary": summarize_diffs(diffs),
        "diffs": [item.to_dict() for item in diffs],
        "writes": {
            "applied": applied,
            "failures": failures,
        },
    }


def run_chat_preflight(*, usage: str, requested_chat_id: Optional[str] = None) -> Dict[str, Any]:
    ensure_task_flow_engine_importable()
    try:
        from task_flow_engine.chat_registry import ChatRegistryError, get_chat_registry_entry
        from task_flow_engine.chat_registry_sync import ChatRegistrySyncError, FeishuChatSearchClient
    except Exception as exc:  # pragma: no cover
        raise SyncBlockedError(f"⚠️[SYNC_BLOCKED: CHAT_PREFLIGHT_IMPORT_FAILED] {exc}") from exc

    try:
        entry = get_chat_registry_entry(usage=usage)
        entry.assert_requested_chat_id(requested_chat_id)
        client = FeishuChatSearchClient()
        metadata = client.get_chat_metadata(entry.chat_id, entry.lookup_query)
        entry.assert_metadata(metadata)
    except (ChatRegistryError, ChatRegistrySyncError, FileNotFoundError) as exc:
        raise SyncBlockedError(f"⚠️[SYNC_BLOCKED: CHAT_PREFLIGHT_FAILED] {exc}") from exc

    return {
        "usage": usage,
        "chat_id": entry.chat_id,
        "lookup_query": entry.lookup_query,
        "expected_name_keywords": list(entry.expected_name_keywords),
        "actual_name": str(metadata.get("name") or "").strip(),
    }


def build_private_notify_payload(report: Dict[str, Any], args: argparse.Namespace) -> Path:
    task_id = (args.notify_task_id or "").strip()
    topic = (args.notify_topic or "").strip()
    if not task_id or not topic:
        raise SyncError("notify 模式必须同时提供 --notify-task-id 与 --notify-topic。")

    payload = {
        "task_id": task_id,
        "topic": topic,
        "zh_cn": {
            "title": topic,
            "content": [],
        },
    }
    lines = payload["zh_cn"]["content"]
    summary = report.get("summary") or {}
    writes = report.get("writes") or {}
    sheet = report.get("sheet") or {}
    lines.append([
        {
            "tag": "text",
            "text": f"同步结果：{report.get('mode', 'sync')} 已完成，目标表为「{sheet.get('title', '[unknown]')}」。",
        }
    ])
    lines.append([
        {
            "tag": "text",
            "text": (
                f"统计摘要：新增 {summary.get('new', 0)} 条，更新 {summary.get('updated', 0)} 条，"
                f"一致 {summary.get('ok', 0)} 条，远端孤儿 {summary.get('orphan', 0)} 条。"
            ),
        }
    ])
    lines.append([
        {
            "tag": "text",
            "text": (
                f"写入执行：成功 {len(writes.get('applied') or [])} 条，失败 {len(writes.get('failures') or [])} 条。"
            ),
        }
    ])
    if report.get("skipped_placeholders"):
        lines.append([
            {
                "tag": "text",
                "text": f"占位样例已跳过：{len(report.get('skipped_placeholders') or [])} 条。",
            }
        ])
    if args.notify_chat_usage:
        preflight = report.get("chat_preflight") or {}
        lines.append([
            {
                "tag": "text",
                "text": (
                    f"群 preflight：usage={preflight.get('usage', args.notify_chat_usage)}；"
                    f"chat_id={preflight.get('chat_id', '[missing]')}；"
                    f"群名={preflight.get('actual_name', '[missing]')}。"
                ),
            }
        ])
    sheet_url = str(report.get("feishu_sheet_url") or "").strip()
    if sheet_url:
        lines.append([
            {
                "tag": "a",
                "text": "打开目标飞书表格",
                "href": sheet_url,
            }
        ])

    topic_slug = slugify_topic(args.notify_topic_slug or topic)
    payload_dir = ephemeral_pool_dir()
    payload_dir.mkdir(parents=True, exist_ok=True)
    payload_path = payload_dir / f"[{task_id}]_{topic_slug}.post.json"
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload_path


def send_private_notify_via_ct(payload_path: Path, args: argparse.Namespace) -> Dict[str, Any]:
    task_id = (args.notify_task_id or "").strip()
    topic = (args.notify_topic or "").strip()
    receiver = (args.notify_receiver_id or "").strip()
    id_type = (args.notify_id_type or "email").strip() or "email"
    if not receiver:
        raise SyncError("notify 模式必须提供 --notify-receiver-id。")

    skill_root = workspace_root() / "user_skills" / "centralized-transmitter"
    script_path = skill_root / "scripts" / "centralized_transmitter.py"
    if not script_path.exists():
        raise SyncBlockedError(f"⚠️[SYNC_BLOCKED: CT_MISSING] 找不到 centralized_transmitter.py：{script_path}")

    preflight_cmd = [
        sys.executable,
        str(script_path),
        "preflight",
        str(payload_path),
        f"--task-id={task_id}",
        f"--topic={topic}",
        "--caller-role=main",
    ]
    preflight_proc = subprocess.run(preflight_cmd, cwd=skill_root, capture_output=True, text=True)
    if preflight_proc.returncode != 0:
        detail = (preflight_proc.stderr or preflight_proc.stdout or "").strip()
        raise SyncError(f"centralized-transmitter preflight 失败：{detail or 'unknown error'}")

    result: Dict[str, Any] = {
        "payload_path": str(payload_path),
        "preflight": json.loads((preflight_proc.stdout or "{}").strip()),
        "send": {
            "dry_run": bool(args.notify_dry_run),
            "receiver_id": receiver,
            "id_type": id_type,
            "task_id": task_id,
            "topic": topic,
            "caller_role": "comm-agent",
            "command_preview": " ".join([
                quote(part) for part in [
                    sys.executable,
                    str(script_path),
                    "send",
                    receiver,
                    "post",
                    str(payload_path),
                    f"--id-type={id_type}",
                    f"--task-id={task_id}",
                    f"--topic={topic}",
                    "--caller-role=comm-agent",
                ]
            ]),
        },
    }
    if args.notify_dry_run:
        return result

    send_cmd = [
        sys.executable,
        str(script_path),
        "send",
        receiver,
        "post",
        str(payload_path),
        f"--id-type={id_type}",
        f"--task-id={task_id}",
        f"--topic={topic}",
        "--caller-role=comm-agent",
    ]
    send_proc = subprocess.run(send_cmd, cwd=skill_root, capture_output=True, text=True)
    if send_proc.returncode != 0:
        detail = (send_proc.stderr or send_proc.stdout or "").strip()
        raise SyncError(f"centralized-transmitter send 失败：{detail or 'unknown error'}")
    result["send"]["stdout"] = (send_proc.stdout or "").strip()
    return result


def maybe_emit_private_notify(report: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    if not args.notify_chat_usage and not args.notify_receiver_id:
        return report
    if args.notify_chat_usage:
        report["chat_preflight"] = run_chat_preflight(
            usage=args.notify_chat_usage,
            requested_chat_id=args.notify_chat_id,
        )
    if args.notify_receiver_id:
        payload_path = build_private_notify_payload(report, args)
        report["notification"] = send_private_notify_via_ct(payload_path, args)
    return report


def run_sync(args: argparse.Namespace) -> Dict[str, Any]:
    local_path = Path(args.local_path)
    field_mapping = load_field_mapping(args.field_mapping)
    primary_key = args.primary_key.strip()
    if primary_key not in field_mapping:
        raise SyncError("field_mapping 必须包含 primary_key 对应的列映射。")
    local_records = parse_local_records(local_path)
    local_records, skipped_placeholders = split_placeholder_records(local_records, primary_key)
    ensure_primary_key_uniqueness(local_records, primary_key, side="本地文件")

    cli = LarkSheetsCLI()
    spreadsheet_token = cli.resolve_spreadsheet_token(args.feishu_sheet_url)
    sheet, header = select_best_sheet(cli, spreadsheet_token, field_mapping)
    validate_required_columns(header, field_mapping)
    primary_key_remote_col = field_mapping[primary_key]
    remote_rows, remote_indexed, first_empty_row = read_remote_rows(
        cli,
        spreadsheet_token,
        sheet,
        header,
        primary_key_remote_col,
    )
    diffs = diff_records(local_records, remote_indexed, primary_key, field_mapping)

    applied: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    if args.mode in {"sync", "patrol"}:
        applied, failures = write_sync_changes(
            cli,
            spreadsheet_token,
            sheet,
            header,
            diffs,
            field_mapping,
            primary_key,
            args.mode,
            first_empty_row,
        )

    report = build_report(
        local_path=local_path,
        feishu_sheet_url=args.feishu_sheet_url,
        spreadsheet_token=spreadsheet_token,
        sheet=sheet,
        primary_key=primary_key,
        field_mapping=field_mapping,
        mode=args.mode,
        diffs=diffs,
        applied=applied,
        failures=failures,
        skipped_placeholders=skipped_placeholders,
    )
    if remote_rows is not None:
        report["remote_row_count"] = len(remote_rows)
    return maybe_emit_private_notify(report, args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="字段级人机同步：本地文件 ↔ 飞书表格（本地为 SSOT）")
    parser.add_argument("--local-path", required=True, help="本地文件路径（Markdown/YAML）")
    parser.add_argument("--feishu-sheet-url", required=True, help="飞书表格 URL / Token / wiki URL")
    parser.add_argument("--primary-key", required=True, help="主键字段名，例如 id")
    parser.add_argument(
        "--field-mapping",
        required=True,
        help="本地字段 -> 飞书列名映射，支持 JSON 字符串或 JSON/YAML 文件路径",
    )
    parser.add_argument("--mode", choices=["audit", "sync", "patrol"], required=True)
    parser.add_argument("--report-out", help="可选，输出 JSON 报告路径")
    parser.add_argument("--notify-receiver-id", help="可选，通知接收方（建议邮箱）")
    parser.add_argument("--notify-id-type", default="email", help="通知接收方 ID 类型，默认 email")
    parser.add_argument("--notify-task-id", help="可选，通知任务 ID；启用通知时必填")
    parser.add_argument("--notify-topic", help="可选，通知主题；启用通知时必填")
    parser.add_argument("--notify-topic-slug", help="可选，自定义 payload 文件名 slug")
    parser.add_argument("--notify-chat-usage", help="可选，发送前先按 Chat Registry 做群 preflight 的 usage")
    parser.add_argument("--notify-chat-id", help="可选，配合 --notify-chat-usage 校验指定 chat_id")
    parser.add_argument("--notify-dry-run", action="store_true", help="仅跑 payload + preflight，不执行真实发送")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = run_sync(args)
    except SyncBlockedError as exc:
        payload = {"status": "blocked", "error": str(exc)}
        if args.report_out:
            out_path = Path(args.report_out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    except SyncError as exc:
        payload = {"status": "error", "error": str(exc)}
        if args.report_out:
            out_path = Path(args.report_out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    payload = {"status": "ok", "report": report}
    if args.report_out:
        out_path = Path(args.report_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
