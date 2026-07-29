import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from task_flow_engine.broadcast_card import (
    build_minimal_broadcast_card,
    pick_top_focus_owners,
    render_owner_category_table_image,
)


class TestBroadcastVisualCard(unittest.TestCase):
    def setUp(self):
        tmp_root = REPO_ROOT / ".tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="broadcast_card_", dir=str(tmp_root)))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _owner(self, name: str, open_id: str, email: str) -> dict:
        return {
            "display_name": name,
            "raw": name,
            "open_id": open_id,
            "email": email,
            "source": "sheet_roster",
        }

    def test_pick_top_focus_owners_prioritizes_overdue_then_missing_ddl(self):
        xia = self._owner("夏春雨", "ou_xia", "xia@bytedance.com")
        yu = self._owner("于奇楠", "ou_yu", "yu@bytedance.com")
        zhao = self._owner("赵月晨", "ou_zhao", "zhao@bytedance.com")
        items = [
            {"key": "1", "task": "任务A", "alert_category": "已超期", "issue_type": "overdue", "owners": [xia]},
            {"key": "2", "task": "任务B", "alert_category": "缺失 DDL", "issue_type": "missing_ddl", "owners": [xia]},
            {"key": "3", "task": "任务C", "alert_category": "缺失 DDL", "issue_type": "missing_ddl", "owners": [xia]},
            {"key": "4", "task": "任务D", "alert_category": "已超期", "issue_type": "overdue", "owners": [yu]},
            {"key": "5", "task": "任务E", "alert_category": "已超期", "issue_type": "overdue", "owners": [yu]},
            {"key": "6", "task": "任务F", "alert_category": "临近到期", "issue_type": "due_soon", "owners": [yu]},
            {"key": "7", "task": "任务G", "alert_category": "缺失 DDL", "issue_type": "missing_ddl", "owners": [zhao]},
            {"key": "8", "task": "任务H", "alert_category": "缺失 DDL", "issue_type": "missing_ddl", "owners": [zhao]},
            {"key": "9", "task": "任务I", "alert_category": "格式异常", "issue_type": "format_error", "owners": [zhao]},
        ]

        top3 = pick_top_focus_owners(items, top_n=3)
        self.assertEqual([owner["display_name"] for owner in top3], ["于奇楠", "夏春雨", "赵月晨"])

    def test_render_owner_category_table_image_outputs_png_with_four_aligned_categories(self):
        xia = self._owner("夏春雨", "ou_xia", "xia@bytedance.com")
        yu = self._owner("于奇楠", "ou_yu", "yu@bytedance.com")
        items = [
            {"key": "1", "task": "任务A", "alert_category": "已超期", "issue_type": "overdue", "owners": [xia]},
            {"key": "2", "task": "任务B", "alert_category": "临近到期", "issue_type": "due_soon", "owners": [xia]},
            {"key": "3", "task": "任务C", "alert_category": "缺失 DDL", "issue_type": "missing_ddl", "owners": [yu]},
            {"key": "4", "task": "任务D", "alert_category": "格式异常", "issue_type": "format_error", "owners": [yu]},
        ]
        output_path = self.temp_dir / "stats.png"
        top3 = pick_top_focus_owners(items, top_n=3)

        meta = render_owner_category_table_image(
            items=items,
            today_text="2026-05-11",
            output_path=output_path,
            top_focus_owners=top3,
        )

        self.assertTrue(output_path.exists())
        self.assertGreater(output_path.stat().st_size, 0)
        self.assertEqual(meta["column_count"], 6)
        self.assertEqual(meta["summary_counts"]["已超期"], 1)
        self.assertEqual(meta["summary_counts"]["临近到期"], 1)
        self.assertEqual(meta["summary_counts"]["缺失 DDL"], 1)
        self.assertEqual(meta["summary_counts"]["格式异常"], 1)

    def test_build_minimal_broadcast_card_renders_focus_section_and_embeds_image(self):
        top3 = [
            {
                "display_name": "夏春雨",
                "open_id": "ou_xia",
                "email": "xia@bytedance.com",
                "counts": {"临近到期": 1, "缺失 DDL": 4},
                "total": 5,
            },
            {
                "display_name": "于奇楠",
                "open_id": "ou_yu",
                "email": "yu@bytedance.com",
                "counts": {"已超期": 2, "临近到期": 1},
                "total": 3,
            },
            {
                "display_name": "赵月晨",
                "open_id": "ou_zhao",
                "email": "zhao@bytedance.com",
                "counts": {"缺失 DDL": 2, "格式异常": 1},
                "total": 3,
            },
        ]
        card = build_minimal_broadcast_card(
            today_text="2026-05-11",
            summary_counts={"已超期": 4, "临近到期": 3, "缺失 DDL": 9, "格式异常": 2},
            top_focus_owners=top3,
            action_text="前往任务工作站处理",
            action_url="https://example.com/workstation",
            image_key="img_v2_test",
        )

        elements = card["dsl"]["body"]["elements"]
        markdown_contents = "\n".join(element.get("content", "") for element in elements if element.get("tag") == "markdown")
        self.assertIn("**📊 巡检统计**", markdown_contents)
        self.assertIn("**📌 重点关注**", markdown_contents)
        self.assertIn("🔵 **临近到期** 3", markdown_contents)
        self.assertIn("<at id=\"ou_yu\"></at>", markdown_contents)
        self.assertNotIn("‼️", markdown_contents)
        self.assertNotIn("🚨", markdown_contents)
        self.assertNotIn("1. <at id=", markdown_contents)
        self.assertTrue(any(element.get("tag") == "hr" for element in elements))
        self.assertTrue(any(element.get("tag") == "img" and element.get("img_key") == "img_v2_test" for element in elements))
        self.assertEqual(markdown_contents.count("<at id="), 3)


if __name__ == "__main__":
    unittest.main()
