import sys
import unittest
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from task_flow_engine.vacation import apply_vacation_guard


class TestVacationGuard(unittest.TestCase):
    def _owner(self, *, name: str, email: str, open_id: str) -> dict:
        return {
            "raw": name,
            "display_name": name,
            "open_id": open_id,
            "email": email,
            "source": "sheet_roster",
        }

    def _item(self, *, key: str, task: str, owner: dict, stage: str = "private") -> dict:
        return {
            "key": key,
            "row": 2,
            "task": task,
            "status": None,
            "owners": [owner],
            "ddl_raw": None,
            "ddl_parsed": None,
            "delta_days": None,
            "alert_category": "缺失 DDL",
            "reason": "DDL为空",
            "issue_type": "missing_ddl",
            "overdue_days": None,
            "abnormal_days": 2,
            "stage": stage,
        }

    def test_holiday_guard_clears_delivery_routes(self):
        owner = self._owner(name="张三", email="zhangsan@bytedance.com", open_id="ou_1")
        item = self._item(key="r2:任务A", task="任务A", owner=owner)
        output = {
            "summary": {"today": "2026-05-01", "private_count": 1, "group_count": 1},
            "grouped_results": {"缺失 DDL": [item]},
            "routes": {
                "private": {
                    owner["email"]: {
                        "owner": owner,
                        "count": 1,
                        "items": [item],
                        "message": "private-msg",
                        "card": {"name": "AimeCard"},
                        "mentions_open_ids": [],
                    }
                },
                "group": {
                    "target_chat": {"chat_id": "oc_xxx", "name": ""},
                    "count": 1,
                    "items": [dict(item, stage="group")],
                    "mentions_open_ids": [owner["open_id"]],
                    "message": "group-msg",
                    "card": {"name": "AimeCard"},
                },
                "unmapped": {"count": 1, "items": [{"key": "u1"}]},
            },
        }

        result = apply_vacation_guard(
            output,
            today=date.fromisoformat("2026-05-01"),
            is_holiday=True,
            owner_on_leave_checker=lambda _owner: False,
        )

        self.assertEqual(result["summary"]["private_count"], 0)
        self.assertEqual(result["summary"]["group_count"], 0)
        self.assertEqual(result["routes"]["private"], {})
        self.assertEqual(result["routes"]["group"]["count"], 0)
        self.assertEqual(result["routes"]["group"]["items"], [])
        self.assertEqual(result["routes"]["unmapped"]["count"], 0)
        self.assertEqual(result["grouped_results"]["缺失 DDL"], [item])
        self.assertTrue(result["vacation"]["is_holiday"])

    def test_personal_leave_guard_filters_private_and_group_routes(self):
        owner_on_leave = self._owner(name="张三", email="zhangsan@bytedance.com", open_id="ou_1")
        owner_available = self._owner(name="李四", email="lisi@bytedance.com", open_id="ou_2")
        leave_item = self._item(key="r2:任务A", task="任务A", owner=owner_on_leave)
        keep_item = self._item(key="r3:任务B", task="任务B", owner=owner_available)

        output = {
            "summary": {"today": "2026-05-04", "private_count": 2, "group_count": 2},
            "grouped_results": {"缺失 DDL": [leave_item, keep_item]},
            "routes": {
                "private": {
                    owner_on_leave["email"]: {
                        "owner": owner_on_leave,
                        "count": 1,
                        "items": [leave_item],
                        "message": "leave-private-msg",
                        "card": {"name": "AimeCard"},
                        "mentions_open_ids": [],
                    },
                    owner_available["email"]: {
                        "owner": owner_available,
                        "count": 1,
                        "items": [keep_item],
                        "message": "keep-private-msg",
                        "card": {"name": "AimeCard"},
                        "mentions_open_ids": [],
                    },
                },
                "group": {
                    "target_chat": {"chat_id": "oc_xxx", "name": ""},
                    "count": 2,
                    "items": [dict(leave_item, stage="group"), dict(keep_item, stage="group")],
                    "mentions_open_ids": [owner_on_leave["open_id"], owner_available["open_id"]],
                    "message": "group-msg",
                    "card": {"name": "AimeCard"},
                },
                "unmapped": {"count": 0, "items": []},
            },
        }

        result = apply_vacation_guard(
            output,
            today=date.fromisoformat("2026-05-04"),
            is_holiday=False,
            owner_on_leave_checker=lambda owner: owner.email == owner_on_leave["email"],
        )

        self.assertNotIn(owner_on_leave["email"], result["routes"]["private"])
        self.assertIn(owner_available["email"], result["routes"]["private"])
        self.assertEqual(result["summary"]["private_count"], 1)
        self.assertEqual(result["summary"]["group_count"], 1)
        self.assertEqual(result["routes"]["group"]["count"], 1)
        self.assertEqual(len(result["routes"]["group"]["items"]), 1)
        self.assertEqual(result["routes"]["group"]["items"][0]["key"], keep_item["key"])
        self.assertTrue(result["routes"]["private"][owner_available["email"]]["message"])
        self.assertIsNotNone(result["routes"]["private"][owner_available["email"]]["card"])
        self.assertTrue(result["vacation"]["personal_checker_enabled"])
        self.assertEqual(result["vacation"]["skipped"]["private_route_keys"], [owner_on_leave["email"]])
        self.assertEqual(result["vacation"]["skipped"]["group_item_keys"], [leave_item["key"]])


if __name__ == "__main__":
    unittest.main()
