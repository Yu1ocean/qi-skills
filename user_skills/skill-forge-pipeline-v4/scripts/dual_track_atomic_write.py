#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Dual-Track Atomic Write Guard (决策录入双轨原子写入护栏)

关联决策：DEC-20260821-001「决策录入必须双轨原子写入，单轨成功即判失败」。

事故背景：forge 子特工只写飞书镜像台账，从未 append 本地 SSOT
`memory/topics/decision-registry.md`，形成孤儿行，漂移数天不可见。

本脚本是 CDA L3 断言层的物理熔断器：

1. 事务块语义：飞书镜像写入成功后，**立刻**执行本地 SSOT append；
   两步绑定为一个事务，中间不允许插入其他动作、不允许等待用户确认。
2. RAW read-after-write 双轨断言：
   - 轨道 A（local）：回读本地文件，解析最后一条 `- id: DEC-...`，断言 == 目标 ID。
   - 轨道 B（mirror）：回读飞书镜像末条记录 ID，断言 == 目标 ID。
3. 任一轨失败 → `raise` 熔断（严禁静默成功），并把该条目标记为「孤儿待修复」
   写入死信队列 `.ephemeral_pool/orphan_decisions.jsonl`。

底层鉴权与飞书读写链路复用 `tools/sync_decision_registry.py`，不重造轮子。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# --------------------------------------------------------------------------
# 合规默认值 (L2 Defaults)
# --------------------------------------------------------------------------
DEFAULT_MIRROR_URL = "https://bytedance.larkoffice.com/wiki/PnnDwYr13imUyVkVPshc46ICnVh"
DEFAULT_SSOT_RELPATH = "memory/topics/decision-registry.md"
DEFAULT_DLQ_RELPATH = ".ephemeral_pool/orphan_decisions.jsonl"
DEFAULT_RAW_SLEEP_SECONDS = 2
DEFAULT_DECISION_ID_PATTERN = r"^DEC-\d{8}-\d{3}$"
DEFAULT_REQUIRED_ENTRY_FIELDS = ["id", "title", "type", "scope", "status", "chosen"]
DEFAULT_SUGGESTED_FIX = (
    "运行 python3 user_skills/skill-forge-pipeline-v4/scripts/dual_track_atomic_write.py "
    "--verify-only <DEC-ID> 复核；若确认单轨缺失，用 tools/sync_decision_registry.py "
    "以本地 SSOT 为准修复飞书镜像，或手工 append 本地 SSOT 后重跑双轨断言。"
)

INJECTED_BAD_ID = "DEC-00000000-000"  # 故障注入用的哨兵 ID
ID_PATTERN = re.compile(DEFAULT_DECISION_ID_PATTERN)
LOCAL_ID_LINE_PATTERN = re.compile(r"^\s*-\s+id:\s*(DEC-\d{8}-\d{3})\s*$", re.MULTILINE)
YAML_BLOCK_PATTERN = re.compile(r"```yaml\n(.*?)\n```", re.DOTALL)


class DualTrackWriteError(RuntimeError):
    """双轨原子写入熔断异常。"""


def get_workspace_root() -> Path:
    # scripts/ -> skill dir -> user_skills -> workspace root
    return Path(__file__).resolve().parents[3]


WORKSPACE_ROOT = get_workspace_root()
TOOLS_DIR = WORKSPACE_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def _load_mirror_backend():
    """延迟导入飞书镜像读写链路，避免 --dry-run 场景强依赖鉴权环境。"""
    try:
        import sync_decision_registry as backend  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise DualTrackWriteError(
            f"无法加载飞书镜像读写链路 tools/sync_decision_registry.py: {exc}"
        ) from exc
    return backend


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------
@dataclass
class TrackAssertion:
    track: str
    expected_id: str
    actual_id: str
    ok: bool
    evidence: str = ""


@dataclass
class DualTrackResult:
    decision_id: str
    mode: str
    assertions: List[TrackAssertion] = field(default_factory=list)
    mirror_row: Optional[int] = None
    logs: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.assertions) and all(a.ok for a in self.assertions)

    @property
    def failed_tracks(self) -> List[str]:
        return [a.track for a in self.assertions if not a.ok]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "mode": self.mode,
            "ok": self.ok,
            "mirror_row": self.mirror_row,
            "assertions": [vars(a) for a in self.assertions],
            "failed_tracks": self.failed_tracks,
            "logs": self.logs,
        }


# --------------------------------------------------------------------------
# L3 校验器 / 断言器
# --------------------------------------------------------------------------
def validate_decision_id(decision_id: str) -> str:
    decision_id = (decision_id or "").strip()
    if not ID_PATTERN.match(decision_id):
        raise DualTrackWriteError(
            f"决策 ID 非法：{decision_id!r}，必须匹配 {DEFAULT_DECISION_ID_PATTERN}"
        )
    return decision_id


