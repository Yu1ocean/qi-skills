#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用途：
    visit-todo-priority-manager 的护栏层脚本，负责输入链接校验、To-Do 行字段校验、DDL 标准化、
    优先级枚举断言，以及应升级条目的识别。

输入：
    - 飞书 Wiki / Docx 链接列表
    - To-Do JSON 数组（每项通常包含 owner / ddl / priority / description / source / status 等字段）

输出：
    - 合法链接列表
    - 标准化后的 To-Do 行（补充 normalized_ddl / ddl_days）
    - 需升级条目列表（DDL <= 3 天、未完成、且 priority == P1）

用法示例：
    python todo_priority_guard.py --input rows.json
    python todo_priority_guard.py --doc-urls '["https://bytedance.larkoffice.com/docx/xxx"]'
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta

DEFAULT_DDL_PLACEHOLDER = "待确认"
VALID_PRIORITIES = {"P0", "P1", "P2"}
COMPLETED_STATUS = {"完成", "已完成"}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@bytedance\.com", re.IGNORECASE)
LARK_DOC_RE = re.compile(
    r"^https://[A-Za-z0-9.-]+\.(?:larkoffice\.com|feishu\.cn)/(?:wiki|docx)/[A-Za-z0-9]+(?:\?.*)?$"
)
ABSOLUTE_PATTERNS = (
    re.compile(r"^(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})$"),
    re.compile(r"^(?P<year>\d{4})/(?P<month>\d{1,2})/(?P<day>\d{1,2})$"),
    re.compile(r"^(?P<month>\d{1,2})月(?P<day>\d{1,2})日$"),
)


class GuardrailError(RuntimeError):
    """Raised when guardrail validation fails."""


def _ensure_base_date(base_date: object = None) -> date:
    if base_date is None:
        return date.today()
    if isinstance(base_date, date) and not isinstance(base_date, datetime):
        return base_date
    if isinstance(base_date, datetime):
        return base_date.date()
    if isinstance(base_date, str):
        parsed = normalize_ddl(base_date, date.today())
        if parsed["normalized_ddl"] == DEFAULT_DDL_PLACEHOLDER:
            raise GuardrailError(f"base_date 无法解析：{base_date}")
        return datetime.strptime(parsed["normalized_ddl"], "%Y-%m-%d").date()
    raise GuardrailError(f"不支持的 base_date 类型：{type(base_date).__name__}")


def _safe_date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise GuardrailError(f"非法日期：{year:04d}-{month:02d}-{day:02d}") from exc


def _next_weekday(base: date, weekday: int) -> date:
    delta = weekday - base.weekday()
    if delta <= 0:
        delta += 7
    return base + timedelta(days=delta)


def validate_input_links(urls: list[str]) -> list[str]:
    if not isinstance(urls, list) or not urls:
        raise GuardrailError("输入链接不能为空，且必须是数组")

    cleaned: list[str] = []
    for raw_url in urls:
        url = str(raw_url).strip()
        if not url:
            raise GuardrailError("发现空链接，请仅传入飞书 wiki/docx 链接")
        if not LARK_DOC_RE.match(url):
            raise GuardrailError(
                f"非法链接：{url}。仅支持飞书 Wiki/Docx 链接，例如 https://bytedance.larkoffice.com/docx/xxxx"
            )
        cleaned.append(url)
    return cleaned


def normalize_ddl(ddl_str: object, base_date: object = None) -> dict[str, object]:
    base = _ensure_base_date(base_date)
    raw_text = "" if ddl_str is None else str(ddl_str).strip()
    if not raw_text:
        return {"raw_ddl": raw_text, "normalized_ddl": DEFAULT_DDL_PLACEHOLDER, "ddl_days": None}

    text = re.sub(r"\s+", "", raw_text)
    target_date: date | None = None

    for pattern in ABSOLUTE_PATTERNS:
        matched = pattern.match(text)
        if not matched:
            continue
        groups = matched.groupdict()
        year = int(groups.get("year") or base.year)
        month = int(groups["month"])
        day = int(groups["day"])
        target_date = _safe_date(year, month, day)
        break

    if target_date is None:
        if text in {"今天", "今日"}:
            target_date = base
        elif text == "明天":
            target_date = base + timedelta(days=1)
        elif text == "后天":
            target_date = base + timedelta(days=2)
        elif text == "本周":
            target_date = base + timedelta(days=max(0, 6 - base.weekday()))
        elif text == "下周":
            next_monday = _next_weekday(base, 0)
            target_date = next_monday + timedelta(days=4)
        elif text == "会前":
            return {"raw_ddl": raw_text, "normalized_ddl": DEFAULT_DDL_PLACEHOLDER, "ddl_days": None}

    if target_date is None:
        return {"raw_ddl": raw_text, "normalized_ddl": DEFAULT_DDL_PLACEHOLDER, "ddl_days": None}

    normalized = target_date.strftime("%Y-%m-%d")
    return {
        "raw_ddl": raw_text,
        "normalized_ddl": normalized,
        "ddl_days": (target_date - base).days,
    }


