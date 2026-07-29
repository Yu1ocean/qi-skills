import sys
import unittest
from datetime import date
from pathlib import Path

# 让 `task_flow_engine` 可被 import
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from task_flow_engine.patrol import TaskPatrol, build_owner_directory_from_roster_rows, _normalize_person_key


class TestRosterMapping(unittest.TestCase):
    def test_roster_mapping_prefers_email_for_route_key(self):
        roster_rows = [
            {
                "__row_number": 2,
                "中文名称": "张三",
                "Open ID": "ou_123",
                "邮箱": "zhangsan@bytedance.com",
            }
        ]
        directory, duplicates = build_owner_directory_from_roster_rows(roster_rows)
        self.assertEqual(duplicates, [])

        # 负责人字段可能带括号备注
        raw_owner = "张三（代理）"
        key = _normalize_person_key(raw_owner)
        self.assertIn(key, directory)
        self.assertEqual(directory[key].email, "zhangsan@bytedance.com")
        self.assertEqual(directory[key].open_id, "ou_123")

        def resolve_owner(raw: str):
            k = _normalize_person_key(raw)
            hit = directory.get(k)
            if hit is None:
                return None
            return hit

        today = date.fromisoformat("2026-05-03")
        patrol = TaskPatrol(owner_resolver=resolve_owner)
        task_rows = [
            {
                "__row_number": 2,
                "负责人": raw_owner,
                "交付结果": "【测试任务】",
                "完成情况": "",
                "DDL": "2026-05-03",
            }
        ]
        out = patrol.run(task_rows, today=today)

        private_routes = out["routes"]["private"]
        self.assertIn("zhangsan@bytedance.com", private_routes)
        bucket = private_routes["zhangsan@bytedance.com"]
        self.assertEqual(bucket["owner"]["email"], "zhangsan@bytedance.com")
        self.assertEqual(bucket["owner"]["open_id"], "ou_123")

    def test_roster_mapping_can_reverse_lookup_email_placeholder(self):
        roster_rows = [
            {
                "__row_number": 2,
                "中文名称": "张三",
                "Open ID": "ou_123",
                "邮箱": "zhangsan@bytedance.com",
            }
        ]
        directory, _ = build_owner_directory_from_roster_rows(roster_rows)

        key = _normalize_person_key("zhangsan@bytedance.com")
        self.assertIn(key, directory)
        self.assertEqual(directory[key].display_name, "张三")
        self.assertEqual(directory[key].email, "zhangsan@bytedance.com")

    def test_roster_duplicate_name_is_reported(self):
        roster_rows = [
            {"__row_number": 2, "中文名称": "李四", "Open ID": "ou_1", "邮箱": "a@bytedance.com"},
            {"__row_number": 3, "中文名称": "李四", "Open ID": "ou_2", "邮箱": "b@bytedance.com"},
        ]
        directory, duplicates = build_owner_directory_from_roster_rows(roster_rows)

        # 后者覆盖前者
        key = _normalize_person_key("李四")
        self.assertEqual(directory[key].open_id, "ou_2")
        self.assertTrue(duplicates)
        self.assertEqual(duplicates[0]["normalized_name"], key)


if __name__ == "__main__":
    unittest.main()