def validate_entry_yaml(entry_text: str, decision_id: str) -> Dict[str, Any]:
    """校验待写入的 YAML 条目块，返回解析后的单条决策记录。"""
    if not (entry_text or "").strip():
        raise DualTrackWriteError("待写入条目为空，拒绝执行双轨写入")

    body = entry_text
    blocks = YAML_BLOCK_PATTERN.findall(entry_text)
    if blocks:
        body = blocks[-1]

    parsed = yaml.safe_load(body)
    if isinstance(parsed, dict):
        records = [parsed]
    elif isinstance(parsed, list):
        records = [x for x in parsed if isinstance(x, dict)]
    else:
        raise DualTrackWriteError("条目 YAML 解析失败：既不是 mapping 也不是 list")

    matched = [r for r in records if str(r.get("id", "")).strip() == decision_id]
    if not matched:
        raise DualTrackWriteError(
            f"条目 YAML 中未找到目标决策 ID {decision_id}，实际 ID="
            f"{[str(r.get('id')) for r in records]}"
        )
    record = matched[-1]

    missing = [f for f in DEFAULT_REQUIRED_ENTRY_FIELDS if not str(record.get(f, "")).strip()]
    if missing:
        raise DualTrackWriteError(f"条目缺少必填字段：{missing}")
    return record


def validate_ssot_path(ssot_path: Path) -> Path:
    if not ssot_path.exists():
        raise DualTrackWriteError(f"本地 SSOT 文件不存在：{ssot_path}")
    if not ssot_path.is_file():
        raise DualTrackWriteError(f"本地 SSOT 路径不是文件：{ssot_path}")
    return ssot_path


def read_local_last_decision_id(ssot_path: Path) -> str:
    text = validate_ssot_path(ssot_path).read_text(encoding="utf-8")
    ids = LOCAL_ID_LINE_PATTERN.findall(text)
    if not ids:
        raise DualTrackWriteError(f"本地 SSOT 未解析到任何 `- id: DEC-...` 条目：{ssot_path}")
    return ids[-1]


def read_local_decision_ids(ssot_path: Path) -> List[str]:
    text = validate_ssot_path(ssot_path).read_text(encoding="utf-8")
    return LOCAL_ID_LINE_PATTERN.findall(text)


def assert_local_track(
    ssot_path: Path,
    expected_id: str,
    *,
    require_last: bool = True,
    inject_failure: bool = False,
) -> TrackAssertion:
    """轨道 A：回读本地 SSOT，断言目标 ID 已落盘。"""
    ids = read_local_decision_ids(ssot_path)
    last_id = ids[-1] if ids else ""
    actual_id = last_id if require_last else (expected_id if expected_id in ids else last_id)
    if inject_failure:
        # 故障注入：强制该轨回读结果失配，用于验证 raise + 死信队列链路
        last_id = INJECTED_BAD_ID
        actual_id = INJECTED_BAD_ID
    ok = (actual_id == expected_id)
    return TrackAssertion(
        track="local",
        expected_id=expected_id,
        actual_id=actual_id,
        ok=ok,
        evidence=json.dumps(
            {"ssot_path": str(ssot_path), "total_entries": len(ids), "last_id": last_id},
            ensure_ascii=False,
        ),
    )


def assert_mirror_track(
    mirror_url: str,
    expected_id: str,
    *,
    require_last: bool = True,
    inject_failure: bool = False,
) -> TrackAssertion:
    """轨道 B：通过飞书链路回读镜像台账末条记录 ID，断言 == 目标 ID。"""
    backend = _load_mirror_backend()
    resolved_url, _, _ = backend.resolve_sheet_url(mirror_url)
    meta = backend.get_sheet_meta(resolved_url)
    values = backend.read_range(resolved_url, meta["sheet_id"], "A1:A1000")

    ids: List[str] = []
    last_row = 0
    for row_num, row in enumerate(values[1:], start=2):
        cell = backend.normalize_text(row[0] if row else "")
        if ID_PATTERN.match(cell):
            ids.append(cell)
            last_row = row_num

    last_id = ids[-1] if ids else ""
    actual_id = last_id if require_last else (expected_id if expected_id in ids else last_id)
    if inject_failure:
        # 故障注入：强制该轨回读结果失配，用于验证 raise + 死信队列链路
        last_id = INJECTED_BAD_ID
        actual_id = INJECTED_BAD_ID
    ok = (actual_id == expected_id)
    return TrackAssertion(
        track="mirror",
        expected_id=expected_id,
        actual_id=actual_id,
        ok=ok,
        evidence=json.dumps(
            {
                "mirror_url": resolved_url,
                "sheet_id": meta["sheet_id"],
                "total_entries": len(ids),
                "last_row": last_row,
                "last_id": last_id,
            },
            ensure_ascii=False,
        ),
    )


