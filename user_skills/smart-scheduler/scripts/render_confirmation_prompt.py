#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Iterable, List


@dataclass
class CandidateOption:
    index: str
    date: str
    primary_slot: str
    secondary_slot: str
    coverage: str = ""
    note: str = ""


def _parse_option(raw: str) -> CandidateOption:
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) == 2:
        index, label = parts
        return CandidateOption(index=index, date="", primary_slot=label, secondary_slot="")
    if len(parts) not in {4, 5, 6}:
        raise ValueError(
            "option must use '<index>|<label>' or '<index>|<date>|<primary_slot>|<secondary_slot>|<coverage>|<note>' format"
        )
    index, date, primary_slot, secondary_slot = parts[:4]
    coverage = parts[4] if len(parts) >= 5 else ""
    note = parts[5] if len(parts) >= 6 else ""
    if not index or not primary_slot:
        raise ValueError("option index and primary_slot must both be non-empty")
    return CandidateOption(
        index=index,
        date=date,
        primary_slot=primary_slot,
        secondary_slot=secondary_slot,
        coverage=coverage,
        note=note,
    )


def _routing_contract(route: str, *, allow_thread_reply: bool, reason: str) -> dict:
    return {
        "route": route,
        "allow_thread_reply": allow_thread_reply,
        "reason": reason,
        "user_action": "请直接发送一条新消息确认，不要隐式继承当前 Thread / 话题楼层。",
        "explicit_user_pick": "pending",
        "stage_gate": "stop_after_stage_2",
    }


def _build_markdown_table(
    options: List[CandidateOption],
    *,
    primary_tz_label: str,
    secondary_tz_label: str,
) -> List[str]:
    use_structured_table = any(option.date or option.secondary_slot or option.coverage or option.note for option in options)
    if not use_structured_table:
        lines = [
            "| 方案 | 时间段 |",
            "| --- | --- |",
        ]
        for option in options:
            lines.append(f"| {option.index} | {option.primary_slot} |")
        return lines

    header = ["方案", "日期", f"时间段（{primary_tz_label}）"]
    if secondary_tz_label:
        header.append(f"时间段（{secondary_tz_label}）")
    header.extend(["覆盖率", "备注"])

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for option in options:
        row = [option.index, option.date or "-", option.primary_slot]
        if secondary_tz_label:
            row.append(option.secondary_slot or "-")
        row.extend([option.coverage or "-", option.note or "-"])
        lines.append("| " + " | ".join(row) + " |")
    return lines


def build_matrix_confirmation(
    options: Iterable[CandidateOption],
    matrix_url: str,
    *,
    primary_tz_label: str = "BJT",
    secondary_tz_label: str = "",
) -> dict:
    option_list: List[CandidateOption] = list(options)
    if not option_list:
        raise ValueError("at least one candidate option is required")
    if not matrix_url.strip():
        raise ValueError("matrix_url is required")

    lines = [
        "根据您的要求，我为您筛选了以下几个备选时段，并生成了详细的忙闲矩阵供您决策：",
        "",
        "**推荐方案（严格表格）：**",
        "",
    ]
    lines.extend(_build_markdown_table(option_list, primary_tz_label=primary_tz_label, secondary_tz_label=secondary_tz_label))
    lines.extend(
        [
            "",
            f"👉 **[点击查看完整忙闲矩阵]({matrix_url})**",
            "",
            "请直接发送一条**新消息**告知您选择的方案序号（如“1”），或说明最终决定；不要隐式继承当前 Thread / 话题楼层。确认后我再继续创建这些会议。",
            "",
            "**消息路由补充约束**：",
            "- 候选矩阵、忙闲分析、确认提示默认均走 **L0_FLAT 新消息**。",
            "- 禁止助手为了“上下文连续”擅自使用 `reply_to`、Thread 盖楼或话题继承。",
            "- 只有命中 `route_manifest.yaml` 白名单的场景，才允许 L1 话题回复。",
        ]
    )
    return {
        "mode": "matrix",
        "text": "\n".join(lines),
        "routing_contract": _routing_contract(
            "L0_FLAT",
            allow_thread_reply=False,
            reason="候选矩阵确认属于正式决策收口，默认必须走新消息确认。",
        ),
    }


def build_preemption_confirmation(slot: str, owner: str, title: str) -> dict:
    if not slot.strip():
        raise ValueError("slot is required")
    if not owner.strip():
        raise ValueError("owner is required")
    if not title.strip():
        raise ValueError("title is required")

    text = "\n".join(
        [
            "所有人都完全空闲的时段已经找不到了。",
            "",
            f"不过，我发现 **{slot}** 有一个可考虑的“抢占”机会：参会者 **{owner}** 在该时段有一个“未接受”状态的日程 `『{title}』`。",
            "",
            "如果这个会议优先级不高，我们可以尝试预定这个时间。",
            "",
            "**要抢占吗？** 请直接发送一条**新消息**回复“是”或“确认抢占”；不要沿当前 Thread / 话题楼层继续盖楼。",
        ]
    )
    return {
        "mode": "preemption",
        "text": text,
        "routing_contract": _routing_contract(
            "L0_FLAT",
            allow_thread_reply=False,
            reason="抢占确认属于高风险建会前确认，默认必须走新消息。",
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Render smart-scheduler confirmation prompts with explicit routing guardrails.")
    parser.add_argument("--mode", choices=["matrix", "preemption"], required=True)
    parser.add_argument("--matrix-url", default="")
    parser.add_argument("--option", action="append", default=[], help="Matrix option in '<index>|<label>' or structured table format. Repeatable.")
    parser.add_argument("--primary-tz-label", default="BJT")
    parser.add_argument("--secondary-tz-label", default="")
    parser.add_argument("--slot", default="")
    parser.add_argument("--owner", default="")
    parser.add_argument("--title", default="")
    args = parser.parse_args()

    if args.mode == "matrix":
        payload = build_matrix_confirmation(
            [_parse_option(raw) for raw in args.option],
            args.matrix_url,
            primary_tz_label=args.primary_tz_label,
            secondary_tz_label=args.secondary_tz_label,
        )
    else:
        payload = build_preemption_confirmation(args.slot, args.owner, args.title)

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
