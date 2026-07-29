#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途：
    对 todo_rows 执行自动升级巡检：DDL <= 阈值天数、未完成、且 priority == P1 的任务，升级为 P0。

输入：
    - todo_rows JSON 数组文件

输出：
    - 应升级条目列表
    - 非 dry-run 模式下，会将输入文件中的对应 priority 更新为 P0 并回写

用法示例：
    python escalation_checker.py --input rows.json --dry-run
    python escalation_checker.py --input rows.json --threshold 5
"""

from __future__ import annotations

import argparse
import json
import sys

from todo_priority_guard import check_escalation, validate_todo_rows


class EscalationError(RuntimeError):
    """Raised when escalation checking fails."""


def _load_rows(file_path: str) -> list[dict[str, object]]:
    with open(file_path, "r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, list):
        raise EscalationError("输入文件必须是 JSON 数组")
    return payload


def _build_row_key(row: dict[str, object]) -> str:
    if row.get("task_key"):
        return f"task_key::{row['task_key']}"
    owner = "" if row.get("owner") is None else str(row.get("owner")).strip()
    description = "" if row.get("description") is None else str(row.get("description")).strip()[:30]
    return f"fallback::{owner}::{description}"


def _write_rows(file_path: str, rows: list[dict[str, object]]) -> None:
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(rows, file, ensure_ascii=False, indent=2)


def apply_escalation(rows: list[dict[str, object]], threshold: int) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    validated_rows = validate_todo_rows(rows)
    escalation_rows = check_escalation(validated_rows, threshold=threshold)
    escalation_keys = {_build_row_key(row) for row in escalation_rows}

    updated_rows: list[dict[str, object]] = []
    for row in validated_rows:
        updated_row = dict(row)
        if _build_row_key(updated_row) in escalation_keys:
            updated_row["priority"] = "P0"
        updated_rows.append(updated_row)
    return escalation_rows, updated_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Escalate near-deadline P1 items to P0")
    parser.add_argument("--input", required=True, help="todo_rows JSON 文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只输出应升级条目，不修改文件")
    parser.add_argument("--threshold", type=int, default=3, help="DDL 升级阈值天数，默认 3")
    args = parser.parse_args()

    if args.threshold < 0:
        raise EscalationError("--threshold 不能小于 0")

    rows = _load_rows(args.input)
    escalation_rows, updated_rows = apply_escalation(rows, threshold=args.threshold)

    if not args.dry_run:
        _write_rows(args.input, updated_rows)

    print(
        json.dumps(
            {
                "ok": True,
                "dry_run": args.dry_run,
                "threshold": args.threshold,
                "escalation_count": len(escalation_rows),
                "escalations": escalation_rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EscalationError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    except json.JSONDecodeError as error:
        print(json.dumps({"ok": False, "error": f"JSON 解析失败：{error}"}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