def assert_dual_track(
    result: DualTrackResult,
    *,
    dlq_path: Path,
    entry_text: str = "",
) -> DualTrackResult:
    """双轨一致性总断言：任一轨失败 -> 写死信队列 + raise 熔断。"""
    if result.ok:
        return result

    for track in result.failed_tracks:
        assertion = next(a for a in result.assertions if a.track == track)
        record_orphan(
            dlq_path,
            decision_id=result.decision_id,
            failed_track=track,
            error=(
                f"双轨回读断言失败：track={track} "
                f"expected={assertion.expected_id} actual={assertion.actual_id} "
                f"evidence={assertion.evidence}"
            ),
            entry_text=entry_text,
        )
    raise DualTrackWriteError(
        "❌ 双轨原子写入断言失败（已标记孤儿待修复）：\n"
        + json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
    )


def record_orphan(
    dlq_path: Path,
    *,
    decision_id: str,
    failed_track: str,
    error: str,
    entry_text: str = "",
) -> Path:
    """写入死信队列，标记「孤儿待修复」。"""
    dlq_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "decision_id": decision_id,
        "failed_track": failed_track,
        "error": error,
        "timestamp": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z"),
        "suggested_fix": DEFAULT_SUGGESTED_FIX,
        "status": "⚠️[孤儿待修复]",
        "entry_preview": (entry_text or "")[:800],
    }
    with dlq_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    print(f"🧯 已写入死信队列（孤儿待修复）：{dlq_path} track={failed_track}")
    return dlq_path


# --------------------------------------------------------------------------
# 事务块：飞书镜像写入 -> 立刻本地 append
# --------------------------------------------------------------------------
def write_mirror_track(mirror_url: str, record: Dict[str, Any]) -> int:
    """飞书镜像写入（含 sync 链路自带的 RAW 回捞），返回写入行号。"""
    backend = _load_mirror_backend()
    resolved_url, _, _ = backend.resolve_sheet_url(mirror_url)
    meta = backend.get_sheet_meta(resolved_url)
    sheet_id = meta["sheet_id"]
    values = backend.read_range(resolved_url, sheet_id, "A1:L1000")
    remote_index, last_nonempty_row = backend.build_remote_index(values)

    row = backend.local_record_to_sheet_row(record)
    decision_id = row[0]
    target_row = remote_index[decision_id]["row_num"] if decision_id in remote_index else last_nonempty_row + 1

    backend.write_range(resolved_url, sheet_id, f"A{target_row}:L{target_row}", [row])
    backend.raw_verify(resolved_url, sheet_id, target_row, row)
    return target_row


def append_local_track(ssot_path: Path, entry_text: str, decision_id: str) -> Path:
    """本地 SSOT append（幂等：已存在同 ID 则跳过写入）。"""
    validate_ssot_path(ssot_path)
    if decision_id in read_local_decision_ids(ssot_path):
        print(f"ℹ️ 本地 SSOT 已存在 {decision_id}，跳过重复 append（幂等）")
        return ssot_path

    block = entry_text.strip()
    if "```yaml" not in block:
        block = "```yaml\n" + block + "\n```"

    current = ssot_path.read_text(encoding="utf-8").rstrip("\n")
    ssot_path.write_text(current + "\n\n---\n\n" + block + "\n", encoding="utf-8")
    return ssot_path


def write_dual_track_atomic(
    *,
    entry_text: str,
    decision_id: str,
    mirror_url: str,
    ssot_path: Path,
    dlq_path: Path,
    inject_failure: str = "",
) -> DualTrackResult:
    decision_id = validate_decision_id(decision_id)
    record = validate_entry_yaml(entry_text, decision_id)
    validate_ssot_path(ssot_path)

    result = DualTrackResult(decision_id=decision_id, mode="write")

    # ---- 事务块开始：镜像写入成功后立刻 append 本地，中间不插入任何动作 ----
    try:
        mirror_row = write_mirror_track(mirror_url, record)
        result.mirror_row = mirror_row
        result.logs.append(f"mirror write ok -> row {mirror_row}")
    except Exception as exc:  # noqa: BLE001
        record_orphan(
            dlq_path,
            decision_id=decision_id,
            failed_track="mirror",
            error=f"飞书镜像写入失败：{exc}",
            entry_text=entry_text,
        )
        raise DualTrackWriteError(f"飞书镜像写入失败，事务熔断：{exc}") from exc

    try:
        append_local_track(ssot_path, entry_text, decision_id)
        result.logs.append(f"local append ok -> {ssot_path}")
    except Exception as exc:  # noqa: BLE001
        record_orphan(
            dlq_path,
            decision_id=decision_id,
            failed_track="local",
            error=f"本地 SSOT append 失败（镜像已写入，形成孤儿行）：{exc}",
            entry_text=entry_text,
        )
        raise DualTrackWriteError(
            f"本地 SSOT append 失败，镜像已写入 row {result.mirror_row}，"
            f"该条目已标记孤儿待修复：{exc}"
        ) from exc
    # ---- 事务块结束 ----

    time.sleep(DEFAULT_RAW_SLEEP_SECONDS)
    result.assertions.append(
        assert_local_track(ssot_path, decision_id, inject_failure=(inject_failure == "local"))
    )
    result.assertions.append(
        assert_mirror_track(mirror_url, decision_id, inject_failure=(inject_failure == "mirror"))
    )
    return assert_dual_track(result, dlq_path=dlq_path, entry_text=entry_text)


