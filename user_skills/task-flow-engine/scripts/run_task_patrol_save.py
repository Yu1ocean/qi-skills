#!/usr/bin/env python3
"""Helper: run task_patrol and save full JSON output to a file.

Why this helper exists:
- The runtime stdout in Aime sandbox can be truncated for large JSON.
- This script writes the full alert dictionary to disk for inspection.

It intentionally mirrors `scripts/task_patrol.py` logic and does NOT send any IM.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional
import subprocess

from task_flow_engine.lark_sheets_cli import LarkSheetsCLI
from task_flow_engine.patrol import (
    OwnerIdentity,
    PatrolStateStore,
    TaskPatrol,
    _normalize_person_key,
    build_owner_directory_from_roster_rows,
)
from task_flow_engine.vacation import (
    FeishuVacationClient,
    apply_vacation_guard,
    is_legal_rest_day,
)


def _values_to_rows(values: List[List[Any]]) -> List[Dict[str, Any]]:
    if not values:
        return []

    header = values[0]
    header_keys: List[Optional[str]] = []
    for h in header:
        if h is None:
            header_keys.append(None)
        else:
            s = str(h).strip()
            header_keys.append(s or None)

    rows: List[Dict[str, Any]] = []
    for i, row in enumerate(values[1:], start=2):
        d: Dict[str, Any] = {"__row_number": i}
        for j, key in enumerate(header_keys):
            if not key:
                continue
            d[key] = row[j] if j < len(row) else None
        rows.append(d)
    return rows


def _repo_root() -> Path:
    # user_skills/task-flow-engine/scripts/run_task_patrol_save.py
    return Path(__file__).resolve().parents[1]


# -----------------------------
# L3 断言层：副作用前的输入校验（避免误写/误读/路径穿透）
# -----------------------------


def validate_spreadsheet(value: str) -> str:
    v = (value or "").strip()
    if not v:
        raise ValueError("spreadsheet 不能为空")
    return v


def validate_safe_path_under_repo(path: Path, *, repo_root: Path, arg_name: str) -> Path:
    repo_root = repo_root.resolve()
    resolved = path.resolve()
    if not str(resolved).startswith(str(repo_root) + str(Path.sep)) and resolved != repo_root:
        raise ValueError(f"{arg_name} 必须位于任务目录内：{resolved} (repo_root={repo_root})")
    return resolved


def _validate_target_chat_id(target_chat: str) -> Dict[str, Any]:
    target_chat = (target_chat or "").strip()
    if not target_chat:
        raise ValueError("target_chat 不能为空")
    if not target_chat.startswith("oc_"):
        raise ValueError("target_chat 必须是 chat_id（oc_xxx）")
    return {"chat_id": target_chat, "name": ""}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spreadsheet", required=True)
    ap.add_argument("--task-sheet-title", default="任务库")
    ap.add_argument("--roster-sheet-title", default="团队联系方式")
    ap.add_argument("--due-soon-days", type=int, default=2)
    ap.add_argument("--today", default=None)
    ap.add_argument("--target-chat", default=None)
    ap.add_argument("--state-file", default=".patrol_state.json")
    ap.add_argument("--no-state", action="store_true")
    ap.add_argument(
        "--disable-legal-holiday-guard",
        action="store_true",
        help="禁用法定休息日静默顺延（默认开启）",
    )
    ap.add_argument(
        "--disable-personal-leave-guard",
        action="store_true",
        help="禁用个人休假静默顺延（默认开启，fail-open）",
    )
    ap.add_argument(
        "--leave-check-min-busy-hours",
        type=float,
        default=4.0,
        help="freebusy 命中个人请假的最小忙碌时长阈值（小时，默认 4.0）",
    )
    ap.add_argument("--output", default="alerts.json")

    args = ap.parse_args()

    repo_root = _repo_root()

    # L3：副作用前的输入校验
    args.spreadsheet = validate_spreadsheet(args.spreadsheet)

    # state/output 都可能触发本地写入：路径必须限制在 repo_root 下
    state_path: Optional[Path] = None
    if not args.no_state:
        p = Path(args.state_file)
        if not p.is_absolute():
            p = repo_root / p
        state_path = validate_safe_path_under_repo(p, repo_root=repo_root, arg_name="state-file")

    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = repo_root / out_path
    out_path = validate_safe_path_under_repo(out_path, repo_root=repo_root, arg_name="output")

    today = date.today() if not args.today else date.fromisoformat(args.today)

    cli = LarkSheetsCLI()
    spreadsheet_token = cli.resolve_spreadsheet_token(args.spreadsheet)

    task_sheet = cli.get_sheet_id(spreadsheet_token, args.task_sheet_title)
    task_values = cli.read_range(spreadsheet_token, task_sheet.sheet_id)
    task_rows = _values_to_rows(task_values)

    roster_sheet = cli.get_sheet_id(spreadsheet_token, args.roster_sheet_title)
    roster_values = cli.read_range(spreadsheet_token, roster_sheet.sheet_id)
    roster_rows = _values_to_rows(roster_values)
    owner_directory, roster_duplicates = build_owner_directory_from_roster_rows(roster_rows)

    def resolve_owner(raw: str) -> OwnerIdentity:
        k = _normalize_person_key(raw)
        hit = owner_directory.get(k)
        if hit is None:
            return OwnerIdentity(raw=raw, display_name=raw, source="sheet")
        return OwnerIdentity(
            raw=raw,
            display_name=hit.display_name,
            open_id=hit.open_id,
            email=hit.email,
            source=hit.source,
        )

    target_chat: Optional[Dict[str, Any]] = None
    if args.target_chat:
        target_chat = _validate_target_chat_id(args.target_chat)

    state: Optional[PatrolStateStore] = None
    if state_path is not None:
        state = PatrolStateStore(state_path)
        state.load()

    patrol = TaskPatrol(due_soon_days=args.due_soon_days, owner_resolver=resolve_owner)
    output = patrol.run(task_rows, today=today, state=state, target_chat=target_chat)

    # 6.1) 休假免打扰与顺延拦截器（法定节假日 + 个人休假）
    holiday_hit = False if args.disable_legal_holiday_guard else is_legal_rest_day(today)
    if args.disable_personal_leave_guard:
        owner_on_leave_checker = None
    else:
        vacation_client = FeishuVacationClient()

        def owner_on_leave_checker(owner: OwnerIdentity) -> bool:
            return vacation_client.is_user_on_leave_by_freebusy(
                owner=owner,
                today=today,
                min_busy_hours=args.leave_check_min_busy_hours,
            )

    output = apply_vacation_guard(
        output,
        today=today,
        is_holiday=holiday_hit,
        owner_on_leave_checker=owner_on_leave_checker,
    )

    if state is not None:
        state.save()
        output["state"] = {"path": str(state.path), "enabled": True}
    else:
        output["state"] = {"enabled": False}

    output["source"] = {
        "spreadsheet_token": spreadsheet_token,
        "task_sheet": {
            "title": task_sheet.title,
            "sheet_id": task_sheet.sheet_id,
            "total_rows_read": len(task_rows),
        },
        "roster_sheet": {
            "title": roster_sheet.title,
            "sheet_id": roster_sheet.sheet_id,
            "total_rows_read": len(roster_rows),
        },
    }
    output["directory"] = {
        "target_chat": target_chat,
        "mapped_members": len(owner_directory),
        "roster_duplicates": roster_duplicates,
    }

    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    # print a small non-truncated summary for logs
    summary = output.get("summary", {})
    routes = output.get("routes", {})
    brief = {
        "ok": True,
        "alerts_path": str(out_path),
        "summary": summary,
        "route_counts": {
            "private_buckets": len((routes.get("private") or {})),
            "private_items": summary.get("private_count"),
            "group_items": summary.get("group_count"),
            "unmapped_items": (routes.get("unmapped") or {}).get("count"),
        },
        "directory": output.get("directory", {}),
        "source": output.get("source", {}),
    }
    print(json.dumps(brief, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
