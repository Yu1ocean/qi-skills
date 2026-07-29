#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

from scripts.dual_write import DualTrackWriter, OwnerIdentity
from scripts.lark_sheets_cli import LarkSheetsCLI, SheetInfo


class DummyCLI(LarkSheetsCLI):
    """A minimal in-memory fake of LarkSheetsCLI for dual_write tests.

    We only implement the methods that DualTrackWriter.write_events uses:
    - get_sheet_id
    - read_header
    - read_range
    - append_rows
    - make_row_by_header
    """

    def __init__(self) -> None:  # type: ignore[override]
        # sheet_id -> SheetInfo
        self._sheets: Dict[str, SheetInfo] = {}
        # title -> sheet_id
        self._title_to_id: Dict[str, str] = {}
        # (token, sheet_id) -> rows (including header)
        self._values: Dict[tuple[str, str], List[List[Any]]] = {}
        # capture last append payloads
        self.append_calls: List[Dict[str, Any]] = []

    # --- helpers to setup sheets ---

    def add_sheet(self, spreadsheet_token: str, sheet_id: str, title: str, values: List[List[Any]]) -> None:
        info = SheetInfo(sheet_id=sheet_id, title=title, row_count=len(values), column_count=len(values[0]) if values else 0)
        self._sheets[sheet_id] = info
        self._title_to_id[title] = sheet_id
        self._values[(spreadsheet_token, sheet_id)] = [list(row) for row in values]

    # --- LarkSheetsCLI overrides ---

    def _auto_find_cli(self) -> Path:  # type: ignore[override]
        # not used in tests
        return Path("/dev/null")

    def info(self, spreadsheet_token: str):  # type: ignore[override]
        return list(self._sheets.values())

    def get_sheet_id(self, spreadsheet_token: str, sheet_title: str) -> SheetInfo:  # type: ignore[override]
        sid = self._title_to_id.get(sheet_title)
        if not sid:
            raise RuntimeError(f"sheet not found: {sheet_title}")
        return self._sheets[sid]

    def read_range(self, spreadsheet_token: str, a1_range: str):  # type: ignore[override]
        # very small A1 parser: "sheet_id!A1:C3" or just "sheet_id"
        if "!" in a1_range:
            sheet_id, _ = a1_range.split("!", 1)
        else:
            sheet_id = a1_range
        return self._values.get((spreadsheet_token, sheet_id), [])

    def append_rows(self, spreadsheet_token: str, a1_range: str, rows: List[List[Any]]):  # type: ignore[override]
        if "!" in a1_range:
            sheet_id, _ = a1_range.split("!", 1)
        else:
            sheet_id = a1_range
        key = (spreadsheet_token, sheet_id)
        existing = self._values.setdefault(key, [])
        existing.extend([list(r) for r in rows])
        self.append_calls.append({"token": spreadsheet_token, "range": a1_range, "rows": rows})
        # mimic lark-sheets-cli response with updatedRange
        return {"ok": True, "data": {"updates": {"updatedRange": a1_range}}}


