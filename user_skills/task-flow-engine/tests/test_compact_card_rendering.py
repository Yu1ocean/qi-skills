import sys
import unittest
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from task_flow_engine.patrol import (
    BROADCAST_CHAT_ID,
    OwnerIdentity,
    PatrolFinding,
    TaskPatrol,
    build_compact_patrol_card_a,
)


class TestCompactCardRendering(unittest.TestCase):
    def _owner(self, name: str, open_id: str, email: str) -> OwnerIdentity:
        return OwnerIdentity(raw=name, display_name=name, open_id=open_id, email=email, source="sheet_roster")

    def _finding(
        self,
        *,
        key: str,
        task: str,
        category: str,
        issue_type: str,
        owners,
        row: int,
        overdue_days=None,
        abnormal_days=None,
        delta_days=None,
        reason="",
    ) -> PatrolFinding:
        return PatrolFinding(
            key=key,
            row=row,
            task=task,
            status=None,
            owners=list(owners),
            ddl_raw=None,
            ddl_parsed=None,
            delta_days=delta_days,
            alert_category=category,
            reason=reason,
            issue_type=issue_type,
            overdue_days=overdue_days,
            abnormal_days=abnormal_days,
            stage="group",
        )

    def test_owner_first_card_body_groups_by_owner_then_category(self):
        zhang = self._owner("张三", "ou_zhang", "zhangsan@bytedance.com")
        li = self._owner("李四", "ou_li", "lisi@bytedance.com")
        items = [
            self._finding(key="1", task="靶向100个商家", category="已超期", issue_type="overdue", owners=[zhang], row=2, overdue_days=8),
            self._finding(key="2", task="【招商活动】设定目标", category="已超期", issue_type="overdue", owners=[zhang], row=3, overdue_days=2),
            self._finding(key="3", task="商家续费复盘", category="已超期", issue_type="overdue", owners=[zhang], row=4, overdue_days=1),
            self._finding(key="4", task="Leads管理表", category="缺失 DDL", issue_type="missing_ddl", owners=[zhang], row=5, abnormal_days=6, reason="DDL为空"),
            self._finding(key="5", task="商家入驻one-pager", category="临近到期", issue_type="due_soon", owners=[li], row=6, delta_days=1),
            self._finding(key="6", task="商家入驻卡点收集", category="格式异常", issue_type="format_error", owners=[], row=7, abnormal_days=2, reason="负责人为空"),
            self._finding(key="7", task="UK招商专项", category="格式异常", issue_type="format_error", owners=[], row=8, abnormal_days=1, reason="负责人为空"),
        ]

        # 模拟群聊播报：过滤掉临近到期项
        filtered_items = [it for it in items if it.issue_type != "due_soon"]
        card, meta = build_compact_patrol_card_a(
            items=filtered_items,
            today=date.fromisoformat("2026-05-08"),
            title="📌 任务巡检提醒",
            template="blue",
            summary_label="异常任务",
            action_text="前往任务工作站处理",
            action_url="https://bytedance.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV?sheet=KmlJhs",
            max_items_per_group=2,
        )

        body_md = card["dsl"]["body"]["elements"][0]["content"]
        self.assertIn("👤 <at id=\"ou_zhang\"></at>：共 4 项异常", body_md)
        self.assertIn("- 🔴 **已超期**：3 项（`靶向100个商家`、`【招商活动】设定目标`、等 1 项）", body_md)
        self.assertIn("- 🟡 **缺失 DDL**：1 项（`Leads管理表`）", body_md)
        # 李四只有“临近到期”，过滤后应不再出现
        self.assertNotIn("👤 <at id=\"ou_li\"></at>", body_md)
        self.assertNotIn("临近到期", body_md)
        self.assertIn("👤 **未分配**：共 2 项异常", body_md)
        self.assertIn("- 🟣 **格式异常**：2 项（`商家入驻卡点收集`、`UK招商专项`）", body_md)
        self.assertEqual(meta["rendered_owners"][0]["owner"], "张三")

    def test_only_changed_mode_hides_unchanged_entries(self):
        owner = self._owner("张三", "ou_zhang", "zhangsan@bytedance.com")
        items = [
            self._finding(key="1", task="靶向100个商家", category="已超期", issue_type="overdue", owners=[owner], row=2, overdue_days=8),
        ]
        _, first_meta = build_compact_patrol_card_a(
            items=items,
            today=date.fromisoformat("2026-05-08"),
            title="📌 任务巡检提醒",
            template="blue",
            summary_label="异常任务",
            action_text="前往任务工作站处理",
            action_url="https://bytedance.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV?sheet=KmlJhs",
            max_items_per_group=3,
        )
        card, meta = build_compact_patrol_card_a(
            items=items,
            today=date.fromisoformat("2026-05-09"),
            title="📌 任务巡检提醒",
            template="blue",
            summary_label="异常任务",
            action_text="前往任务工作站处理",
            action_url="https://bytedance.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV?sheet=KmlJhs",
            max_items_per_group=3,
            only_changed=True,
            previous_snapshot=first_meta["snapshot"],
        )

        body_md = card["dsl"]["body"]["elements"][0]["content"]
        self.assertIn("✅ 今日相对昨日无新增/变化异常，完整列表见工作站。", body_md)
        self.assertEqual(meta["visible_total"], 0)

    def test_task_patrol_forces_fixed_broadcast_chat(self):
        owner = self._owner("张三", "ou_zhang", "zhangsan@bytedance.com")

        def resolve_owner(_raw: str) -> OwnerIdentity:
            return owner

        patrol = TaskPatrol(owner_resolver=resolve_owner, group_card_max_items_per_group=2)
        output = patrol.run(
            [
                {
                    "__row_number": 2,
                    "负责人": "张三",
                    "交付结果": "靶向100个商家",
                    "完成情况": "",
                    "DDL": "2026-05-01",
                }
            ],
            today=date.fromisoformat("2026-05-08"),
            target_chat={"chat_id": "oc_other", "name": "other"},
        )

        self.assertEqual(output["routes"]["group_broadcast"]["target_chat"]["chat_id"], BROADCAST_CHAT_ID)
        self.assertEqual(output["routes"]["group"]["target_chat"]["chat_id"], BROADCAST_CHAT_ID)
        self.assertEqual(output["card_state"]["target_chat"]["chat_id"], BROADCAST_CHAT_ID)


if __name__ == "__main__":
    unittest.main()
