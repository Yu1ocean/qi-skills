#!/usr/bin/env python3
import json
from pathlib import Path

import scripts.patrol as patrol

URL = "https://bytedance.sg.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV?sheet=uJkm4f"
EP = Path("/workspace/iris_19f7e856-22a9-491e-b611-5e5c09e9e419/.ephemeral_pool")
EP.mkdir(parents=True, exist_ok=True)

plan = patrol.run_mode_b(URL, True)
run_id = plan["run_id"] + "-private"

scheduled_lines = [
    f"- {item['user']['name']}：{item['reserved_slot']['start_time'][11:16]} ~ {item['reserved_slot']['end_time'][11:16]}"
    for item in plan["scheduled"]
] or ["- 无可强插档期"]

unresolved_lines = [
    f"- {item['user']['name']}：{item['reason']}"
    for item in plan["unresolvable"]
] or ["- 无"]

plan_path = EP / f"[{run_id}]_weekly_top3_patrol_modeB_plan.json"
post_path = EP / f"[{run_id}]_weekly_top3_patrol_modeB_private_summary.post.json"
card_path = EP / f"[{run_id}]_weekly_top3_patrol_modeB_preview.card.json"

private_post = {
    "zh_cn": {
        "title": "Weekly Top3 Patrol Mode B（Dry Run 私发验收）",
        "content": [
            [{"tag": "text", "text": f"周次：{plan['week']}"}],
            [{"tag": "text", "text": f"待补齐：{plan['pending_count']} 人；可强插：{plan['scheduled_count']} 人；未解：{len(plan['unresolvable'])} 人"}],
            [{"tag": "text", "text": "拟强插日程：\n" + "\n".join(scheduled_lines)}],
            [{"tag": "text", "text": "未解名单：\n" + "\n".join(unresolved_lines)}],
            [{"tag": "text", "text": f"群播预览卡片：见下一条 interactive card\n完整计划 JSON：{plan_path}"}],
        ],
    }
}

plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
post_path.write_text(json.dumps(private_post, ensure_ascii=False, indent=2), encoding="utf-8")
card_path.write_text(json.dumps(patrol.build_l0_card(plan), ensure_ascii=False, indent=2), encoding="utf-8")

print(json.dumps({
    "run_id": run_id,
    "plan_path": str(plan_path),
    "post_path": str(post_path),
    "card_path": str(card_path),
}, ensure_ascii=False))