class TestDualWriteDynamicRoster(unittest.TestCase):
    def _make_writer(self) -> tuple[DualTrackWriter, DummyCLI]:
        cli = DummyCLI()
        spreadsheet_token = "sht_test"

        # Aime日志: minimal header
        cli.add_sheet(
            spreadsheet_token,
            sheet_id="log_sheet",
            title="Aime日志",
            values=[["交付结果", "负责人", "进展"]],
        )

        # 任务库: header with 负责人
        cli.add_sheet(
            spreadsheet_token,
            sheet_id="task_sheet",
            title="任务库",
            values=[["交付结果", "负责人", "DDL", "进展"]],
        )

        # 团队名单: start with header only, empty body
        cli.add_sheet(
            spreadsheet_token,
            sheet_id="roster_sheet",
            title="团队名单",
            values=[["中文名称", "英文名/花名", "邮箱", "Open ID"]],
        )

        writer = DualTrackWriter(
            spreadsheet_token=spreadsheet_token,
            log_sheet_title="Aime日志",
            task_sheet_title="任务库",
            roster_sheet_title="团队名单",
            cli=cli,
        )
        return writer, cli

    def test_owner_not_in_roster_and_no_chat_match_falls_back_to_plain_text(self):
        writer, cli = self._make_writer()

        event = {
            "type": "chat_task",
            "chat_id": "oc_dummy",
            "task": {
                "task_name": "【测试任务】",
                "owners": ["新同学"],
                "due_time": None,
                "source_text_full": "@新同学 【测试任务】",
            },
        }

        with patch.object(writer, "_lookup_owner_identity_via_chat_members", return_value=None):
            result = writer.write_events([event], batch_id="B1", dry_run=False, raw_verify=False)

        self.assertEqual(result.written_task_rows, 1)
        self.assertEqual(len(result.taskflow_ack_records), 1)
        self.assertIn("已录入任务台账：", result.taskflow_ack_records[0]["rendered_text"])
        # roster should still only contain header row
        roster_values = cli._values[("sht_test", "roster_sheet")]
        self.assertEqual(len(roster_values), 1)
        # task row should contain plain text owner
        task_values = cli._values[("sht_test", "task_sheet")]
        self.assertEqual(len(task_values), 2)
        self.assertEqual(task_values[1][1], "新同学")

    def test_owner_not_in_roster_but_chat_match_triggers_roster_append_and_mention(self):
        writer, cli = self._make_writer()

        event = {
            "type": "chat_task",
            "chat_id": "oc_group_1",
            "task": {
                "task_name": "【测试任务】",
                "owners": ["新同学"],
                "due_time": None,
                "source_text_full": "@新同学 【测试任务】",
            },
        }

        identity = OwnerIdentity(
            raw="新同学",
            display_name="新同学",
            alias_name="新同学",
            open_id="ou_xxx",
            email="new.user@bytedance.com",
            source="chat_member:oc_group_1",
        )

        with patch.object(writer, "_lookup_owner_identity_via_chat_members", return_value=identity):
            result = writer.write_events([event], batch_id="B2", dry_run=False, raw_verify=False)

        self.assertEqual(result.written_task_rows, 1)
        self.assertEqual(len(result.taskflow_ack_records), 1)
        self.assertIn("【测试任务】", result.taskflow_ack_records[0]["rendered_text"])
        # roster sheet should now have one appended row
        roster_values = cli._values[("sht_test", "roster_sheet")]
        self.assertEqual(len(roster_values), 2)
        self.assertIn("新同学", roster_values[1])
        self.assertIn("new.user@bytedance.com", roster_values[1])
        # task row should contain a mention dict or list instead of plain text
        task_values = cli._values[("sht_test", "task_sheet")]
        self.assertEqual(len(task_values), 2)
        owners_cell = task_values[1][1]
        if isinstance(owners_cell, list):
            cell_items = owners_cell
        else:
            cell_items = [owners_cell]
        self.assertTrue(any(isinstance(v, dict) and v.get("type") == "mention" for v in cell_items))
        self.assertFalse(any(isinstance(v, str) and "<EMAIL_" in v for v in cell_items))
        self.assertEqual(roster_values[1][1], "新同学")

    def test_chat_member_name_empty_falls_back_to_zh_name_for_alias(self):
        writer, _ = self._make_writer()

        payload = {
            "users": [
                {
                    "name": "",
                    "zh_name": "Cherry Gao",
                    "open_id": "ou_cherry",
                    "email": "gaochuan.cherry@bytedance.com",
                }
            ]
        }

        with patch("scripts.dual_write._run_cmd", return_value=json.dumps(payload, ensure_ascii=False)):
            identity = writer._lookup_owner_identity_via_chat_members("Cherry Gao", chat_id="oc_group_1")

        self.assertIsNotNone(identity)
        assert identity is not None
        self.assertEqual(identity.display_name, "Cherry Gao")
        self.assertEqual(identity.alias_name, "Cherry Gao")
        self.assertEqual(identity.open_id, "ou_cherry")
        self.assertEqual(identity.email, "gaochuan.cherry@bytedance.com")


if __name__ == "__main__":
    unittest.main(verbosity=2)
