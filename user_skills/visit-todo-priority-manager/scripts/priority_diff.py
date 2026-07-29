#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途：
    对原始 todo_rows 与人工校准版本做任务级 diff，产出优先级变更明细与未变更统计。

输入：
    - original.json：原始 To-Do JSON 数组
    - calibrated.json：人工校准后的 To-Do JSON 数组

输出：
    - JSON：包含变更列表、未变更数量、统计信息
    - Markdown：适合直接贴进文档的 diff 表格

用法示例：
    python priority_diff.py --original original.json --calibrated calibrated.json --format markdown
    python priority_diff.py --original original.json --calibrated calibrated.json --format json
"""

from __future__ import annotations

import argparse
import json
import re

VALID_PRIORITIES = {"P0", "P1", "P2"}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@bytedance\.com", re.IGNORECASE)


class DiffError(RuntimeError):
    """Raised when diff generation fails."""


def _normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value).strip()).lower()


def _task_key(item: dict[str, object]) -> str:
    task_key = _normalize_text(item.get("task_key"))
    if task_key:
        return f"task_key::{task_key}"
    owner = _normalize_text(item.get("owner"))
    description = _normalize_text(item.get("description") or item.get("task_name"))[:30]
    if not owner or not description:
        raise DiffError("缺少 task_key 且无法退化为 (owner, description[:30]) 匹配")
    return f"fallback::{owner}::{description}"


def _display_key(item: dict[str, object]) -> str:
    if item.get("task_key"):
        return str(item["task_key"])
    owner = "" if item.get("owner") is None else str(item.get("owner")).strip()
    description = "" if item.get("description") is None else str(item.get("description")).strip()
    return f"{owner} | {description[:30]}"


def _normalize_priority(value: object) -> str:
    priority = "" if value is None else str(value).strip().upper()
    if priority not in VALID_PRIORITIES:
        raise DiffError(f"priority 非法：{value}")
    return priority


def _validate_item(item: dict[str, object], side: str, index: int) -> None:
    if not isinstance(item, dict):
        raise DiffError(f"{side} 第 {index} 项不是对象")
    _normalize_priority(item.get("priority"))
    owner = "" if item.get("owner") is None else str(item.get("owner")).strip()
    if owner and EMAIL_RE.search(owner):
        raise DiffError(f"{side} 第 {index} 项 owner 残留邮箱：{owner}")


def _build_index(items: list[dict[str, object]], side: str) -> dict[str, dict[str, object]]:
    index_map: dict[str, dict[str, object]] = {}
    for idx, item in enumerate(items, start=1):
        _validate_item(item, side, idx)
        key = _task_key(item)
        if key in index_map:
            raise DiffError(f"{side} 存在重复任务键：{_display_key(item)}")
        index_map[key] = item
    return index_map


def build_diff(
    original_rows: list[dict[str, object]], calibrated_rows: list[dict[str, object]]
) -> dict[str, object]:
    original_index = _build_index(original_rows, "original")
    calibrated_index = _build_index(calibrated_rows, "calibrated")

    changes: list[dict[str, object]] = []
    unchanged_count = 0
    unmatched_count = 0

    for key, calibrated_item in calibrated_index.items():
        original_item = original_index.get(key)
        if not original_item:
            unmatched_count += 1
            changes.append(
                {
                    "task_key": _display_key(calibrated_item),
                    "old_priority": "[未匹配]",
                    "new_priority": _normalize_priority(calibrated_item.get("priority")),
                    "change_reason": calibrated_item.get("change_reason") or "人工校准版本中新增或未匹配到原任务",
                }
            )
            continue

        old_priority = _normalize_priority(original_item.get("priority"))
        new_priority = _normalize_priority(calibrated_item.get("priority"))
        if old_priority == new_priority:
            unchanged_count += 1
            continue

        changes.append(
            {
                "task_key": _display_key(calibrated_item),
                "old_priority": old_priority,
                "new_priority": new_priority,
                "change_reason": calibrated_item.get("change_reason")
                or calibrated_item.get("priority_reason")
                or "人工校准",
            }
        )

    return {
        "changes": changes,
        "unchanged_count": unchanged_count,
        "changed_count": len(changes),
        "original_count": len(original_rows),
        "calibrated_count": len(calibrated_rows),
        "unmatched_count": unmatched_count,
    }


def render_markdown(diff_result: dict[str, object]) -> str:
    lines = [
        f"- 原始条目数：{diff_result['original_count']}",
        f"- 校准条目数：{diff_result['calibrated_count']}",
        f"- 变更条目数：{diff_result['changed_count']}",
        f"- 未变更条目数：{diff_result['unchanged_count']}",
        f"- 未匹配条目数：{diff_result['unmatched_count']}",
        "",
    ]

    changes = diff_result["changes"]
    if not changes:
        lines.append("无优先级变更。")
        return "\n".join(lines)

    lines.extend(
        [
            "| 任务键 | 原优先级 | 新优先级 | 变更原因 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in changes:
        lines.append(
            f"| {row['task_key']} | {row['old_priority']} | {row['new_priority']} | {row['change_reason']} |"
        )
    return "\n".join(lines)


def _load_rows(file_path: str) -> list[dict[str, object]]:
    with open(file_path, "r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, list):
        raise DiffError(f"{file_path} 必须是 JSON 数组")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate priority diff between original and calibrated todo rows")
    parser.add_argument("--original", required=True, help="原始 todo_rows JSON 文件")
    parser.add_argument("--calibrated", required=True, help="人工校准后的 todo_rows JSON 文件")
    parser.add_argument("--format", choices=["json", "markdown"], default="json", help="输出格式")
    args = parser.parse_args()

    diff_result = build_diff(_load_rows(args.original), _load_rows(args.calibrated))
    if args.format == "markdown":
        print(render_markdown(diff_result))
    else:
        print(json.dumps({"ok": True, **diff_result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DiffError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    except json.JSONDecodeError as error:
        print(json.dumps({"ok": False, "error": f"JSON 解析失败：{error}"}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