def _normalize_status(status: object) -> str:
    return "" if status is None else str(status).strip()


def _normalize_owner(owner: object) -> str:
    text = "" if owner is None else str(owner).strip()
    if not text:
        raise GuardrailError("Owner 不能为空")
    if EMAIL_RE.search(text):
        raise GuardrailError(f"Owner 仍残留邮箱，请回捞真实姓名后再交付：{text}")
    return text


def _normalize_priority(priority: object) -> str:
    text = "" if priority is None else str(priority).strip().upper()
    if text not in VALID_PRIORITIES:
        raise GuardrailError(f"priority 只允许 P0/P1/P2，当前收到：{priority}")
    return text


def validate_todo_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    if not isinstance(rows, list) or not rows:
        raise GuardrailError("rows 必须是非空 JSON 数组")

    validated_rows: list[dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise GuardrailError(f"第 {index} 条不是对象，无法校验")

        owner = _normalize_owner(row.get("owner"))
        priority = _normalize_priority(row.get("priority"))
        description = "" if row.get("description") is None else str(row.get("description")).strip()
        source = "" if row.get("source") is None else str(row.get("source")).strip()
        status = _normalize_status(row.get("status"))

        if not description:
            raise GuardrailError(f"第 {index} 条 description 不能为空")
        if not source:
            raise GuardrailError(f"第 {index} 条 source 不能为空")

        ddl_info = normalize_ddl(row.get("ddl"))
        normalized_row = dict(row)
        normalized_row["owner"] = owner
        normalized_row["priority"] = priority
        normalized_row["description"] = description
        normalized_row["source"] = source
        normalized_row["status"] = status
        normalized_row["ddl"] = ddl_info["normalized_ddl"]
        normalized_row["raw_ddl"] = ddl_info["raw_ddl"]
        normalized_row["normalized_ddl"] = ddl_info["normalized_ddl"]
        normalized_row["ddl_days"] = ddl_info["ddl_days"]
        validated_rows.append(normalized_row)

    return validated_rows


def check_escalation(rows: list[dict[str, object]], threshold: int = 3) -> list[dict[str, object]]:
    validated_rows = validate_todo_rows(rows)
    escalations: list[dict[str, object]] = []

    for row in validated_rows:
        ddl_days = row.get("ddl_days")
        status = _normalize_status(row.get("status"))
        priority = str(row.get("priority", "")).upper()
        if isinstance(ddl_days, int) and ddl_days <= threshold and status not in COMPLETED_STATUS and priority == "P1":
            escalations.append(
                {
                    "task_key": row.get("task_key") or f"{row.get('owner', '')}|{str(row.get('description', ''))[:30]}",
                    "old_priority": "P1",
                    "new_priority": "P0",
                    "ddl": row.get("ddl"),
                    "ddl_days": ddl_days,
                    "owner": row.get("owner"),
                    "description": row.get("description"),
                    "status": status or "待补",
                    "change_reason": f"DDL ≤ {threshold} 天且未完成，按规则应升级为 P0",
                }
            )
    return escalations


def _load_json_file(file_path: str) -> object:
    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


def main() -> int:
    parser = argparse.ArgumentParser(description="visit-todo-priority-manager guardrail validator")
    parser.add_argument("--input", help="待校验的 todo_rows JSON 文件路径")
    parser.add_argument("--doc-urls", help="待校验的飞书文档链接 JSON 数组")
    args = parser.parse_args()

    if args.doc_urls:
        urls = json.loads(args.doc_urls)
        result = validate_input_links(urls)
        print(json.dumps({"ok": True, "urls": result}, ensure_ascii=False, indent=2))
        return 0

    if args.input:
        payload = _load_json_file(args.input)
        if not isinstance(payload, list):
            raise GuardrailError("--input 对应文件必须是 JSON 数组")
        rows = validate_todo_rows(payload)
        escalations = check_escalation(rows)
        print(
            json.dumps(
                {
                    "ok": True,
                    "row_count": len(rows),
                    "rows": rows,
                    "escalation_count": len(escalations),
                    "escalations": escalations,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    raise GuardrailError("请通过 --input 或 --doc-urls 指定校验对象")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GuardrailError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    except json.JSONDecodeError as error:
        print(json.dumps({"ok": False, "error": f"JSON 解析失败：{error}"}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
