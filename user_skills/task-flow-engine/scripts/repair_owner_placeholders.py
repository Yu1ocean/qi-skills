#!/usr/bin/env python3
"""修复任务库里误填为邮箱占位符的负责人字段。

能力：
1. 读取同一份表格中的【团队名单】构建“中文名 + 邮箱别名”目录。
2. 对指定行的负责人字段做邮箱反查，自愈为中文名。
3. 可选清理标题末尾误残留的日期小尾巴。
4. 写后即读，输出 RAW 回捞结果，便于零信任核对。
"""

import argparse
import json
import re
from typing import Any, Dict, List, Optional, Sequence

from task_flow_engine.lark_sheets_cli import LarkSheetsCLI
from task_flow_engine.patrol import (
    _normalize_person_key,
    _normalize_text,
    build_owner_directory_from_roster_rows,
    split_people,
)


TASK_SHEET_URL = "https://bytedance.sg.larkoffice.com/sheets/TnNYsLq9phIJwutJGwBl730ygjd"


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


def _canonicalize_owner_text(raw_value: Any, owner_directory: Dict[str, Any]) -> Optional[str]:
    owner_text = _normalize_text(raw_value)
    people = split_people(owner_text)
    if not people:
        return None

    resolved: List[str] = []
    for person in people:
        hit = owner_directory.get(_normalize_person_key(person))
        resolved.append(hit.display_name if hit else person)
    return "、".join(resolved)


def _strip_trailing_date_suffix(title: str) -> str:
    s = (title or "").strip()
    if not s:
        return s
    s = re.sub(r"\s*\d{4}-\d{2}-\d{2}(?=】$)", "", s)
    s = re.sub(r"\s*\d{4}/\d{2}/\d{2}(?=】$)", "", s)
    return s.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spreadsheet", default=TASK_SHEET_URL)
    ap.add_argument("--task-sheet-title", default="任务库")
    ap.add_argument("--roster-sheet-title", default="团队名单")
    ap.add_argument("--rows", nargs="+", type=int, required=True, help="要修复的任务库行号，例如：28 29")
    ap.add_argument("--strip-title-date-tail", action="store_true", help="清理标题末尾残留日期尾巴")
    args = ap.parse_args()

    cli = LarkSheetsCLI()
    spreadsheet_token = cli.resolve_spreadsheet_token(args.spreadsheet)

    task_sheet = cli.get_sheet_id(spreadsheet_token, args.task_sheet_title)
    roster_sheet = cli.get_sheet_id(spreadsheet_token, args.roster_sheet_title)

    task_values = cli.read_range(spreadsheet_token, task_sheet.sheet_id)
    task_rows = {row["__row_number"]: row for row in _values_to_rows(task_values)}

    roster_values = cli.read_range(spreadsheet_token, roster_sheet.sheet_id)
    roster_rows = _values_to_rows(roster_values)
    owner_directory, _ = build_owner_directory_from_roster_rows(roster_rows)

    read_back: Dict[int, Dict[str, Any]] = {}
    changes: List[Dict[str, Any]] = []

    for row_no in args.rows:
        row = task_rows.get(row_no)
        if row is None:
            raise ValueError(f"任务库不存在第 {row_no} 行")

        owner_before = _normalize_text(row.get("负责人")) or ""
        owner_after = _canonicalize_owner_text(row.get("负责人"), owner_directory) or owner_before

        title_before = _normalize_text(row.get("交付结果")) or ""
        title_after = _strip_trailing_date_suffix(title_before) if args.strip_title_date_tail else title_before

        if owner_after != owner_before:
            cli.write_range(spreadsheet_token, f"{task_sheet.sheet_id}!D{row_no}:D{row_no}", [[owner_after]])
        if title_after != title_before:
            cli.write_range(spreadsheet_token, f"{task_sheet.sheet_id}!A{row_no}:A{row_no}", [[title_after]])

        read_values = cli.read_range(spreadsheet_token, f"{task_sheet.sheet_id}!A{row_no}:F{row_no}")
        read_back[row_no] = {
            "range": f"A{row_no}:F{row_no}",
            "values": read_values,
        }
        changes.append(
            {
                "row": row_no,
                "title_before": title_before,
                "title_after": title_after,
                "owner_before": owner_before,
                "owner_after": owner_after,
            }
        )

    print(
        json.dumps(
            {
                "spreadsheet_token": spreadsheet_token,
                "task_sheet_id": task_sheet.sheet_id,
                "roster_sheet_id": roster_sheet.sheet_id,
                "changes": changes,
                "read_back": read_back,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
