import unittest
from pathlib import Path

from task_flow_engine.chat_registry_sync import (
    CHAT_ID_HEADER,
    EXPECTED_KEYWORDS_HEADER,
    OWNER_HEADER,
    REMARKS_HEADER,
    USAGE_HEADER,
    build_registry_payload_from_rows,
)


class TestChatRegistrySync(unittest.TestCase):
    def test_build_registry_payload_from_rows_uses_feishu_metadata(self):
        rows = [
            {
                "__row_number": 2,
                USAGE_HEADER: "task_patrol_broadcast",
                CHAT_ID_HEADER: "oc_b566689fc5704ba70cc0f43fc32f0cc4",
                EXPECTED_KEYWORDS_HEADER: "UK/EU/JP POP BD",
                OWNER_HEADER: [
                    {
                        "type": "url",
                        "text": "yuqinan@bytedance.com",
                        "link": "yuqinan@bytedance.com",
                    }
                ],
                REMARKS_HEADER: "updated_at=2026-05-11；name=任务巡检广播群；default_usage=task_patrol_broadcast；note=任务 DDL 巡检/催办提醒默认群广播目标",
            }
        ]

        payload = build_registry_payload_from_rows(
            rows,
            spreadsheet_token="FvkIslPSgh4XGqtcUqychqU7nzb",
            sheet_title="Sheet1",
            metadata_resolver=lambda chat_id, query: {
                "chat_id": chat_id,
                "name": "UK/EU/JP POP BD",
            },
        )

        self.assertEqual(payload["updated_at"], "2026-05-11")
        self.assertEqual(payload["default_usage"], "task_patrol_broadcast")
        self.assertEqual(payload["source"]["spreadsheet_token"], "FvkIslPSgh4XGqtcUqychqU7nzb")
        self.assertEqual(payload["source"]["sheet_title"], "Sheet1")

        entry = payload["chats"]["task_patrol_broadcast"]
        self.assertEqual(entry["chat_id"], "oc_b566689fc5704ba70cc0f43fc32f0cc4")
        self.assertEqual(entry["name"], "UK/EU/JP POP BD")
        self.assertEqual(entry["lookup_query"], "UK/EU/JP POP BD")
        self.assertEqual(entry["expected_name_keywords"], ["UK/EU/JP POP BD"])
        self.assertEqual(entry["admin_email"], "yuqinan@bytedance.com")
        self.assertIn("任务 DDL 巡检/催办提醒默认群广播目标", entry["description"])


if __name__ == "__main__":
    unittest.main()
