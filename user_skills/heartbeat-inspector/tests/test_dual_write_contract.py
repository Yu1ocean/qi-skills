#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest
from pathlib import Path
from typing import Any, Dict, List

from scripts.dual_write import DualTrackWriter, _canonicalize_cell, _collect_chat_task_contract_violations
from scripts.lark_sheets_cli import LarkSheetsCLI, SheetInfo


class DummyCLI(LarkSheetsCLI):
    def __init__(self) -> None:  # type: ignore[override]
        self._sheets: Dict[str, SheetInfo] = {}
        self._title_to_id: Dict[str, str] = {}
        self._values: Dict[tuple[str, str], List[List[Any]]] = {}
        self.append_calls: List[Dict[str, Any]] = []

    def add_sheet(self, spreadsheet_token: str, sheet_id: str, title: str, values: List[List[Any]]) -> None:
        info = SheetInfo(sheet_id=sheet_id, title=title, row_count=len(values), column_count=len(values[0]) if values else 0)
        self._sheets[sheet_id] = info
        self._title_to_id[title] = sheet_id
        self._values[(spreadsheet_token, sheet_id)] = [list(row) for row in values]

    def _auto_find_cli(self) -> Path:  # type: ignore[override]
        return Path("/dev/null")

    def info(self, spreadsheet_token: str):  # type: ignore[override]
        return list(self._sheets.values())

    def get_sheet_id(self, spreadsheet_token: str, sheet_title: str) -> SheetInfo:  # type: ignore[override]
        sid = self._title_to_id.get(sheet_title)
        if not sid:
            raise RuntimeError(f"sheet not found: {sheet_title}")
        return self._sheets[sid]

    def read_range(self, spreadsheet_token: str, a1_range: str):  # type: ignore[override]
        sheet_id = a1_range.split("!", 1)[0]
        return self._values.get((spreadsheet_token, sheet_id), [])

    def append_rows(self, spreadsheet_token: str, a1_range: str, rows: List[List[Any]]):  # type: ignore[override]
        sheet_id = a1_range.split("!", 1)[0]
        key = (spreadsheet_token, sheet_id)
        self._values.setdefault(key, []).extend([list(r) for r in rows])
        self.append_calls.append({"token": spreadsheet_token, "range": a1_range, "rows": rows})
        return {"ok": True, "data": {"updates": {"updatedRange": a1_range}}}


class TestDualWriteContract(unittest.TestCase):
    def test_canonicalize_cell_flattens_auto_link_rich_text(self):
        value = [
            {"type": "text", "text": "prefix "},
            {"type": "url", "text": "https://example.com", "link": "https://example.com"},
            {"type": "text", "text": " suffix"},
        ]
        self.assertEqual(_canonicalize_cell(value), "prefix https://example.com suffix")

    def _make_writer(self) -> tuple[DualTrackWriter, DummyCLI]:
        cli = DummyCLI()
        spreadsheet_token = "sht_contract"
        cli.add_sheet(spreadsheet_token, "log_sheet", "Aime日志", [["交付结果", "完成情况", "分类", "负责人", "DDL", "进展"]])
        cli.add_sheet(spreadsheet_token, "task_sheet", "任务库", [["交付结果", "完成情况", "分类", "负责人", "DDL", "进展"]])
        cli.add_sheet(spreadsheet_token, "roster_sheet", "团队名单", [["中文名称", "邮箱", "Open ID"]])
        return (
            DualTrackWriter(
                spreadsheet_token=spreadsheet_token,
                log_sheet_title="Aime日志",
                task_sheet_title="任务库",
                roster_sheet_title="团队名单",
                cli=cli,
            ),
            cli,
        )

    def test_collect_chat_task_contract_violations_flags_suggestion_reply(self):
        event = {
            "type": "chat_task",
            "task": {
                "task_name": "整理方案",
                "suggestion_reply": "请补充负责人和DDL",
                "source_text_full": "大家帮我整理方案",
            },
        }
        violations = _collect_chat_task_contract_violations(event)
        self.assertIn("task_name_missing_or_not_bracketed", violations)
        self.assertIn("suggestion_reply_present", violations)

    def test_invalid_chat_task_is_logged_but_not_written_to_task_sheet(self):
        writer, cli = self._make_writer()
        invalid_event = {
            "type": "chat_task",
            "task": {
                "task_name": "整理方案",
                "owners": ["张三"],
                "suggestion_reply": "请补充明确DDL后再入库",
                "source_text_full": "@张三 整理方案，下周给我",
            },
            "text": "@张三 整理方案，下周给我",
        }

        result = writer.write_events([invalid_event], batch_id="B_CONTRACT", dry_run=True, raw_verify=False)

        self.assertEqual(result.written_log_rows, 1)
        self.assertEqual(result.written_task_rows, 0)
        self.assertEqual(len(result.taskflow_ack_records), 0)
        self.assertEqual(len(result.invalid_task_events), 1)
        self.assertIn("suggestion_reply_present", result.invalid_task_events[0]["violations"])
        self.assertIn("task_name_missing_or_not_bracketed", result.invalid_task_events[0]["violations"])
        self.assertEqual(len(cli.append_calls), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
