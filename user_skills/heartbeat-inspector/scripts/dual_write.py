#!/usr/bin/env python3
"""双轨写入（Dual-Track Write）。

把 heartbeat-inspector 的增量事件（JSON）同时写入：
- 【Aime日志】：全量审计（原始群消息快照 + 提取 JSON + 批次号）
- 【任务库】：仅写入 type=chat_task 的“任务行”

重要约束（与 feishu-doc-writing-guide 对齐）：
- 写入前必须优先通过 bytedcli-auth 进行用户身份鉴权（避免 Bot 身份 403 视野不一致）
- 实际读写通过 inner_skills/lark-sheets 的 CLI 完成（避免脚本内直连 OpenAPI）

本模块既可被 `scripts/run_inspector.py` 内部 import 调用，也提供 CLI 入口供单独运行。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


# 兼容两种运行方式：
# 1) 作为包导入：from scripts.dual_write import DualTrackWriter
# 2) 直接执行：python3 scripts/dual_write.py ...
try:
    from scripts.lark_sheets_cli import LarkSheetsCLI, LarkSheetsError, SheetInfo, _col_num_to_a1
except Exception:  # pragma: no cover
    from lark_sheets_cli import LarkSheetsCLI, LarkSheetsError, SheetInfo, _col_num_to_a1


def _workspace_root() -> Path:
    env = os.environ.get("IRIS_WORKSPACE_PATH")
    return Path(env).resolve() if env else Path.cwd().resolve()


def _run_cmd(cmd: List[str], timeout: int = 60) -> str:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed (code={p.returncode}): {' '.join(cmd)}\n{p.stdout}")
    return p.stdout


def bytedcli_auth(*, strict: bool = True) -> bool:
    """执行 bytedcli-auth。

    - strict=True：鉴权失败直接抛错（适用于写入链路）
    - strict=False：失败返回 False（适用于 best-effort 场景）
    """

    root = _workspace_root()
    script = root / "inner_skills" / "bytedcli-auth" / "scripts" / "bytedcli_auth.sh"
    if not script.exists():
        if strict:
            raise RuntimeError(f"bytedcli-auth script not found: {script}")
        return False

    try:
        _run_cmd(["bash", str(script)], timeout=60)
        return True
    except Exception:
        if strict:
            raise
        return False


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _compact_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _safe_get(d: Dict[str, Any], path: Sequence[str]) -> Optional[Any]:
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _extract_message_snapshot(event: Dict[str, Any]) -> str:
    """尽量从事件中取“最像原始群消息”的字段。"""

    # 1) chat_task 结构里有 source_text_full
    v = _safe_get(event, ["task", "source_text_full"])
    if v:
        return str(v)

    # 2) heartbeat-inspector 的 message_new 通常有 text
    if event.get("text"):
        return str(event.get("text"))

    # 3) 兜底：整行 JSON
    return _compact_json(event)


def _normalize_person(value: Any) -> str:
    """把 @人/富文本/普通字符串归一成人类可读的名字。"""

    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, dict):
        # 常见：@人 mention block
        for k in ("name", "text", "en_name", "zh_name"):
            v = value.get(k)
            if v is None:
                continue
            s = str(v).strip()
            if not s:
                continue
            if k == "text" and s.startswith("@"):  # e.g. "@张三"
                s = s[1:].strip()
            return s
        return _compact_json(value)

    return str(value).strip()


def _normalize_person_list(values: Any) -> str:
    if values is None:
        return ""
    if isinstance(values, list):
        parts = [_normalize_person(x) for x in values]
        parts = [p for p in parts if p]
        return "、".join(parts)
    return _normalize_person(values)


def _find_updated_range(resp: Dict[str, Any]) -> Optional[str]:
    """Best-effort: 从 append 返回中尝试解析“本次更新的 A1 range”。

    注意：lark-sheets-cli 不同版本的返回 schema 可能不同，因此这里做多路径兼容。
    """

    candidates: List[List[str]] = [
        ["data", "updates", "updatedRange"],
        ["data", "updates", "updated_range"],
        ["data", "updates", "updatedData", "range"],
        ["data", "updates", "updated_data", "range"],
        ["data", "updatedRange"],
        ["data", "updated_range"],
        ["data", "range"],
        ["data", "tableRange"],
    ]

    def pick(obj: Any, path: List[str]) -> Optional[str]:
        cur = obj
        for k in path:
            if not isinstance(cur, dict) or k not in cur:
                return None
            cur = cur[k]
        if isinstance(cur, str) and cur.strip():
            return cur.strip()
        return None

    for p in candidates:
        r = pick(resp, p)
        if r:
            return r
    return None


def _normalize_cells(values: List[List[Any]]) -> List[List[str]]:
    out: List[List[str]] = []
    for row in values:
        rr: List[str] = []
        for c in row:
            if c is None:
                rr.append("")
            else:
                rr.append(str(c))
        out.append(rr)
    return out


@dataclass
class DualWriteResult:
    batch_id: str
    written_log_rows: int
    written_task_rows: int
    raw_verified: bool
    raw_verify_skipped_reason: Optional[str] = None


class DualTrackWriter:
    """把 heartbeat-inspector 输出的 JSON 事件做“双轨写入”。

    轨道 A：全量审计日志写入【Aime日志】（含原始快照 + 提取 JSON + 批次号）
    轨道 B：仅 task 类事件写入【任务库】

    约束：
    - 不假设表头结构：运行时读 header 并做列对齐
    - 写入以 append 为主（避免误改动既有行）
    """

    def __init__(
        self,
        *,
        spreadsheet_token: str,
        log_sheet_title: str = "Aime日志",
        task_sheet_title: str = "任务库",
        cli: Optional[LarkSheetsCLI] = None,
    ):
        self.spreadsheet_token = spreadsheet_token
        self.log_sheet_title = log_sheet_title
        self.task_sheet_title = task_sheet_title
        self.cli = cli or LarkSheetsCLI()

        self.log_sheet: SheetInfo = self.cli.get_sheet_id(spreadsheet_token, log_sheet_title)
        self.task_sheet: SheetInfo = self.cli.get_sheet_id(spreadsheet_token, task_sheet_title)

    def _build_log_kv(self, event: Dict[str, Any], batch_id: str, write_time: str) -> Dict[str, Any]:
        event_type = event.get("type")
        owners = _safe_get(event, ["task", "owners"])
        owners_text = _normalize_person_list(owners)

        task_name = _safe_get(event, ["task", "task_name"]) or ""
        due_time = (
            _safe_get(event, ["task", "due_time"])
            or _safe_get(event, ["status_update", "postponed_to_time"])
            or ""
        )

        return {
            # 兼容当前表头（A~F）
            "交付结果": task_name or (event_type or ""),
            "完成情况": "",
            "分类": event_type or "",
            "负责人": owners_text,
            "DDL": due_time,
            "进展": _extract_message_snapshot(event),
            # 新增审计字段（G~K）
            "写入时间": write_time,
            "消息来源": f"heartbeat-inspector:{event_type}",
            "原始群消息快照": _extract_message_snapshot(event),
            "大模型提取 JSON": _compact_json(event),
            "批次号": batch_id,
        }

    def _build_task_kv(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if event.get("type") != "chat_task":
            return None

        task = event.get("task") or {}
        task_name = task.get("task_name")
        owners = task.get("owners")
        due_time = task.get("due_time") or task.get("ddl") or ""
        ack_tag = _safe_get(task, ["ack_lock", "tag"]) or task.get("status") or ""

        owners_text = _normalize_person_list(owners)

        return {
            "交付结果": task_name or "",
            "完成情况": ack_tag,
            "分类": "群聊任务抽取",
            "负责人": owners_text,
            "DDL": due_time or "",
            "进展": task.get("source_text_full") or event.get("text") or "",
        }

    def _append_and_verify(
        self,
        *,
        spreadsheet_token: str,
        append_range: str,
        chunk: List[List[Any]],
        enable_raw_verify: bool,
    ) -> tuple[bool, Optional[str]]:
        resp = self.cli.append_rows(spreadsheet_token, append_range, chunk)

        if not enable_raw_verify:
            return False, "raw_verify_disabled"

        updated_range = _find_updated_range(resp)
        if not updated_range:
            return False, "append_response_missing_updated_range"

        # RAW 原子锁：写→等→读
        time.sleep(2)
        values = self.cli.read_range(spreadsheet_token, updated_range)

        got = _normalize_cells(values)
        want = _normalize_cells(chunk)
        if len(got) < len(want):
            raise LarkSheetsError(
                "RAW 校验失败：读回行数小于写入行数\n"
                f"updated_range={updated_range}\n"
                f"want_rows={len(want)} got_rows={len(got)}\n"
                f"resp={json.dumps(resp, ensure_ascii=False)[:2000]}"
            )

        tail = got[-len(want) :]
        if tail != want:
            raise LarkSheetsError(
                "RAW 校验失败：读回内容与写入内容不一致\n"
                f"updated_range={updated_range}\n"
                f"want_tail={json.dumps(want, ensure_ascii=False)[:2000]}\n"
                f"got_tail={json.dumps(tail, ensure_ascii=False)[:2000]}\n"
                f"resp={json.dumps(resp, ensure_ascii=False)[:2000]}"
            )

        return True, None

    def write_events(
        self,
        events: Iterable[Dict[str, Any]],
        *,
        batch_id: Optional[str] = None,
        write_time: Optional[str] = None,
        chunk_size: int = 50,
        dry_run: bool = False,
        raw_verify: bool = True,
    ) -> DualWriteResult:
        batch_id = batch_id or f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        write_time = write_time or _now_iso()

        # 读表头并缓存
        log_header = self.cli.read_header(self.spreadsheet_token, self.log_sheet)
        task_header = self.cli.read_header(self.spreadsheet_token, self.task_sheet)

        # +append 的 range 必须覆盖 values 的列宽；否则会报 90202 (columns of value > range)
        log_col_count = max(1, len(log_header))
        task_col_count = max(1, len(task_header))
        log_append_range = f"{self.log_sheet.sheet_id}!A1:{_col_num_to_a1(log_col_count)}1"
        task_append_range = f"{self.task_sheet.sheet_id}!A1:{_col_num_to_a1(task_col_count)}1"

        log_rows: List[List[Any]] = []
        task_rows: List[List[Any]] = []

        for ev in events:
            if not isinstance(ev, dict):
                continue

            log_kv = self._build_log_kv(ev, batch_id=batch_id, write_time=write_time)
            log_rows.append(self.cli.make_row_by_header(log_header, log_kv))

            task_kv = self._build_task_kv(ev)
            if task_kv:
                task_rows.append(self.cli.make_row_by_header(task_header, task_kv))

        if dry_run:
            return DualWriteResult(
                batch_id=batch_id,
                written_log_rows=len(log_rows),
                written_task_rows=len(task_rows),
                raw_verified=False,
                raw_verify_skipped_reason="dry_run",
            )

        written_log = 0
        written_task = 0
        verified_any = False
        skipped_reason: Optional[str] = None

        # 分块追加，避免单次过大
        for i in range(0, len(log_rows), chunk_size):
            chunk = log_rows[i : i + chunk_size]
            if not chunk:
                continue
            ok, reason = self._append_and_verify(
                spreadsheet_token=self.spreadsheet_token,
                append_range=log_append_range,
                chunk=chunk,
                enable_raw_verify=raw_verify,
            )
            verified_any = verified_any or ok
            skipped_reason = skipped_reason or reason
            written_log += len(chunk)

        for i in range(0, len(task_rows), chunk_size):
            chunk = task_rows[i : i + chunk_size]
            if not chunk:
                continue
            ok, reason = self._append_and_verify(
                spreadsheet_token=self.spreadsheet_token,
                append_range=task_append_range,
                chunk=chunk,
                enable_raw_verify=raw_verify,
            )
            verified_any = verified_any or ok
            skipped_reason = skipped_reason or reason
            written_task += len(chunk)

        return DualWriteResult(
            batch_id=batch_id,
            written_log_rows=written_log,
            written_task_rows=written_task,
            raw_verified=verified_any,
            raw_verify_skipped_reason=None if verified_any else skipped_reason,
        )


def _iter_events_from_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    if path == "-":
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)
        return

    p = Path(path)
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        yield json.loads(line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--spreadsheet",
        required=True,
        help="电子表格 URL 或 token（支持 wiki URL / sheets URL / spreadsheet_token）",
    )
    ap.add_argument("--log-sheet-title", default="Aime日志")
    ap.add_argument("--task-sheet-title", default="任务库")
    ap.add_argument(
        "--input-jsonl",
        required=True,
        help="heartbeat-inspector 输出的 JSONL 文件路径；用 - 表示 stdin",
    )
    ap.add_argument("--batch-id", default=None, help="可选：指定批次号（不传则自动生成）")
    ap.add_argument("--dry-run", action="store_true", help="只计算将写入多少行，不实际写表")
    ap.add_argument(
        "--no-raw-verify",
        action="store_true",
        help="禁用 RAW 写后即读校验（默认开启；仅在确认底层 CLI 无法返回 updatedRange 时使用）",
    )
    args = ap.parse_args()

    # 写入链路：默认 strict，鉴权失败直接熔断
    bytedcli_auth(strict=True)

    cli = LarkSheetsCLI()
    spreadsheet_token = cli.resolve_spreadsheet_token(args.spreadsheet)

    writer = DualTrackWriter(
        spreadsheet_token=spreadsheet_token,
        log_sheet_title=args.log_sheet_title,
        task_sheet_title=args.task_sheet_title,
        cli=cli,
    )

    events = list(_iter_events_from_jsonl(args.input_jsonl))
    result = writer.write_events(
        events,
        batch_id=args.batch_id,
        dry_run=args.dry_run,
        raw_verify=not bool(args.no_raw_verify),
    )

    try:
        print(
            json.dumps(
                {
                    "ok": True,
                    "batch_id": result.batch_id,
                    "written_log_rows": result.written_log_rows,
                    "written_task_rows": result.written_task_rows,
                    "dry_run": bool(args.dry_run),
                    "raw_verified": result.raw_verified,
                    "raw_verify_skipped_reason": result.raw_verify_skipped_reason,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