def verify_only(
    *,
    decision_id: str,
    mirror_url: str,
    ssot_path: Path,
    dlq_path: Path,
    inject_failure: str = "",
) -> DualTrackResult:
    """事后巡检：只做双轨回读断言，不写入。"""
    decision_id = validate_decision_id(decision_id)
    result = DualTrackResult(decision_id=decision_id, mode="verify-only")
    result.assertions.append(
        assert_local_track(
            ssot_path, decision_id, require_last=False, inject_failure=(inject_failure == "local")
        )
    )
    result.assertions.append(
        assert_mirror_track(
            mirror_url, decision_id, require_last=False, inject_failure=(inject_failure == "mirror")
        )
    )
    return assert_dual_track(result, dlq_path=dlq_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="决策录入双轨原子写入护栏（DEC-20260821-001）")
    parser.add_argument("--entry", help="待写入的决策条目 YAML 文本")
    parser.add_argument("--entry-file", help="待写入的决策条目 YAML 文件路径")
    parser.add_argument("--decision-id", help="目标决策 ID，例如 DEC-20260821-001")
    parser.add_argument("--mirror-url", default=DEFAULT_MIRROR_URL, help="飞书镜像台账 URL")
    parser.add_argument(
        "--ssot-path",
        default=str(WORKSPACE_ROOT / DEFAULT_SSOT_RELPATH),
        help="本地 SSOT 路径",
    )
    parser.add_argument(
        "--dlq-path",
        default=str(WORKSPACE_ROOT / DEFAULT_DLQ_RELPATH),
        help="孤儿待修复死信队列文件",
    )
    parser.add_argument("--dry-run", action="store_true", help="只做前置校验与计划输出，不写入")
    parser.add_argument("--verify-only", metavar="DEC-ID", help="只做双轨回读断言（事后巡检）")
    parser.add_argument(
        "--inject-failure",
        choices=["local", "mirror"],
        default="",
        help="故障注入（测试用）：人为让某一轨回读失败，验证 raise + 死信队列链路",
    )
    args = parser.parse_args()

    ssot_path = Path(args.ssot_path).resolve()
    dlq_path = Path(args.dlq_path).resolve()

    try:
        if args.verify_only:
            result = verify_only(
                decision_id=args.verify_only,
                mirror_url=args.mirror_url,
                ssot_path=ssot_path,
                dlq_path=dlq_path,
                inject_failure=args.inject_failure,
            )
            print("✅ [VERIFY-ONLY][PASS]")
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
            return 0

        entry_text = args.entry or ""
        if args.entry_file:
            entry_text = Path(args.entry_file).read_text(encoding="utf-8")
        if not args.decision_id:
            raise DualTrackWriteError("写入模式必须提供 --decision-id")

        decision_id = validate_decision_id(args.decision_id)
        record = validate_entry_yaml(entry_text, decision_id)

        if args.dry_run:
            plan = {
                "mode": "dry-run",
                "decision_id": decision_id,
                "title": str(record.get("title", "")),
                "mirror_url": args.mirror_url,
                "ssot_path": str(ssot_path),
                "dlq_path": str(dlq_path),
                "local_already_present": decision_id in read_local_decision_ids(ssot_path),
                "transaction_order": ["mirror_write", "local_append", "dual_track_assert"],
                "note": "dry-run 不产生任何写入副作用",
            }
            print("✅ [DRY-RUN][PASS] 前置校验通过，事务计划如下：")
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0

        result = write_dual_track_atomic(
            entry_text=entry_text,
            decision_id=decision_id,
            mirror_url=args.mirror_url,
            ssot_path=ssot_path,
            dlq_path=dlq_path,
            inject_failure=args.inject_failure,
        )
        print("✅ [DUAL-TRACK][PASS] 双轨原子写入完成且回读一致")
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0
    except DualTrackWriteError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"❌ [DUAL-TRACK][FATAL] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
