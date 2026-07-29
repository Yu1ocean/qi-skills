#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

DEFAULT_MONTHS = 1
DEFAULT_MAX_MESSAGES = 0
DEFAULT_BATCH_SIZE = 20
DEFAULT_APPROVAL_QUERY_TERMS = [
    "差旅审批",
    "出差审批",
    "travel approval",
    "trip approval",
    "差旅",
]
DEFAULT_BOOKING_QUERY_TERMS = [
    "【差旅】",
    "Hi Travel 火车票",
    "预订了机票",
    "预订了酒店",
    "员工商旅系统",
]
DEFAULT_QUERY_TERMS = list(DEFAULT_APPROVAL_QUERY_TERMS)
DEFAULT_COLLECTION_MODE = "auto"
COLLECTION_MODE_CHOICES = ("approval", "booking", "auto")
BOOKING_NOTIFICATION_KEYWORDS = [
    "员工商旅系统",
    "请勿回复",
    "no reply",
    "noreply",
    "Hi Travel",
    "预订了机票",
    "预订了Hi Travel火车票",
    "预订了酒店",
]
APPROVAL_NOTIFICATION_KEYWORDS = ["差旅审批", "出差审批", "travel approval", "trip approval"]
ALL_PARSED_TRAVELERS_LABEL = "ALL_PARSED_TRAVELERS"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_GEOCODE_SLEEP_SECONDS = 1.0
DEFAULT_MAIL_TRIAGE_PAGE_SLEEP_SECONDS = 0.35
DEFAULT_MAIL_FETCH_BATCH_SLEEP_SECONDS = 0.2
DEFAULT_GEOCODER = "nominatim"
DEFAULT_COUNTRY_HINTS = {
    "departure": "China",
    "destination": "",
}
DEFAULT_DYNAMIC_UI_DIR = ".aime/dynamic-ui/react-card"
DEFAULT_TEMPLATE_NAME = "travel_dashboard_template.html"
DEFAULT_DYNAMIC_UI_TEMPLATE_NAME = "travel_dashboard_dynamic_ui_template.html"
DEFAULT_GEO_CACHE = "output/geo_cache.json"
DEFAULT_CITY_ALIAS_CACHE = "output/city_alias_cache.json"
DEFAULT_FOOTPRINT_LIBRARY = "output/travel_footprint_library.json"
DEFAULT_HOTEL_POLICY_TABLE = "output/hotel_policy_rules.json"
DEFAULT_CITY_ALIAS_CONFIDENCE_THRESHOLD = 80
DEFAULT_CITY_ALIAS_SEEDS = {
    "泉州南": {"city": "泉州", "confidence": 100, "source": "seed"},
    "临平南": {"city": "杭州", "confidence": 100, "source": "seed"},
}
DEFAULT_GEOCODE_ALIAS_PROVIDER_ORDER = ("amap", "baidu")

FIELD_ALIASES = {
    "name": ["申请人", "出差人", "员工姓名", "姓名", "乘机人", "乘车人", "入住人", "Applicant", "Traveler", "Traveller", "Employee"],
    "departure_city": ["出发城市", "出发地", "始发地", "出发", "Departure City", "Departure", "Origin"],
    "destination_city": ["目的城市", "目的地", "到达城市", "前往", "Destination City", "Destination"],
    "departure_time": ["出发时间", "开始时间", "启程时间", "Departure Time", "Start Time"],
    "return_time": ["返程时间", "结束时间", "返回时间", "Return Time", "End Time"],
    "booking_time": ["预订时间", "下单时间", "订票时间", "订房时间", "Booking Time", "Booked At", "Booking Date"],
    "approval_time": ["审批通过时间", "审批时间", "批准时间", "Approval Time", "Approved At", "Approval Date"],
    "cabin_class": ["舱位", "机票舱位", "舱位等级", "Cabin", "Cabin Class"],
    "seat_class": ["席别", "座位等级", "Seat Class"],
    "hotel_price_per_night": ["酒店单晚", "每晚房价", "单晚房费", "Hotel Rate", "Nightly Rate"],
    "hotel_standard_amount": ["酒店差标", "住宿标准", "标准金额", "Hotel Standard", "Policy Limit"],
    "hotel_total_amount": ["酒店总价", "房费总额", "公司支付", "Hotel Total", "Total Hotel Amount"],
    "over_policy_reason": ["超标原因", "超差原因", "超标说明", "Reason for Exception", "Exception Reason"],
    "duplicate_booking_flag": ["重复预订", "重复下单", "Duplicate Booking"],
}

TIME_PATTERNS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y.%m.%d %H:%M:%S",
    "%Y.%m.%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
]

BOOL_TRUE_WORDS = {"是", "true", "yes", "y", "1", "已", "有", "命中", "存在", "违规", "超标"}
BOOL_FALSE_WORDS = {"否", "false", "no", "n", "0", "无", "未", "正常", "合规"}
BOOKED_BEFORE_APPROVAL_KEYWORDS = ["先订后批", "审批前预订", "先预订后审批", "booked before approval"]
CABIN_OVER_KEYWORDS = ["商务舱", "头等舱", "超级经济舱", "商务座", "一等座", "非经济型席位", "超舱", "超标舱位"]
HOTEL_OVER_KEYWORDS = ["酒店超标", "超差标", "住宿超标", "房价超标", "超住宿标准"]
DUPLICATE_BOOKING_KEYWORDS = ["重复预订", "重复下单", "duplicate booking", "重复订单"]
OVER_POLICY_REASON_BUCKETS = [
    ("合理安置", ["合理安置", "航班调整", "同伴同行"]),
    ("健康原因", ["健康原因", "身体原因", "医疗", "ehs"]),
    ("无经济舱/标准房", ["无经济舱", "无标准间", "无标准房", "售罄"]),
    ("合作方指定", ["合作方指定", "客户指定", "会议指定酒店"]),
    ("不可抗力", ["不可抗力", "天气", "航班取消", "临时变更"]),
]


class DashboardError(RuntimeError):
    pass


def validate_allowed_names(names: Sequence[str]) -> None:
    return None


def normalize_person_name(raw: Any) -> str:
    value = normalize_text(str(raw or ""))
    value = re.sub(r"^[：:;；,，。\s]+|[：:;；,，。\s]+$", "", value)
    value = re.sub(r"\s+", "", value)
    match = re.search(r"([\u4e00-\u9fa5·]{2,20})", value)
    return match.group(1) if match else ""


def build_default_booking_audit() -> Dict[str, Any]:
    return {
        "hotel_candidates": 0,
        "hotel_enriched_to_transport": 0,
        "hotel_partial_candidate_retained": 0,
        "hotel_partial_retained": 0,
        "hotel_without_transport_match": 0,
        "booking_discarded_count": 0,
        "discard_reasons": {},
    }


def register_booking_discard(audit: Dict[str, Any], reason: str) -> None:
    normalized_reason = normalize_text(reason) or "unknown"
    audit["booking_discarded_count"] = int(audit.get("booking_discarded_count") or 0) + 1
    bucket = audit.setdefault("discard_reasons", {})
    bucket[normalized_reason] = int(bucket.get(normalized_reason) or 0) + 1


def build_record_status(record_status: str, *, travel_context_missing: bool, discard_reason: str = "") -> Dict[str, Any]:
    return {
        "record_status": record_status,
        "travel_context_missing": travel_context_missing,
        "discard_reason": discard_reason,
    }


def normalize_policy_rule(rule: Dict[str, Any], index: int) -> Dict[str, Any]:
    city = normalize_city(rule.get("city") or rule.get("destination_city") or rule.get("destination") or "")
    aliases = [normalize_city(item) for item in (rule.get("aliases") or []) if normalize_city(item)]
    match_level = normalize_text(str(rule.get("match_level") or ("city" if city else "global"))).lower() or "global"
    limit_amount = rule.get("limit_amount")
    if limit_amount in (None, ""):
        limit_amount = rule.get("hotel_standard_amount")
    try:
        limit_value = float(limit_amount) if limit_amount not in (None, "") else None
    except (TypeError, ValueError):
        limit_value = None
    return {
        "rule_id": normalize_text(str(rule.get("rule_id") or rule.get("id") or f"policy-{index + 1:04d}")),
        "city": city,
        "aliases": aliases,
        "match_level": match_level,
        "limit_amount": limit_value,
        "currency": normalize_text(str(rule.get("currency") or "CNY")) or "CNY",
        "priority": int(rule.get("priority") or (100 if city else 10)),
        "raw": rule,
    }


def load_hotel_policy_table(path: Path) -> List[Dict[str, Any]]:
    payload = load_json(path, default={})
    rules = payload.get("rules") if isinstance(payload, dict) else payload
    if not isinstance(rules, list):
        return []
    normalized = [normalize_policy_rule(rule, index) for index, rule in enumerate(rules) if isinstance(rule, dict)]
    normalized = [rule for rule in normalized if rule.get("limit_amount") is not None]
    normalized.sort(key=lambda rule: (-int(rule.get("priority") or 0), 0 if rule.get("city") else 1, rule.get("rule_id") or ""))
    return normalized


def resolve_hotel_policy_rule(destination_city: str, hotel_policy_rules: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    normalized_city = normalize_city(destination_city)
    if not normalized_city:
        return None
    exact_matches = [
        rule for rule in hotel_policy_rules if normalized_city == rule.get("city") or normalized_city in set(rule.get("aliases") or [])
    ]
    if exact_matches:
        return exact_matches[0]
    for fallback_key in ["国内其他城市", "海外其他城市", "其他城市", "默认", "default", "global"]:
        normalized_fallback = normalize_city(fallback_key) if fallback_key not in {"default", "global"} else fallback_key
        for rule in hotel_policy_rules:
            city = rule.get("city") or ""
            aliases = set(rule.get("aliases") or [])
            if fallback_key in {"default", "global"}:
                if rule.get("match_level") in {"global", "default"}:
                    return rule
            elif city == normalized_fallback or normalized_fallback in aliases:
                return rule
    return None


def apply_hotel_policy_fields(record: Dict[str, Any], hotel_policy_rules: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    item = dict(record)
    text = item.get("raw_excerpt") or ""
    explicit_standard_amount = item.get("hotel_standard_amount")
    policy_rule = resolve_hotel_policy_rule(item.get("destination_city") or "", hotel_policy_rules)
    decision_source = "unknown"
    policy_match_level = None
    policy_rule_id = ""
    policy_currency = ""
    if policy_rule and policy_rule.get("limit_amount") is not None:
        item["hotel_standard_amount"] = policy_rule.get("limit_amount")
        decision_source = "policy_table"
        policy_match_level = policy_rule.get("match_level") or "city"
        policy_rule_id = policy_rule.get("rule_id") or ""
        policy_currency = policy_rule.get("currency") or "CNY"
    elif explicit_standard_amount is not None:
        decision_source = "mail_extract"
    elif contains_any(text, HOTEL_OVER_KEYWORDS):
        decision_source = "email_fallback"

    is_hotel_over_policy = derive_hotel_over_policy(item.get("hotel_price_per_night"), item.get("hotel_standard_amount"), text)
    needs_review = False
    hotel_policy_severity = "normal"
    if decision_source == "email_fallback" and is_hotel_over_policy is True:
        needs_review = True
    if decision_source == "unknown" and item.get("hotel_price_per_night") is not None:
        needs_review = True
    if item.get("hotel_price_per_night") is not None and item.get("hotel_standard_amount") not in (None, ""):
        try:
            limit_amount = float(item.get("hotel_standard_amount"))
            if limit_amount > 0 and float(item.get("hotel_price_per_night")) > limit_amount * 2:
                hotel_policy_severity = "critical"
        except (TypeError, ValueError):
            hotel_policy_severity = "normal"

    item["is_hotel_over_policy"] = is_hotel_over_policy
    item["hotel_policy_decision_source"] = decision_source
    item["policy_match_level"] = policy_match_level
    item["policy_rule_id"] = policy_rule_id
    item["policy_currency"] = policy_currency
    item["needs_review"] = bool(item.get("needs_review")) or needs_review
    item["hotel_policy_severity"] = hotel_policy_severity
    item["over_policy_reason"] = derive_over_policy_reason(
        text,
        extract_field_by_aliases(text, FIELD_ALIASES["over_policy_reason"]) or item.get("over_policy_reason") or "",
        item.get("is_over_cabin_policy"),
        item.get("is_hotel_over_policy"),
    )
    return item


def validate_required_fields(row: Dict[str, Any], *, require_return_time: bool = True) -> None:
    required = [
        "name",
        "departure_city",
        "destination_city",
        "departure_time",
    ]
    if require_return_time:
        required.append("return_time")
    missing = [field for field in required if not str(row.get(field, "")).strip()]
    if missing:
        raise DashboardError(f"记录缺少必填字段：{missing} | row={row}")


def run_command(command: Sequence[str], *, action: str, cwd: Optional[Path] = None) -> str:
    result = subprocess.run(
        list(command),
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise DashboardError(
            f"{action} 失败（exit={result.returncode}）\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout


def ensure_mail_cli_ready() -> None:
    run_command(["lark-cli", "mail", "+triage", "-h"], action="检查 lark mail +triage 帮助")
    run_command(["lark-cli", "mail", "+messages", "-h"], action="检查 lark mail +messages 帮助")


def month_delta(now: dt.datetime, months: int) -> dt.datetime:
    year = now.year
    month = now.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(now.day, 28)
    return now.replace(year=year, month=month, day=day)


def parse_window_boundary(value: str, *, is_end: bool) -> Optional[dt.datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = normalize_datetime_string(text)
    if not normalized:
        raise DashboardError(f"无法解析时间参数：{value}")
    parsed = dt.datetime.strptime(normalized, "%Y-%m-%d")
    if re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", text) and is_end:
        parsed = parsed.replace(hour=23, minute=59)
    return parsed


def resolve_collection_window(*, months: int, start_time_text: str = "", end_time_text: str = "") -> Tuple[dt.datetime, dt.datetime]:
    now = dt.datetime.now()
    start_time = parse_window_boundary(start_time_text, is_end=False) if start_time_text else month_delta(now, months)
    end_time = parse_window_boundary(end_time_text, is_end=True) if end_time_text else now
    if start_time > end_time:
        raise DashboardError(f"时间窗非法：start_time={start_time} 晚于 end_time={end_time}")
    return start_time, end_time


def parse_any_json(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return {}
    lines = [
        line
        for line in raw.splitlines()
        if not line.startswith("[Metrics") and "proxy detected" not in line and not line.startswith("\x1b")
    ]
    text = "\n".join(lines).strip()
    start = min([idx for idx in [text.find("{"), text.find("[")] if idx >= 0], default=-1)
    if start > 0:
        text = text[start:]
    return json.loads(text)


def flatten_strings(obj: Any, *, limit: int = 500) -> List[str]:
    values: List[str] = []

    def _walk(node: Any) -> None:
        if len(values) >= limit:
            return
        if node is None:
            return
        if isinstance(node, str):
            s = node.strip()
            if s:
                values.append(s)
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if len(values) >= limit:
                    break
                if isinstance(key, str) and key.strip():
                    values.append(key.strip())
                _walk(value)
            return
        if isinstance(node, list):
            for item in node:
                if len(values) >= limit:
                    break
                _walk(item)
            return
        if isinstance(node, (int, float, bool)):
            values.append(str(node))

    _walk(obj)
    return values


def sanitize_text(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[\t\r\f\v]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def normalize_datetime_string(text: str) -> Optional[str]:
    candidate = (text or "").strip()
    if not candidate:
        return None
    candidate = re.sub(r"(?:周|星期)[一二三四五六日天]", " ", candidate)
    candidate = candidate.replace("（", "(").replace("）", ")")
    candidate = candidate.replace("年", "-").replace("月", "-").replace("日", " ")
    candidate = candidate.replace("/", "-").replace(".", "-")
    candidate = candidate.replace("T", " ")
    candidate = re.sub(r"\([^)]*\)", " ", candidate)
    candidate = re.sub(r"\s+", " ", candidate)
    candidate = candidate.strip(" -")
    candidate = re.sub(r"(\d{2}:\d{2}):(\d{2})", r"\1:\2", candidate)
    for fmt in TIME_PATTERNS:
        try:
            parsed = dt.datetime.strptime(candidate, fmt)
            if fmt in {"%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"}:
                parsed = parsed.replace(hour=0, minute=0, second=0)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    m = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?", candidate)
    if m:
        year, month, day = [int(m.group(i)) for i in range(1, 4)]
        hour = int(m.group(4) or 0)
        minute = int(m.group(5) or 0)
        parsed = dt.datetime(year, month, day, hour, minute)
        return parsed.strftime("%Y-%m-%d")
    partial = re.search(r"(?<!\d)(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?(?!\d)", candidate)
    if partial:
        year = dt.datetime.now().year
        month = int(partial.group(1))
        day = int(partial.group(2))
        hour = int(partial.group(3) or 0)
        minute = int(partial.group(4) or 0)
        parsed = dt.datetime(year, month, day, hour, minute)
        return parsed.strftime("%Y-%m-%d")
    return None


def parse_sent_at(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        try:
            return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            return None
    return normalize_datetime_string(str(value))


def parse_dt_or_none(text_value: Any) -> Optional[dt.datetime]:
    normalized = normalize_datetime_string(str(text_value or ""))
    if not normalized:
        return None
    return dt.datetime.strptime(normalized, "%Y-%m-%d")


def pick_first_present(dct: Dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in dct and dct[key] not in (None, ""):
            return dct[key]
    return None


def extract_message_summaries(payload: Any) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if any(k in node for k in ["message_id", "id"]) and any(
                k in node for k in ["subject", "date", "sent_at", "timestamp"]
            ):
                message_id = node.get("message_id") or node.get("id")
                if message_id:
                    results.append(
                        {
                            "message_id": str(message_id),
                            "subject": str(node.get("subject") or node.get("title") or ""),
                            "date": parse_sent_at(
                                pick_first_present(node, ["date", "date_formatted", "sent_at", "timestamp", "internal_date", "create_time"])
                            ),
                            "raw": node,
                        }
                    )
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
    dedup: Dict[str, Dict[str, Any]] = {}
    for item in results:
        dedup[item["message_id"]] = item
    return list(dedup.values())


def to_cli_time(value: dt.datetime) -> str:
    tz = dt.timezone(dt.timedelta(hours=8))
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
    else:
        value = value.astimezone(tz)
    return value.isoformat(timespec="seconds")


def extract_triage_pagination(payload: Any) -> Tuple[bool, str]:
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), dict):
            data = payload["data"]
            has_more = bool(data.get("has_more"))
            page_token = str(data.get("page_token") or "")
            if has_more or page_token:
                return has_more, page_token
        return bool(payload.get("has_more")), str(payload.get("page_token") or "")
    return False, ""


def cli_triage(
    query: str = "",
    *,
    max_messages: int,
    mailbox: str = "me",
    start_time: Optional[dt.datetime] = None,
    end_time: Optional[dt.datetime] = None,
    folder: str = "",
) -> List[Dict[str, Any]]:
    collected: Dict[str, Dict[str, Any]] = {}
    page_token = ""
    last_token = None
    target_limit = max_messages if max_messages and max_messages > 0 else None

    while target_limit is None or len(collected) < target_limit:
        remaining = 400 if target_limit is None else max(1, target_limit - len(collected))
        page_size = min(remaining, 400)
        command = [
            "lark-cli",
            "mail",
            "+triage",
            "--format",
            "json",
            "--mailbox",
            mailbox,
            "--max",
            str(page_size),
        ]
        filter_payload: Dict[str, Any] = {}
        time_range: Dict[str, str] = {}
        if start_time:
            time_range["start_time"] = to_cli_time(start_time)
        if end_time:
            time_range["end_time"] = to_cli_time(end_time)
        if time_range:
            filter_payload["time_range"] = time_range
        if folder:
            filter_payload["folder"] = folder
        if filter_payload:
            command.extend(["--filter", json.dumps(filter_payload, ensure_ascii=False)])
        if query:
            command.extend(["--query", query])
        if page_token:
            command.extend(["--page-token", page_token])

        output = run_command(
            command,
            action=f"搜索邮件：{query or '[folder sweep]'} | folder={folder or 'ALL'} | page_token={page_token or 'FIRST'}",
        )
        payload = parse_any_json(output)
        page_summaries = extract_message_summaries(payload)
        before_count = len(collected)
        for item in page_summaries:
            collected[item["message_id"]] = item

        has_more, next_page_token = extract_triage_pagination(payload)
        if not has_more or not next_page_token:
            break
        if next_page_token == page_token or next_page_token == last_token:
            break
        if len(collected) == before_count and not page_summaries:
            break
        last_token = page_token
        page_token = next_page_token
        time.sleep(DEFAULT_MAIL_TRIAGE_PAGE_SLEEP_SECONDS)

    return list(collected.values())


def chunked(items: Sequence[str], size: int) -> Iterable[List[str]]:
    for idx in range(0, len(items), size):
        yield list(items[idx : idx + size])


def cli_fetch_messages(message_ids: Sequence[str], *, mailbox: str = "me") -> List[Dict[str, Any]]:
    all_messages: List[Dict[str, Any]] = []
    batches = list(chunked(list(message_ids), DEFAULT_BATCH_SIZE))
    for index, batch in enumerate(batches):
        output = run_command(
            [
                "lark-cli",
                "mail",
                "+messages",
                "--format",
                "json",
                "--mailbox",
                mailbox,
                "--message-ids",
                ",".join(batch),
            ],
            action=f"批量读取邮件：{len(batch)} 封",
        )
        payload = parse_any_json(output)
        if isinstance(payload, dict):
            if isinstance(payload.get("messages"), list):
                all_messages.extend(payload["messages"])
            elif isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("messages"), list):
                all_messages.extend(payload["data"]["messages"])
            elif isinstance(payload.get("data"), list):
                all_messages.extend(payload["data"])
            else:
                all_messages.append(payload)
        elif isinstance(payload, list):
            all_messages.extend(payload)
        if index < len(batches) - 1:
            time.sleep(DEFAULT_MAIL_FETCH_BATCH_SLEEP_SECONDS)
    return all_messages


def summary_matches_collection(summary: Dict[str, Any], *, mode: str, query_terms: Sequence[str]) -> bool:
    signal_text = "\n".join(
        flatten_strings(
            {
                "subject": summary.get("subject") or "",
                "raw": summary.get("raw") or {},
            },
            limit=80,
        )
    ).lower()
    if not signal_text.strip():
        return False

    booking_signals = {item.lower() for item in DEFAULT_BOOKING_QUERY_TERMS + BOOKING_NOTIFICATION_KEYWORDS}
    approval_signals = {item.lower() for item in DEFAULT_APPROVAL_QUERY_TERMS + APPROVAL_NOTIFICATION_KEYWORDS}
    query_signals = {str(item or "").strip().lower() for item in query_terms if str(item or "").strip()}

    if mode == "booking":
        signals = booking_signals | query_signals
    elif mode == "approval":
        signals = approval_signals | query_signals
    else:
        signals = booking_signals | approval_signals | query_signals
    return any(signal and signal in signal_text for signal in signals)


def extract_message_text(message: Dict[str, Any]) -> str:
    primary_parts: List[str] = []
    for key in ["subject", "title", "body_html", "body_plain_text", "body_preview"]:
        value = message.get(key)
        if not value:
            continue
        if key == "body_html":
            primary_parts.append(sanitize_text(str(value)))
        else:
            primary_parts.append(str(value))
    supplemental = flatten_strings(
        {k: v for k, v in message.items() if k not in {"subject", "title", "body_html", "body_plain_text", "body_preview"}},
        limit=800,
    )
    joined = "\n".join(primary_parts + supplemental)
    return sanitize_text(joined)


def normalize_city(text_value: str) -> str:
    text_value = (text_value or "").strip()
    text_value = re.sub(r"^[：:\-\s]+|[：:;；,，。\s]+$", "", text_value)
    text_value = re.sub(r"\s{2,}", " ", text_value)
    replacements = {
        "中国": "",
        "中华人民共和国": "",
        "市辖区": "",
    }
    for old, new in replacements.items():
        text_value = text_value.replace(old, new)
    text_value = normalize_text(text_value)
    if not text_value:
        return ""

    location_aliases = {
        "上海虹桥": "上海",
        "上海浦东": "上海",
        "深圳北": "深圳",
        "深圳宝安": "深圳",
        "杭州东": "杭州",
        "南通西": "南通",
        "北京南": "北京",
        "北京首都": "北京",
        "北京大兴": "北京",
        "广州南": "广州",
        "广州白云": "广州",
        "成都东": "成都",
        "成都天府": "成都",
        "成都双流": "成都",
        "南京南": "南京",
        "南京禄口": "南京",
        "苏州北": "苏州",
        "香港西九龙": "香港",
    }
    for alias, city in location_aliases.items():
        if text_value == alias or text_value.startswith(alias + "机场") or text_value.startswith(alias + "站"):
            return city

    direct_cities = ["北京", "上海", "天津", "重庆", "香港", "澳门"]
    for city in direct_cities:
        if text_value.startswith(city):
            return city

    city_match = re.search(r"([\u4e00-\u9fa5A-Za-z]{2,20}?)(?:市|州|盟|地区)", text_value)
    if city_match:
        return city_match.group(1)

    text_value = re.sub(r"(?:国际|国内)?(?:机场|机场T\d|航站楼|火车站|高铁站|动车站)$", "", text_value)
    text_value = re.sub(r"(?:东站|西站|南站|北站)$", "", text_value)
    if text_value in location_aliases:
        return location_aliases[text_value]
    if len(text_value) >= 3 and text_value[-1] in {"东", "西", "南", "北"} and text_value[:-1] in {
        "深圳",
        "杭州",
        "南通",
        "苏州",
        "北京",
        "南京",
        "广州",
        "成都",
        "西安",
        "武汉",
        "长沙",
        "郑州",
        "济南",
        "青岛",
        "厦门",
        "福州",
        "宁波",
        "昆明",
    }:
        return text_value[:-1]
    return text_value.strip(" ,，")


def normalize_text(text_value: str) -> str:
    return re.sub(r"\s+", " ", (text_value or "").strip())


def uniq_preserve_order(items: Sequence[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in items:
        clean = normalize_text(str(item or ""))
        if not clean or clean in seen:
            continue
        seen.add(clean)
        ordered.append(clean)
    return ordered


def resolve_collection_mode(mode: str) -> str:
    mode = (mode or DEFAULT_COLLECTION_MODE).strip().lower()
    if mode not in COLLECTION_MODE_CHOICES:
        raise DashboardError(f"不支持的 mode：{mode}，可选值：{', '.join(COLLECTION_MODE_CHOICES)}")
    return mode


def resolve_query_terms(mode: str, queries: Optional[Sequence[str]]) -> List[str]:
    extras = [normalize_text(query) for query in (queries or []) if normalize_text(query)]
    if extras:
        return uniq_preserve_order(extras)
    if mode == "approval":
        return list(DEFAULT_APPROVAL_QUERY_TERMS)
    if mode == "booking":
        return list(DEFAULT_BOOKING_QUERY_TERMS)
    return uniq_preserve_order(list(DEFAULT_APPROVAL_QUERY_TERMS) + list(DEFAULT_BOOKING_QUERY_TERMS))


def extract_message_subject(message: Dict[str, Any]) -> str:
    return normalize_text(str(message.get("subject") or message.get("title") or ""))


def extract_message_sender(message: Dict[str, Any]) -> str:
    sender_fields = [
        message.get("from"),
        message.get("sender"),
        message.get("from_name"),
        message.get("from_address"),
        message.get("headers"),
    ]
    parts: List[str] = []
    for field in sender_fields:
        parts.extend(flatten_strings(field, limit=40))
    return normalize_text(" ".join(parts))


def infer_message_channel(message: Dict[str, Any], text: str) -> str:
    subject = extract_message_subject(message)
    sender = extract_message_sender(message)
    combined = f"{subject}\n{sender}\n{text}"
    if contains_any(combined, BOOKING_NOTIFICATION_KEYWORDS) and (
        "【差旅】" in subject or contains_any(subject, ["预订了", "Hi Travel", "机票", "火车票", "酒店"])
    ):
        return "booking"
    if contains_any(combined, APPROVAL_NOTIFICATION_KEYWORDS):
        return "approval"
    if "【差旅】" in subject and contains_any(subject, ["预订了", "机票", "火车票", "酒店"]):
        return "booking"
    return "approval"


def extract_all_time_values(text: str) -> List[str]:
    matches = re.findall(
        r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?(?:\s*\d{1,2}:\d{2}(?::\d{2})?)?|\d{1,2}月\d{1,2}日(?:\s*\d{1,2}:\d{2})?",
        text or "",
        flags=re.IGNORECASE,
    )
    values: List[str] = []
    for raw in matches:
        normalized = normalize_datetime_string(raw)
        if normalized and normalized not in values:
            values.append(normalized)
    return values


def extract_date_range_field(text: str, aliases: Sequence[str]) -> Tuple[Optional[str], Optional[str]]:
    for alias in aliases:
        match = re.search(rf"{re.escape(alias)}\s*[：:]\s*([^\n]+)", text, flags=re.IGNORECASE)
        if not match:
            continue
        values = extract_all_time_values(match.group(1))
        if len(values) >= 2:
            return values[0], values[1]
    return None, None


def extract_line_value(line: str, aliases: Sequence[str]) -> Optional[str]:
    for alias in aliases:
        match = re.search(rf"{re.escape(alias)}\s*[：:]\s*(.+)$", line, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def extract_route_pair(text: str) -> Optional[Tuple[str, str]]:
    patterns = [
        r"([\u4e00-\u9fa5A-Za-z]{2,20}(?:机场|火车站|高铁站|动车站|站|虹桥|浦东|宝安|禄口|白云|天府|双流|大兴|首都|北|南|东|西)?)\s*(?:→|->|—>|至|到|-)\s*([\u4e00-\u9fa5A-Za-z]{2,20}(?:机场|火车站|高铁站|动车站|站|虹桥|浦东|宝安|禄口|白云|天府|双流|大兴|首都|北|南|东|西)?)",
        r"(?:出发|始发|起飞|发车)\s*[:：]?\s*([\u4e00-\u9fa5A-Za-z]{2,20}(?:机场|火车站|高铁站|动车站|站|虹桥|浦东|宝安|禄口|白云|天府|双流|大兴|首都|北|南|东|西)?)\s*(?:前往|抵达|到达)\s*([\u4e00-\u9fa5A-Za-z]{2,20}(?:机场|火车站|高铁站|动车站|站|虹桥|浦东|宝安|禄口|白云|天府|双流|大兴|首都|北|南|东|西)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if not match:
            continue
        departure_city = normalize_city(match.group(1))
        destination_city = normalize_city(match.group(2))
        if departure_city and destination_city and departure_city != destination_city:
            return departure_city, destination_city
    return None


def extract_field_by_aliases(text: str, aliases: Sequence[str]) -> Optional[str]:
    for alias in aliases:
        pattern = rf"(?:^|\n|\|)\s*{re.escape(alias)}\s*[：:]\s*([^\n\|]+)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def find_candidate_name(text: str) -> Optional[str]:
    normalized = normalize_person_name(extract_field_by_aliases(text, FIELD_ALIASES["name"]) or "")
    if normalized:
        return normalized
    patterns = [
        r"(?:申请人|出差人|员工姓名|姓名|乘机人|乘车人|入住人)\s*[：:]\s*([\u4e00-\u9fa5·]{2,20})",
        r"【差旅】\s*([\u4e00-\u9fa5·]{2,20})\s*预订了",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            candidate = normalize_person_name(match.group(1))
            if candidate:
                return candidate
    return None


def extract_time_field(text: str, aliases: Sequence[str]) -> Optional[str]:
    raw = extract_field_by_aliases(text, aliases)
    if raw:
        normalized = normalize_datetime_string(raw)
        if normalized:
            return normalized
    for alias in aliases:
        pattern = rf"{re.escape(alias)}[^\n]*?(20\d{{2}}[-/.年]\d{{1,2}}[-/.月]\d{{1,2}}(?:日)?(?:\s+\d{{1,2}}:\d{{2}}(?::\d{{2}})?)?)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            normalized = normalize_datetime_string(match.group(1))
            if normalized:
                return normalized
    return None


def extract_amount_field(text: str, aliases: Sequence[str]) -> Optional[float]:
    raw = extract_field_by_aliases(text, aliases)
    if not raw:
        for alias in aliases:
            pattern = rf"{re.escape(alias)}[^\n]*?([¥￥$]?\s*[0-9][0-9,]*(?:\.\d+)?)"
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                raw = match.group(1)
                break
    if not raw:
        return None
    cleaned = raw.replace(",", "")
    numbers = re.findall(r"-?\d+(?:\.\d+)?", cleaned)
    if not numbers:
        return None
    try:
        return float(numbers[0])
    except ValueError:
        return None


def parse_bool_text(raw: Optional[str]) -> Optional[bool]:
    if raw is None:
        return None
    cleaned = normalize_text(raw).lower()
    if not cleaned:
        return None
    if cleaned in BOOL_TRUE_WORDS:
        return True
    if cleaned in BOOL_FALSE_WORDS:
        return False
    if any(word in cleaned for word in ["是", "已", "存在", "命中", "违规", "超标"]):
        return True
    if any(word in cleaned for word in ["否", "未", "无", "正常", "合规"]):
        return False
    return None


def contains_any(text: str, keywords: Sequence[str]) -> bool:
    lowered = (text or "").lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def truncate_reason(reason: str, limit: int = 60) -> str:
    clean = re.sub(r"\s+", " ", (reason or "").strip())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def compute_booking_lead_days(booking_time: Optional[str], departure_time: Optional[str]) -> Optional[float]:
    booking_dt = parse_dt_or_none(booking_time)
    departure_dt = parse_dt_or_none(departure_time)
    if not booking_dt or not departure_dt:
        return None
    delta_days = (departure_dt - booking_dt).total_seconds() / 86400
    return round(delta_days, 1)


def derive_booked_before_approval(booking_time: Optional[str], approval_time: Optional[str], text: str) -> Optional[bool]:
    explicit = contains_any(text, BOOKED_BEFORE_APPROVAL_KEYWORDS)
    if explicit:
        return True
    booking_dt = parse_dt_or_none(booking_time)
    approval_dt = parse_dt_or_none(approval_time)
    if booking_dt and approval_dt:
        return booking_dt < approval_dt
    return None


def derive_over_cabin_policy(cabin_class: str, seat_class: str, text: str) -> Optional[bool]:
    explicit = parse_bool_text(extract_field_by_aliases(text, ["是否超舱位标准", "是否超舱位", "超标舱位", "Cabin Policy Hit"]))
    if explicit is not None:
        return explicit
    joined = " ".join([cabin_class, seat_class, text])
    if contains_any(joined, CABIN_OVER_KEYWORDS):
        return True
    if cabin_class or seat_class:
        return False
    return None


def derive_hotel_over_policy(hotel_price_per_night: Optional[float], hotel_standard_amount: Optional[float], text: str) -> Optional[bool]:
    explicit = parse_bool_text(extract_field_by_aliases(text, ["是否超差标", "酒店是否超标", "Hotel Over Policy"]))
    if explicit is not None:
        return explicit
    if hotel_price_per_night is not None and hotel_standard_amount is not None:
        return hotel_price_per_night > hotel_standard_amount
    if contains_any(text, HOTEL_OVER_KEYWORDS):
        return True
    if hotel_price_per_night is not None or hotel_standard_amount is not None:
        return False
    return None


def derive_over_policy_reason(text: str, extracted_reason: str, is_over_cabin_policy: Optional[bool], is_hotel_over_policy: Optional[bool]) -> str:
    reason = truncate_reason(extracted_reason or "")
    if reason:
        return reason
    if not is_over_cabin_policy and not is_hotel_over_policy:
        return ""
    for label, keywords in OVER_POLICY_REASON_BUCKETS:
        if contains_any(text, keywords):
            return label
    return "待人工复核"


def extract_approval_record_from_message(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    text = extract_message_text(message)
    if not text:
        return None

    name = normalize_person_name(extract_field_by_aliases(text, FIELD_ALIASES["name"]) or find_candidate_name(text) or "")
    if not name:
        return None

    departure_city = normalize_city(extract_field_by_aliases(text, FIELD_ALIASES["departure_city"]) or "")
    destination_city = normalize_city(extract_field_by_aliases(text, FIELD_ALIASES["destination_city"]) or "")
    departure_time = extract_time_field(text, FIELD_ALIASES["departure_time"]) or ""
    return_time = extract_time_field(text, FIELD_ALIASES["return_time"]) or ""

    source_sent_at = (
        parse_sent_at(pick_first_present(message, ["date", "date_formatted", "sent_at", "timestamp", "internal_date", "create_time"]))
        or ""
    )
    booking_time = extract_time_field(text, FIELD_ALIASES["booking_time"])
    approval_time = extract_time_field(text, FIELD_ALIASES["approval_time"]) or source_sent_at or None
    cabin_class = normalize_text(extract_field_by_aliases(text, FIELD_ALIASES["cabin_class"]) or "")
    seat_class = normalize_text(extract_field_by_aliases(text, FIELD_ALIASES["seat_class"]) or "")
    hotel_price_per_night = extract_amount_field(text, FIELD_ALIASES["hotel_price_per_night"])
    hotel_standard_amount = extract_amount_field(text, FIELD_ALIASES["hotel_standard_amount"])
    hotel_total_amount = extract_amount_field(text, FIELD_ALIASES["hotel_total_amount"])

    duplicate_from_mail = parse_bool_text(extract_field_by_aliases(text, FIELD_ALIASES["duplicate_booking_flag"]))
    if duplicate_from_mail is None and contains_any(text, DUPLICATE_BOOKING_KEYWORDS):
        duplicate_from_mail = True

    is_booked_before_approval = derive_booked_before_approval(booking_time, approval_time, text)
    is_over_cabin_policy = derive_over_cabin_policy(cabin_class, seat_class, text)
    is_hotel_over_policy = derive_hotel_over_policy(hotel_price_per_night, hotel_standard_amount, text)
    over_policy_reason = derive_over_policy_reason(
        text,
        extract_field_by_aliases(text, FIELD_ALIASES["over_policy_reason"]) or "",
        is_over_cabin_policy,
        is_hotel_over_policy,
    )
    booking_lead_days = compute_booking_lead_days(booking_time, departure_time)
    source_message_id = str(message.get("message_id") or message.get("id") or "")

    record = {
        "name": name,
        "departure_city": departure_city,
        "destination_city": destination_city,
        "departure_time": departure_time,
        "return_time": return_time,
        "booking_time": booking_time or "",
        "approval_time": approval_time or "",
        "booking_lead_days": booking_lead_days,
        "is_booked_before_approval": is_booked_before_approval,
        "cabin_class": cabin_class,
        "seat_class": seat_class,
        "is_over_cabin_policy": is_over_cabin_policy,
        "hotel_price_per_night": hotel_price_per_night,
        "hotel_standard_amount": hotel_standard_amount,
        "hotel_total_amount": hotel_total_amount,
        "is_hotel_over_policy": is_hotel_over_policy,
        "over_policy_reason": over_policy_reason,
        "duplicate_booking_flag": bool(duplicate_from_mail) if duplicate_from_mail is not None else False,
        "is_first_time_destination": False,
        "source_channel": "approval",
        "booking_template_type": "approval",
        "source_message_id": source_message_id,
        "source_message_ids": [source_message_id] if source_message_id else [],
        "source_subject": extract_message_subject(message),
        "source_sent_at": source_sent_at,
        "raw_excerpt": text[:1200],
        "hotel_policy_decision_source": "mail_extract" if hotel_standard_amount is not None else "unknown",
        "policy_match_level": None,
        "policy_rule_id": "",
        "policy_currency": "",
        "hotel_policy_severity": "normal",
        "needs_review": False,
        "review_reason": "",
        **build_record_status("complete", travel_context_missing=False),
    }

    try:
        validate_required_fields(record)
    except DashboardError:
        return None
    return record


def extract_booking_name(subject: str, text: str) -> Optional[str]:
    match = re.search(r"【差旅】\s*([\u4e00-\u9fa5·]{2,20})\s*预订了", subject)
    if match:
        candidate = normalize_person_name(match.group(1))
        if candidate:
            return candidate
    name = find_candidate_name(subject)
    if name:
        return name
    return find_candidate_name(text)


def extract_booking_kind(subject: str, text: str) -> Optional[str]:
    combined = f"{subject}\n{text}"
    if "火车票" in combined:
        return "train"
    if "机票" in combined or "航班" in combined:
        return "flight"
    if "酒店" in combined:
        return "hotel"
    return None


def extract_transport_segments(text: str) -> List[Dict[str, str]]:
    departure_aliases = ["出发城市", "出发地", "始发地", "出发站", "始发站", "出发机场", "起飞机场"]
    destination_aliases = ["目的城市", "目的地", "到达城市", "到达站", "终到站", "到达机场", "降落机场"]
    route_aliases = ["航班信息", "车次信息", "去程航班", "回程航班", "去程车次", "回程车次"]
    departure_time_aliases = ["出发时间", "发车时间", "起飞时间", "乘车时间", "启程时间", "去程时间", "回程时间", "返程时间", "出发日期", "乘车日期"]
    lines = [normalize_text(line) for line in text.splitlines() if normalize_text(line)]
    segments: List[Dict[str, str]] = []
    current: Dict[str, str] = {}

    section_keywords = ["去程航班", "回程航班", "去程车次", "回程车次"]
    for idx, keyword in enumerate(section_keywords):
        start = text.find(keyword)
        if start < 0:
            continue
        next_positions = [text.find(other, start + len(keyword)) for other in section_keywords[idx + 1 :] if text.find(other, start + len(keyword)) >= 0]
        end = min(next_positions) if next_positions else min(len(text), start + 220)
        section_text = text[start:end]
        route = extract_route_pair(section_text)
        time_values = extract_all_time_values(section_text)
        if route and time_values:
            segments.append(
                {
                    "departure_city": route[0],
                    "destination_city": route[1],
                    "departure_time": time_values[0],
                }
            )

    for idx, line in enumerate(lines):
        departure_value = extract_line_value(line, departure_aliases)
        destination_value = extract_line_value(line, destination_aliases)
        route_value = extract_line_value(line, route_aliases)
        if departure_value:
            current["departure_city"] = normalize_city(departure_value)
        if destination_value:
            current["destination_city"] = normalize_city(destination_value)
        route = extract_route_pair(route_value or line)
        if route:
            current["departure_city"], current["destination_city"] = route
        time_value = extract_time_field(line, departure_time_aliases)
        if not time_value and route_value:
            nearby = "\n".join(lines[idx : idx + 3])
            time_candidates = extract_all_time_values(nearby)
            time_value = time_candidates[0] if time_candidates else ""
        elif not time_value:
            nearby = "\n".join(lines[idx : idx + 2])
            time_candidates = extract_all_time_values(nearby)
            time_value = time_candidates[0] if time_candidates else ""
        if time_value:
            current["departure_time"] = time_value
        if current.get("departure_city") and current.get("destination_city") and current.get("departure_time"):
            segments.append(
                {
                    "departure_city": current["departure_city"],
                    "destination_city": current["destination_city"],
                    "departure_time": current["departure_time"],
                }
            )
            current = {}

    if not segments:
        route = extract_route_pair(text)
        time_values = extract_all_time_values(text)
        if route and time_values:
            segments.append(
                {
                    "departure_city": route[0],
                    "destination_city": route[1],
                    "departure_time": time_values[0],
                }
            )

    dedup: Dict[Tuple[str, str, str], Dict[str, str]] = {}
    for item in segments:
        key = (item["departure_city"], item["destination_city"], item["departure_time"])
        if all(key):
            dedup[key] = item
    return sorted(dedup.values(), key=lambda item: item["departure_time"])


def build_booking_transport_candidates(message: Dict[str, Any], *, text: str, name: str, booking_kind: str) -> List[Dict[str, Any]]:
    segments = extract_transport_segments(text)
    if not segments:
        return []

    source_message_id = str(message.get("message_id") or message.get("id") or "")
    source_sent_at = (
        parse_sent_at(pick_first_present(message, ["date", "date_formatted", "sent_at", "timestamp", "internal_date", "create_time"]))
        or ""
    )
    cabin_class = normalize_text(extract_field_by_aliases(text, FIELD_ALIASES["cabin_class"]) or "")
    seat_class = normalize_text(extract_field_by_aliases(text, FIELD_ALIASES["seat_class"]) or "")
    candidates: List[Dict[str, Any]] = []
    for segment in segments:
        candidates.append(
            {
                "name": name,
                "departure_city": segment["departure_city"],
                "destination_city": segment["destination_city"],
                "departure_time": segment["departure_time"],
                "return_time": "",
                "booking_time": source_sent_at,
                "approval_time": "",
                "booking_lead_days": None,
                "is_booked_before_approval": None,
                "cabin_class": cabin_class,
                "seat_class": seat_class,
                "is_over_cabin_policy": None,
                "hotel_price_per_night": None,
                "hotel_standard_amount": None,
                "hotel_total_amount": None,
                "is_hotel_over_policy": None,
                "over_policy_reason": "",
                "duplicate_booking_flag": False,
                "is_first_time_destination": False,
                "source_channel": "booking",
                "booking_template_type": booking_kind,
                "source_message_id": source_message_id,
                "source_message_ids": [source_message_id] if source_message_id else [],
                "source_subject": extract_message_subject(message),
                "source_sent_at": source_sent_at,
                "raw_excerpt": text[:1200],
                "hotel_policy_decision_source": "unknown",
                "policy_match_level": None,
                "policy_rule_id": "",
                "policy_currency": "",
                "hotel_policy_severity": "normal",
                "needs_review": False,
                **build_record_status("complete", travel_context_missing=False),
                "_booking_record_kind": "transport",
            }
        )
    return candidates


def extract_hotel_city(text: str) -> str:
    city = normalize_city(
        extract_field_by_aliases(text, ["酒店城市", "入住城市", "目的地", "酒店地址", "酒店名称", "入住酒店"]) or ""
    )
    if city:
        return city
    match = re.search(r"([北京上海天津重庆香港澳门]|[\u4e00-\u9fa5]{2,20}?)(?:市|区|县).{0,8}酒店", text)
    if match:
        return normalize_city(match.group(1))
    return ""


def build_booking_hotel_candidate(message: Dict[str, Any], *, text: str, name: str) -> Optional[Dict[str, Any]]:
    destination_city = extract_hotel_city(text)
    range_start, range_end = extract_date_range_field(text, ["入离店日期", "入住离店日期", "入住/离店", "Stay", "Check-in / Check-out"])
    checkin_time = extract_time_field(text, ["入住时间", "入住日期", "Check-in", "入住"]) or range_start or ""
    checkout_time = extract_time_field(text, ["离店时间", "离店日期", "退房时间", "Check-out", "离店"]) or range_end or ""
    source_message_id = str(message.get("message_id") or message.get("id") or "")
    source_sent_at = (
        parse_sent_at(pick_first_present(message, ["date", "date_formatted", "sent_at", "timestamp", "internal_date", "create_time"]))
        or ""
    )
    hotel_price_per_night = extract_amount_field(text, FIELD_ALIASES["hotel_price_per_night"])
    hotel_standard_amount = extract_amount_field(text, FIELD_ALIASES["hotel_standard_amount"])
    hotel_total_amount = extract_amount_field(text, FIELD_ALIASES["hotel_total_amount"])
    if not any([destination_city, checkin_time, checkout_time, hotel_price_per_night, hotel_total_amount]):
        return None
    return {
        "name": name,
        "departure_city": "",
        "destination_city": destination_city,
        "departure_time": checkin_time,
        "return_time": checkout_time,
        "booking_time": source_sent_at,
        "approval_time": "",
        "booking_lead_days": None,
        "is_booked_before_approval": None,
        "cabin_class": "",
        "seat_class": "",
        "is_over_cabin_policy": None,
        "hotel_price_per_night": hotel_price_per_night,
        "hotel_standard_amount": hotel_standard_amount,
        "hotel_total_amount": hotel_total_amount,
        "is_hotel_over_policy": None,
        "over_policy_reason": "",
        "duplicate_booking_flag": False,
        "is_first_time_destination": False,
        "source_channel": "booking",
        "booking_template_type": "hotel",
        "source_message_id": source_message_id,
        "source_message_ids": [source_message_id] if source_message_id else [],
        "source_subject": extract_message_subject(message),
        "source_sent_at": source_sent_at,
        "raw_excerpt": text[:1200],
        "hotel_policy_decision_source": "unknown",
        "policy_match_level": None,
        "policy_rule_id": "",
        "policy_currency": "",
        "hotel_policy_severity": "normal",
        "needs_review": False,
        "review_reason": "",
        **build_record_status("partial", travel_context_missing=True),
        "_booking_record_kind": "hotel",
    }


def extract_booking_records_from_message(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    text = extract_message_text(message)
    if not text:
        return []
    subject = extract_message_subject(message)
    name = extract_booking_name(subject, text)
    if not name:
        return []
    booking_kind = extract_booking_kind(subject, text)
    if booking_kind in {"train", "flight"}:
        return build_booking_transport_candidates(message, text=text, name=name, booking_kind=booking_kind)
    if booking_kind == "hotel":
        hotel_candidate = build_booking_hotel_candidate(message, text=text, name=name)
        return [hotel_candidate] if hotel_candidate else []
    return []


def combine_string_values(*values: Any, sep: str = " / ") -> str:
    parts = []
    for value in values:
        if isinstance(value, list):
            parts.extend(str(item) for item in value if str(item or "").strip())
        elif str(value or "").strip():
            parts.append(str(value).strip())
    return sep.join(uniq_preserve_order(parts))


def pick_earliest_time(*values: Optional[str]) -> str:
    timestamps = [parse_dt_or_none(value) for value in values if parse_dt_or_none(value)]
    if not timestamps:
        return ""
    return min(timestamps).strftime("%Y-%m-%d")


def pick_latest_time(*values: Optional[str]) -> str:
    timestamps = [parse_dt_or_none(value) for value in values if parse_dt_or_none(value)]
    if not timestamps:
        return ""
    return max(timestamps).strftime("%Y-%m-%d")


def compute_trip_window(record: Dict[str, Any]) -> Tuple[str, str]:
    start = pick_earliest_time(
        record.get("timeline_start"),
        record.get("departure_time"),
        record.get("_hotel_checkin_time"),
    )
    end = pick_latest_time(
        record.get("timeline_end"),
        record.get("return_time"),
        record.get("_hotel_checkout_time"),
        record.get("departure_time"),
        record.get("_hotel_checkin_time"),
    )
    if not start and end:
        start = end
    if not end and start:
        end = start
    return start, end


def trip_contains_weekend(record: Dict[str, Any]) -> bool:
    start_dt = parse_dt_or_none(record.get("timeline_start") or record.get("departure_time"))
    explicit_end_dt = parse_dt_or_none(
        record.get("return_time")
        or record.get("_hotel_checkout_time")
        or record.get("_hotel_checkin_time")
    )
    end_dt = explicit_end_dt or start_dt
    if not start_dt and not end_dt:
        return False
    if not start_dt:
        start_dt = end_dt
    if not end_dt:
        end_dt = start_dt
    if not start_dt or not end_dt:
        return False
    if end_dt < start_dt:
        start_dt, end_dt = end_dt, start_dt
    current = start_dt.date()
    end_date = end_dt.date()
    while current <= end_date:
        if current.weekday() >= 5:
            return True
        current += dt.timedelta(days=1)
    return False


def merge_nullable_bool(*values: Optional[bool]) -> Optional[bool]:
    known = [value for value in values if value is not None]
    if not known:
        return None
    if any(value is True for value in known):
        return True
    return False


def merge_transport_pair(first: Dict[str, Any], second: Dict[str, Any]) -> Dict[str, Any]:
    first_dt = parse_dt_or_none(first.get("departure_time"))
    second_dt = parse_dt_or_none(second.get("departure_time"))
    if second_dt and first_dt and second_dt < first_dt:
        first, second = second, first
    merged = dict(first)
    merged["return_time"] = second.get("departure_time") or merged.get("return_time") or ""
    merged["approval_time"] = ""
    merged["booking_time"] = pick_earliest_time(first.get("booking_time"), second.get("booking_time"))
    merged["cabin_class"] = combine_string_values(first.get("cabin_class"), second.get("cabin_class"))
    merged["seat_class"] = combine_string_values(first.get("seat_class"), second.get("seat_class"))
    merged["source_message_id"] = first.get("source_message_id") or second.get("source_message_id") or ""
    merged["source_message_ids"] = uniq_preserve_order(
        list(first.get("source_message_ids") or []) + list(second.get("source_message_ids") or [])
    )
    merged["source_subject"] = combine_string_values(first.get("source_subject"), second.get("source_subject"), sep=" | ")
    merged["source_sent_at"] = pick_earliest_time(first.get("source_sent_at"), second.get("source_sent_at"))
    merged["raw_excerpt"] = combine_string_values(first.get("raw_excerpt"), second.get("raw_excerpt"), sep="\n---\n")[:1200]
    merged["is_over_cabin_policy"] = merge_nullable_bool(
        first.get("is_over_cabin_policy"), second.get("is_over_cabin_policy")
    )
    merged["timeline_start"], merged["timeline_end"] = compute_trip_window(merged)
    return merged


def pair_reverse_transport_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sorted_records = sorted(records, key=lambda item: item.get("departure_time") or item.get("source_sent_at") or "")
    used = set()
    results: List[Dict[str, Any]] = []
    for idx, record in enumerate(sorted_records):
        if idx in used:
            continue
        if record.get("return_time"):
            results.append(record)
            used.add(idx)
            continue
        current_dt = parse_dt_or_none(record.get("departure_time"))
        match_idx = None
        for j in range(idx + 1, len(sorted_records)):
            if j in used:
                continue
            other = sorted_records[j]
            if other.get("name") != record.get("name"):
                continue
            if other.get("departure_city") != record.get("destination_city"):
                continue
            if other.get("destination_city") != record.get("departure_city"):
                continue
            other_dt = parse_dt_or_none(other.get("departure_time"))
            if not current_dt or not other_dt:
                continue
            if other_dt <= current_dt:
                continue
            if (other_dt - current_dt).days > 1:
                continue
            match_idx = j
            break
        if match_idx is not None:
            results.append(merge_transport_pair(record, sorted_records[match_idx]))
            used.add(idx)
            used.add(match_idx)
        else:
            results.append(record)
            used.add(idx)
    return results


def enrich_transport_records_with_hotels(
    transport_records: List[Dict[str, Any]], hotel_records: List[Dict[str, Any]], *, audit: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    for hotel in hotel_records:
        hotel_start = parse_dt_or_none(hotel.get("departure_time"))
        hotel_end = parse_dt_or_none(hotel.get("return_time"))
        best_idx = None
        best_score: Optional[float] = None
        for idx, trip in enumerate(transport_records):
            if trip.get("name") != hotel.get("name"):
                continue
            if normalize_city(trip.get("destination_city") or "") != normalize_city(hotel.get("destination_city") or ""):
                continue
            trip_start = parse_dt_or_none(trip.get("departure_time"))
            trip_end = parse_dt_or_none(trip.get("return_time"))
            effective_trip_end = trip_end or trip_start
            if hotel_start and trip_start:
                score = abs((hotel_start - trip_start).total_seconds())
            elif hotel_end and effective_trip_end:
                score = abs((hotel_end - effective_trip_end).total_seconds())
            else:
                score = float("inf")
            if not hotel_start or not trip_start or not effective_trip_end:
                continue
            if hotel_start < trip_start:
                continue
            if hotel_start > effective_trip_end:
                continue
            if best_score is None or score < best_score:
                best_idx = idx
                best_score = score
        if best_idx is None or best_score is None or best_score == float("inf") or best_score > 14 * 86400:
            if audit is not None:
                audit["hotel_without_transport_match"] = int(audit.get("hotel_without_transport_match") or 0) + 1
            continue
        trip = transport_records[best_idx]
        trip["hotel_price_per_night"] = trip.get("hotel_price_per_night")
        if trip["hotel_price_per_night"] is None:
            trip["hotel_price_per_night"] = hotel.get("hotel_price_per_night")
        if trip.get("hotel_standard_amount") is None:
            trip["hotel_standard_amount"] = hotel.get("hotel_standard_amount")
        if trip.get("hotel_total_amount") is None:
            trip["hotel_total_amount"] = hotel.get("hotel_total_amount")
        trip["source_message_ids"] = uniq_preserve_order(
            list(trip.get("source_message_ids") or []) + list(hotel.get("source_message_ids") or [])
        )
        trip["source_subject"] = combine_string_values(trip.get("source_subject"), hotel.get("source_subject"), sep=" | ")
        trip["raw_excerpt"] = combine_string_values(trip.get("raw_excerpt"), hotel.get("raw_excerpt"), sep="\n---\n")[:1200]
        trip["booking_template_type"] = combine_string_values(trip.get("booking_template_type"), "hotel")
        trip["_hotel_checkin_time"] = hotel.get("departure_time") or trip.get("_hotel_checkin_time") or ""
        trip["_hotel_checkout_time"] = hotel.get("return_time") or trip.get("_hotel_checkout_time") or ""
        if not trip.get("return_time") and hotel.get("return_time"):
            trip["return_time"] = hotel.get("return_time") or ""
        trip["timeline_start"], trip["timeline_end"] = compute_trip_window(trip)
        trip["travel_context_missing"] = False
        hotel["_matched_to_transport"] = True
        if audit is not None:
            audit["hotel_enriched_to_transport"] = int(audit.get("hotel_enriched_to_transport") or 0) + 1
    return transport_records


def build_standalone_hotel_trip(hotel: Dict[str, Any]) -> Dict[str, Any]:
    partial = dict(hotel)
    partial.pop("_booking_record_kind", None)
    partial["departure_city"] = partial.get("departure_city") or partial.get("destination_city") or "酒店待补全"
    partial["timeline_start"], partial["timeline_end"] = compute_trip_window(partial)
    partial.update(build_record_status("partial", travel_context_missing=True))
    partial["booking_template_type"] = combine_string_values(partial.get("booking_template_type"), "hotel_only")
    partial["needs_review"] = True
    return partial


def finalize_booking_records(
    records: List[Dict[str, Any]], *, hotel_policy_rules: Optional[Sequence[Dict[str, Any]]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    hotel_policy_rules = list(hotel_policy_rules or [])
    audit = build_default_booking_audit()
    transport_records = [item for item in records if item.get("_booking_record_kind") == "transport"]
    hotel_records = [item for item in records if item.get("_booking_record_kind") == "hotel"]
    audit["hotel_candidates"] = len(hotel_records)
    paired_records = pair_reverse_transport_records(transport_records)
    paired_records = enrich_transport_records_with_hotels(paired_records, hotel_records, audit=audit)
    finalized: List[Dict[str, Any]] = []
    for item in paired_records:
        item = dict(item)
        item.pop("_booking_record_kind", None)
        item.update(build_record_status("complete", travel_context_missing=bool(item.get("travel_context_missing"))))
        item["booking_lead_days"] = compute_booking_lead_days(item.get("booking_time"), item.get("departure_time"))
        item["is_booked_before_approval"] = derive_booked_before_approval(
            item.get("booking_time"), item.get("approval_time"), item.get("raw_excerpt") or ""
        )
        item["is_over_cabin_policy"] = derive_over_cabin_policy(
            item.get("cabin_class") or "", item.get("seat_class") or "", item.get("raw_excerpt") or ""
        )
        item = apply_hotel_policy_fields(item, hotel_policy_rules)
        try:
            validate_required_fields(item, require_return_time=False)
        except DashboardError:
            register_booking_discard(audit, "invalid_transport_record")
            continue
        finalized.append(item)

    for hotel in hotel_records:
        if hotel.get("_matched_to_transport"):
            continue
        partial = build_standalone_hotel_trip(hotel)
        partial = apply_hotel_policy_fields(partial, hotel_policy_rules)
        try:
            validate_required_fields(partial, require_return_time=False)
        except DashboardError:
            register_booking_discard(audit, "invalid_hotel_partial_record")
            continue
        finalized.append(partial)
        audit["hotel_partial_candidate_retained"] = int(audit.get("hotel_partial_candidate_retained") or 0) + 1
    return finalized, audit


def extract_records_from_message(message: Dict[str, Any], *, allowed_mode: str) -> List[Dict[str, Any]]:
    text = extract_message_text(message)
    if not text:
        return []
    channel = infer_message_channel(message, text)
    if allowed_mode == "approval" and channel != "approval":
        return []
    if allowed_mode == "booking" and channel != "booking":
        return []
    if channel == "booking":
        return extract_booking_records_from_message(message)
    approval_record = extract_approval_record_from_message(message)
    return [approval_record] if approval_record else []


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return copy.deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def alert_route(row: Dict[str, Any]) -> str:
    return f"{row.get('departure_city') or '--'} → {row.get('destination_city') or '--'}"


def alert_trip_date(row: Dict[str, Any]) -> str:
    return str(row.get("timeline_start") or row.get("departure_time") or row.get("source_sent_at") or "")[:10]


def alert_date_range(row: Dict[str, Any]) -> str:
    start = alert_trip_date(row)
    end = str(row.get("timeline_end") or row.get("return_time") or row.get("departure_time") or start or "")[:10]
    if not start:
        return end
    if not end or end == start:
        return start
    return f"{start}~{end}"


def build_alert_key(*, person: str, rule_type: str, date_range: str) -> str:
    return "_".join(normalize_text(str(item)) or "NA" for item in [person, rule_type, date_range])


def build_alert_id(*, person: str, route: str, trip_date: str, rule_type: str, date_range: str = "") -> str:
    stable_range = date_range or trip_date
    return build_alert_key(person=person, rule_type=rule_type, date_range=stable_range)


def normalize_alert_key(alert: Dict[str, Any]) -> str:
    person = normalize_text(str(alert.get("person") or "")) or "--"
    rule_type = normalize_text(str(alert.get("rule_type") or "")) or "--"
    date_range = normalize_text(str(alert.get("date_range") or alert.get("date") or "")) or "--"
    return build_alert_key(person=person, rule_type=rule_type, date_range=date_range)


def build_compliance_alert_details(records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rule_specs = [
        ("周末差旅", lambda row: row.get("contains_weekend") is True),
        ("未批先订", lambda row: row.get("is_booked_before_approval") is True),
        ("交通超标", lambda row: row.get("is_over_cabin_policy") is True),
        ("酒店超标", lambda row: row.get("is_hotel_over_policy") is True),
        ("重复预订", lambda row: row.get("duplicate_booking_flag") is True),
    ]
    alerts: List[Dict[str, Any]] = []
    seen: set[str] = set()
    sorted_records = sorted(
        [dict(row) for row in records],
        key=lambda row: (str(row.get("name") or ""), alert_trip_date(row), alert_route(row)),
    )
    for row in sorted_records:
        person = normalize_text(str(row.get("name") or "")) or "--"
        route = alert_route(row)
        trip_date = alert_trip_date(row)
        date_range = alert_date_range(row)
        for rule_type, predicate in rule_specs:
            if not predicate(row):
                continue
            alert_id = build_alert_id(person=person, route=route, trip_date=trip_date, rule_type=rule_type, date_range=date_range)
            if alert_id in seen:
                continue
            seen.add(alert_id)
            alerts.append(
                {
                    "alert_id": alert_id,
                    "alert_key": alert_id,
                    "person": person,
                    "route": route,
                    "date": trip_date,
                    "date_range": date_range,
                    "rule_type": rule_type,
                    "trip_id": row.get("trip_id") or "",
                    "is_new": False,
                }
            )
    return alerts


def compliance_alerts_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    compliance = payload.get("compliance") if isinstance(payload, dict) else {}
    alerts = compliance.get("alerts") if isinstance(compliance, dict) else None
    if isinstance(alerts, list):
        return [dict(item) for item in alerts if isinstance(item, dict)]
    trips = payload.get("trips") if isinstance(payload, dict) else []
    return build_compliance_alert_details(trips if isinstance(trips, list) else [])


def compute_daily_alert_diff(today_payload: Dict[str, Any], yesterday_payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    today_alerts = compliance_alerts_from_payload(today_payload)
    if not yesterday_payload:
        return {
            "status": "no_baseline",
            "message": "首次运行，暂无历史对比 📊",
            "count": 0,
            "alerts": [],
        }
    yesterday_keys = {normalize_alert_key(item) for item in compliance_alerts_from_payload(yesterday_payload)}
    new_alerts = []
    for item in today_alerts:
        item["is_new"] = normalize_alert_key(item) not in yesterday_keys
        if item["is_new"]:
            new_alerts.append(item)
    return {
        "status": "ok",
        "message": "今日无新增预警 ✅" if not new_alerts else f"今日新增 {len(new_alerts)} 条预警",
        "count": len(new_alerts),
        "alerts": new_alerts,
        "all_alerts": today_alerts,
    }


def enrich_daily_alert_diff(payload: Dict[str, Any], *, snapshot_dir: Path) -> Dict[str, Any]:
    generated_at = str(payload.get("generated_at") or dt.datetime.now().strftime("%Y-%m-%d"))[:10]
    current_date = dt.datetime.strptime(generated_at, "%Y-%m-%d")
    yesterday = (current_date - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_path = snapshot_dir / f"{yesterday}.json"
    yesterday_payload = load_json(yesterday_path, default=None) if yesterday_path.exists() else None
    enriched = dict(payload)
    compliance = dict(enriched.get("compliance") or {})
    compliance["alerts"] = build_compliance_alert_details(enriched.get("trips") or [])
    compliance["daily_new_alerts"] = compute_daily_alert_diff({**enriched, "compliance": compliance}, yesterday_payload)
    marked_alerts = compliance["daily_new_alerts"].pop("all_alerts", None)
    if isinstance(marked_alerts, list):
        compliance["alerts"] = marked_alerts
    enriched["compliance"] = compliance
    summary = dict(enriched.get("summary") or {})
    summary["daily_new_alerts"] = compliance["daily_new_alerts"]["count"]
    enriched["summary"] = summary
    enriched["snapshot"] = {
        "snapshot_date": generated_at,
        "snapshot_path": str(snapshot_dir / f"{generated_at}.json"),
        "baseline_date": yesterday,
        "baseline_path": str(yesterday_path) if yesterday_path.exists() else "",
    }
    return enriched


def persist_daily_snapshot(payload: Dict[str, Any], *, snapshot_dir: Path) -> Path:
    snapshot_date = str(payload.get("generated_at") or dt.datetime.now().strftime("%Y-%m-%d"))[:10]
    snapshot_path = snapshot_dir / f"{snapshot_date}.json"
    save_json(snapshot_path, payload)
    return snapshot_path


def load_city_alias_cache(path: Path) -> Dict[str, Any]:
    payload = load_json(path, default={})
    merged: Dict[str, Any] = copy.deepcopy(DEFAULT_CITY_ALIAS_SEEDS)
    if isinstance(payload, dict):
        for raw_key, value in payload.items():
            key = normalize_city(str(raw_key or ""))
            if not key:
                continue
            if isinstance(value, dict):
                city = normalize_city(str(value.get("city") or ""))
                confidence = int(value.get("confidence") or 0)
                source = str(value.get("source") or "cache")
            else:
                city = normalize_city(str(value or ""))
                confidence = 100 if city else 0
                source = "legacy-cache"
            if city:
                merged[key] = {"city": city, "confidence": confidence or 100, "source": source}
    return merged


def save_city_alias_cache(path: Path, cache: Dict[str, Any]) -> None:
    ordered = dict(sorted(cache.items(), key=lambda item: item[0]))
    save_json(path, ordered)


def amap_geocode_city_alias(raw_city: str) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("AMAP_MAP_KEY") or os.getenv("AMAP_KEY") or os.getenv("GAODE_MAP_KEY") or os.getenv("GAODE_KEY")
    if not api_key:
        return None
    url = (
        "https://restapi.amap.com/v3/geocode/geo?address="
        + quote_plus(raw_city)
        + "&key="
        + quote_plus(api_key)
    )
    request = Request(url, headers={"User-Agent": "AimeTeamTravelDashboard/3.0"})
    with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    geocodes = payload.get("geocodes") or []
    if not geocodes:
        return None
    top = geocodes[0]
    address_component = top.get("addressComponent") or {}
    city_value = address_component.get("city") or top.get("city") or address_component.get("province") or ""
    city = normalize_city(city_value if isinstance(city_value, str) else "".join(city_value or []))
    if not city:
        return None
    confidence = 90 if address_component.get("city") or top.get("city") else 70
    return {
        "city": city,
        "confidence": confidence,
        "source": "amap",
        "display_name": top.get("formatted_address") or raw_city,
    }


def baidu_geocode_city_alias(raw_city: str) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("BAIDU_MAP_KEY") or os.getenv("BAIDU_KEY")
    if not api_key:
        return None
    url = (
        "https://api.map.baidu.com/geocoding/v3/?address="
        + quote_plus(raw_city)
        + "&output=json&ret_coordtype=gcj02ll&ak="
        + quote_plus(api_key)
    )
    request = Request(url, headers={"User-Agent": "AimeTeamTravelDashboard/3.0"})
    with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    result = payload.get("result") or {}
    address_component = result.get("addressComponent") or {}
    city = normalize_city(address_component.get("city") or "")
    if not city:
        return None
    confidence = int(result.get("confidence") or 0)
    return {
        "city": city,
        "confidence": confidence,
        "source": "baidu",
        "display_name": result.get("formatted_address") or raw_city,
    }


def resolve_city_alias_via_api(raw_city: str) -> Optional[Dict[str, Any]]:
    normalized = normalize_city(raw_city)
    if not normalized:
        return None
    for provider in DEFAULT_GEOCODE_ALIAS_PROVIDER_ORDER:
        try:
            if provider == "amap":
                resolved = amap_geocode_city_alias(normalized)
            elif provider == "baidu":
                resolved = baidu_geocode_city_alias(normalized)
            else:
                resolved = None
        except Exception:
            resolved = None
        if resolved:
            return resolved
    return None


def normalize_city_with_alias(raw_city: str, *, alias_cache: Dict[str, Any]) -> str:
    normalized = normalize_city(raw_city)
    if not normalized:
        return ""
    cached = alias_cache.get(normalized)
    if isinstance(cached, dict):
        cached_city = normalize_city(str(cached.get("city") or ""))
        if cached_city:
            return cached_city
    resolved = resolve_city_alias_via_api(normalized)
    if not resolved:
        return normalized
    city = normalize_city(str(resolved.get("city") or ""))
    confidence = int(resolved.get("confidence") or 0)
    if not city or confidence < DEFAULT_CITY_ALIAS_CONFIDENCE_THRESHOLD:
        return normalized
    alias_cache[normalized] = {
        "city": city,
        "confidence": confidence,
        "source": str(resolved.get("source") or "api"),
        "display_name": str(resolved.get("display_name") or normalized),
    }
    return city


def apply_city_aliases(records: List[Dict[str, Any]], *, cache_path: Path) -> List[Dict[str, Any]]:
    alias_cache = load_city_alias_cache(cache_path)
    normalized_records: List[Dict[str, Any]] = []
    for record in records:
        item = dict(record)
        item["departure_city"] = normalize_city_with_alias(item.get("departure_city") or "", alias_cache=alias_cache)
        item["destination_city"] = normalize_city_with_alias(item.get("destination_city") or "", alias_cache=alias_cache)
        normalized_records.append(item)
    save_city_alias_cache(cache_path, alias_cache)
    return normalized_records


def geocode_city(city: str, *, cache: Dict[str, Any], role: str) -> Optional[Dict[str, Any]]:
    city = normalize_city(city)
    if not city:
        return None
    cache_key = f"{role}::{city}"
    if cache_key in cache:
        return cache[cache_key]

    query = city
    country_hint = DEFAULT_COUNTRY_HINTS.get(role, "")
    if country_hint and country_hint.lower() not in city.lower():
        query = f"{city}, {country_hint}"

    url = (
        "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&addressdetails=1&q="
        + quote_plus(query)
    )
    request = Request(
        url,
        headers={
            "User-Agent": "AimeTeamTravelDashboard/2.0",
            "Accept-Language": "zh-CN,en-US;q=0.9,en;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: PERF203
        cache[cache_key] = None
        raise DashboardError(f"经纬度解析失败：{city} | {exc}") from exc

    if not payload:
        cache[cache_key] = None
        return None

    top = payload[0]
    resolved = {
        "query": query,
        "city": city,
        "lat": float(top["lat"]),
        "lon": float(top["lon"]),
        "display_name": top.get("display_name", city),
        "geocoder": DEFAULT_GEOCODER,
    }
    cache[cache_key] = resolved
    time.sleep(DEFAULT_GEOCODE_SLEEP_SECONDS)
    return resolved


def enrich_with_coordinates(records: List[Dict[str, Any]], *, cache_path: Path) -> List[Dict[str, Any]]:
    cache = load_json(cache_path, default={})
    enriched: List[Dict[str, Any]] = []
    for record in records:
        item = dict(record)
        item["departure_coord"] = geocode_city(item["departure_city"], cache=cache, role="departure")
        item["destination_coord"] = geocode_city(item["destination_city"], cache=cache, role="destination")
        enriched.append(item)
    save_json(cache_path, cache)
    return enriched


def format_review_amount(value: Any) -> str:
    if value in (None, ""):
        return "未知金额"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return normalize_text(str(value)) or "未知金额"
    formatted = f"{amount:.2f}".rstrip("0").rstrip(".")
    return f"¥{formatted}"


def is_partial_hotel_record(item: Dict[str, Any]) -> bool:
    if normalize_text(item.get("record_status") or "").lower() != "partial":
        return False
    template_type = normalize_text(item.get("booking_template_type") or "").lower()
    if "hotel" in template_type:
        return True
    return any(item.get(field) not in (None, "") for field in ["hotel_price_per_night", "hotel_total_amount", "hotel_standard_amount"])


def build_partial_hotel_duplicate_review_reason(items: Sequence[Dict[str, Any]]) -> str:
    amounts = [format_review_amount(item.get("hotel_total_amount") or item.get("hotel_price_per_night")) for item in items]
    return (
        f"同一人/同一入住窗存在多封酒店预订邮件（共{len(items)}封），金额分别为{'/'.join(amounts)}，"
        "订单号均未解析，无法排除重复预订，需商旅后台人工核查。"
    )


def annotate_partial_hotel_duplicate_group(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not items:
        return []
    review_reason = build_partial_hotel_duplicate_review_reason(items)
    try:
        ranked = sorted(
            items,
            key=lambda item: (
                float(item.get("hotel_total_amount") or item.get("hotel_price_per_night") or 0),
                item.get("source_sent_at") or "",
                item.get("source_message_id") or "",
            ),
            reverse=True,
        )
    except (TypeError, ValueError):
        ranked = list(items)
    annotated: List[Dict[str, Any]] = []
    for index, item in enumerate(ranked, start=1):
        enriched = dict(item)
        enriched["duplicate_booking_flag"] = True
        enriched["needs_review"] = True
        enriched["review_reason"] = review_reason
        enriched["duplicate_candidate_rank"] = index
        enriched["duplicate_candidate_count"] = len(ranked)
        annotated.append(enriched)
    return annotated


def deduplicate_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, str, str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for item in records:
        key = (
            item["name"],
            item["departure_city"],
            item["destination_city"],
            item["departure_time"],
            item["return_time"],
        )
        grouped[key].append(item)

    deduped: List[Dict[str, Any]] = []
    for items in grouped.values():
        if len(items) > 1 and all(is_partial_hotel_record(item) for item in items):
            deduped.extend(annotate_partial_hotel_duplicate_group(items))
            continue
        deduped.append(items[-1])

    return sorted(deduped, key=lambda x: ((x.get("departure_time") or ""), x["name"], x["destination_city"], x.get("source_message_id") or ""))


def mark_duplicate_bookings(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, str], List[Tuple[int, Dict[str, Any]]]] = defaultdict(list)
    for idx, item in enumerate(records):
        grouped[(item["name"], item["destination_city"])].append((idx, item))

    for group in grouped.values():
        group.sort(key=lambda pair: pair[1].get("departure_time") or "")
        for i in range(len(group)):
            idx_i, item_i = group[i]
            start_i = parse_dt_or_none(item_i.get("departure_time"))
            end_i = parse_dt_or_none(item_i.get("return_time"))
            if item_i.get("duplicate_booking_flag"):
                records[idx_i]["duplicate_booking_flag"] = True
                continue
            for j in range(i + 1, len(group)):
                idx_j, item_j = group[j]
                start_j = parse_dt_or_none(item_j.get("departure_time"))
                end_j = parse_dt_or_none(item_j.get("return_time"))
                if not start_i or not start_j or not end_i or not end_j:
                    continue
                overlaps = max(start_i, start_j) < min(end_i, end_j)
                if overlaps:
                    records[idx_i]["duplicate_booking_flag"] = True
                    records[idx_j]["duplicate_booking_flag"] = True
    return records


def apply_first_time_destination_flags(records: List[Dict[str, Any]], *, footprint_path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    library = load_json(
        footprint_path,
        default={
            "updated_at": "",
            "people": {},
        },
    )
    people_store = library.setdefault("people", {})

    def sort_key(item: Dict[str, Any]) -> Tuple[str, str]:
        return (item.get("departure_time") or item.get("source_sent_at") or "", item.get("source_message_id") or "")

    for item in sorted(records, key=sort_key):
        name = item["name"]
        destination = normalize_city(item.get("destination_city") or "")
        if not destination:
            item["is_first_time_destination"] = False
            continue
        person_entry = people_store.setdefault(name, {"destinations": {}, "trip_count": 0})
        destination_store = person_entry.setdefault("destinations", {})
        seen_before = destination in destination_store
        item["is_first_time_destination"] = not seen_before
        dest_entry = destination_store.setdefault(
            destination,
            {
                "first_seen_at": item.get("departure_time") or item.get("source_sent_at") or "",
                "last_seen_at": item.get("return_time") or item.get("departure_time") or item.get("source_sent_at") or "",
                "count": 0,
                "source_message_ids": [],
            },
        )
        dest_entry["last_seen_at"] = item.get("return_time") or item.get("departure_time") or item.get("source_sent_at") or dest_entry.get("last_seen_at", "")
        dest_entry["count"] = int(dest_entry.get("count", 0)) + 1
        message_id = item.get("source_message_id") or ""
        if message_id and message_id not in dest_entry["source_message_ids"]:
            dest_entry["source_message_ids"].append(message_id)
        person_entry["trip_count"] = int(person_entry.get("trip_count", 0)) + 1

    library["updated_at"] = dt.datetime.now().strftime("%Y-%m-%d")
    save_json(footprint_path, library)
    return records, library


def build_trip_id(name: str, anchor_time: str, destination_city: str, cluster_index: int) -> str:
    raw = f"{normalize_person_name(name)}|{anchor_time}|{normalize_city(destination_city)}|{cluster_index}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10].upper()
    return f"TRIP-{digest}"


def enrich_trip_ids(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in records:
        grouped[item.get("name") or "未知"].append(item)

    for person_records in grouped.values():
        person_records.sort(key=lambda row: (row.get("departure_time") or row.get("source_sent_at") or "", row.get("destination_city") or ""))
        cluster_index = 0
        previous: Optional[Dict[str, Any]] = None
        for item in person_records:
            start_dt = parse_dt_or_none(item.get("departure_time"))
            previous_end = parse_dt_or_none((previous or {}).get("return_time"))
            stitched = False
            if previous and start_dt and previous_end:
                gap_days = (start_dt - previous_end).total_seconds() / 86400
                same_city_chain = normalize_city(item.get("departure_city") or "") == normalize_city(previous.get("destination_city") or "")
                revisit_same_destination = normalize_city(item.get("destination_city") or "") == normalize_city(previous.get("destination_city") or "")
                stitched = 0 <= gap_days <= 4 and (same_city_chain or revisit_same_destination)
            if previous is None or not stitched:
                cluster_index += 1
            anchor_time = item.get("departure_time") or item.get("source_sent_at") or ""
            item["trip_cluster_index"] = cluster_index
            item["trip_id"] = build_trip_id(item.get("name") or "", anchor_time, item.get("destination_city") or "", cluster_index)
            previous = item
    return records


def compute_trip_risk_score(item: Dict[str, Any]) -> float:
    score = 100.0
    if item.get("is_booked_before_approval") is True:
        score -= 24
    if item.get("is_over_cabin_policy") is True:
        score -= 16
    if item.get("is_hotel_over_policy") is True:
        score -= 16
    if item.get("duplicate_booking_flag"):
        score -= 14
    if item.get("contains_weekend"):
        score -= 10
    if item.get("is_first_time_destination"):
        score -= 6
    cluster_size = int(item.get("travel_cluster_size") or 1)
    if cluster_size >= 3:
        score -= min(10, (cluster_size - 2) * 3)
    return round(max(0.0, min(100.0, score)), 1)


def risk_level_from_score(score: float) -> str:
    if score >= 85:
        return "low"
    if score >= 70:
        return "medium"
    return "high"


def build_spatiotemporal_clusters(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for item in records:
        destination = normalize_city(item.get("destination_city") or "")
        departure_day = str(item.get("departure_time") or "")[:10]
        if destination and departure_day:
            grouped[(destination, departure_day)].append(item)

    clusters: List[Dict[str, Any]] = []
    member_to_cluster: Dict[str, Dict[str, Any]] = {}
    for (destination, departure_day), items in grouped.items():
        people = sorted({item.get("name") or "--" for item in items})
        if not items:
            continue
        lead_values = [float(item["booking_lead_days"]) for item in items if isinstance(item.get("booking_lead_days"), (int, float))]
        cluster_seed = f"{destination}|{departure_day}|{'|'.join(people)}"
        cluster = {
            "cluster_id": f"CLUSTER-{hashlib.sha1(cluster_seed.encode('utf-8')).hexdigest()[:8].upper()}",
            "destination_city": destination,
            "departure_day": departure_day,
            "people": people,
            "trip_count": len(items),
            "avg_booking_lead_days": round(sum(lead_values) / len(lead_values), 1) if lead_values else None,
            "high_risk_trip_count": 0,
        }
        clusters.append(cluster)
        for item in items:
            member_to_cluster[item.get("trip_id") or ""] = cluster

    for item in records:
        cluster = member_to_cluster.get(item.get("trip_id") or "")
        if not cluster:
            item["travel_cluster_id"] = ""
            item["travel_cluster_size"] = 1
            item["travel_cluster_people"] = [item.get("name") or "--"]
            continue
        item["travel_cluster_id"] = cluster["cluster_id"]
        item["travel_cluster_size"] = cluster["trip_count"]
        item["travel_cluster_people"] = cluster["people"]

    return {
        "clusters": sorted(clusters, key=lambda row: (-row["trip_count"], row["departure_day"], row["destination_city"])),
        "member_to_cluster": member_to_cluster,
    }


def build_person_risk_rankings(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in records:
        grouped[item.get("name") or "未知"].append(item)

    rankings: List[Dict[str, Any]] = []
    for name, items in grouped.items():
        scores = [float(item.get("compliance_risk_score") or 0.0) for item in items]
        alerts = sum(
            1
            for item in items
            if (
                item.get("is_booked_before_approval") is True
                or item.get("is_over_cabin_policy") is True
                or item.get("is_hotel_over_policy") is True
                or item.get("duplicate_booking_flag")
                or item.get("contains_weekend")
            )
        )
        first_departure = min((item.get("departure_time") or item.get("source_sent_at") or "") for item in items)
        rankings.append(
            {
                "name": name,
                "risk_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
                "risk_level": risk_level_from_score(round(sum(scores) / len(scores), 1) if scores else 0.0),
                "trip_count": len(items),
                "alert_count": alerts,
                "first_time_count": sum(1 for item in items if item.get("is_first_time_destination")),
                "cluster_exposure": max(int(item.get("travel_cluster_size") or 1) for item in items),
                "avg_booking_lead_days": round(sum(float(item["booking_lead_days"]) for item in items if isinstance(item.get("booking_lead_days"), (int, float))) / max(1, sum(1 for item in items if isinstance(item.get("booking_lead_days"), (int, float)))), 1)
                if any(isinstance(item.get("booking_lead_days"), (int, float)) for item in items)
                else None,
                "latest_destination": sorted(items, key=lambda row: row.get("departure_time") or row.get("source_sent_at") or "")[-1].get("destination_city") or "--",
                "timeline_anchor": first_departure,
            }
        )

    rankings.sort(key=lambda row: (row["risk_score"], -row["alert_count"], -row["trip_count"], row["name"]))
    return rankings


def compute_health_rate(healthy_count: int, known_count: int) -> Optional[float]:
    if known_count <= 0:
        return None
    return round(healthy_count / known_count * 100, 1)


def build_compliance_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    lead_values = [float(item["booking_lead_days"]) for item in records if item.get("booking_lead_days") is not None]
    booked_flags = [item["is_booked_before_approval"] for item in records if item.get("is_booked_before_approval") is not None]
    cabin_flags = [item["is_over_cabin_policy"] for item in records if item.get("is_over_cabin_policy") is not None]
    hotel_flags = [item["is_hotel_over_policy"] for item in records if item.get("is_hotel_over_policy") is not None]
    over_policy_flags = [
        (item.get("is_over_cabin_policy") is True) or (item.get("is_hotel_over_policy") is True)
        for item in records
        if item.get("is_over_cabin_policy") is not None or item.get("is_hotel_over_policy") is not None
    ]
    duplicate_flags = [bool(item.get("duplicate_booking_flag")) for item in records]
    weekend_flags = [bool(item.get("contains_weekend")) for item in records]
    first_time_flags = [bool(item.get("is_first_time_destination")) for item in records]

    booked_after_approval_count = sum(1 for flag in booked_flags if flag is False)
    cabin_ok_count = sum(1 for flag in cabin_flags if flag is False)
    hotel_ok_count = sum(1 for flag in hotel_flags if flag is False)
    over_policy_ok_count = sum(1 for flag in over_policy_flags if flag is False)
    duplicate_ok_count = sum(1 for flag in duplicate_flags if flag is False)
    weekend_safe_count = sum(1 for flag in weekend_flags if flag is False)
    first_time_count = sum(1 for flag in first_time_flags if flag)
    known_first_time = len(first_time_flags)

    metrics = {
        "booking_lead_days": {
            "known_count": len(lead_values),
            "avg_days": round(sum(lead_values) / len(lead_values), 1) if lead_values else None,
        },
        "is_booked_before_approval": {
            "known_count": len(booked_flags),
            "violation_count": sum(1 for flag in booked_flags if flag),
            "healthy_rate": compute_health_rate(booked_after_approval_count, len(booked_flags)),
        },
        "is_over_cabin_policy": {
            "known_count": len(cabin_flags),
            "violation_count": sum(1 for flag in cabin_flags if flag),
            "healthy_rate": compute_health_rate(cabin_ok_count, len(cabin_flags)),
        },
        "is_hotel_over_policy": {
            "known_count": len(hotel_flags),
            "violation_count": sum(1 for flag in hotel_flags if flag),
            "healthy_rate": compute_health_rate(hotel_ok_count, len(hotel_flags)),
        },
        "over_policy_alert": {
            "known_count": len(over_policy_flags),
            "violation_count": sum(1 for flag in over_policy_flags if flag),
            "healthy_rate": compute_health_rate(over_policy_ok_count, len(over_policy_flags)),
            "transport_violation_count": sum(1 for flag in cabin_flags if flag),
            "hotel_violation_count": sum(1 for flag in hotel_flags if flag),
        },
        "duplicate_booking_flag": {
            "known_count": len(duplicate_flags),
            "violation_count": sum(1 for flag in duplicate_flags if flag),
            "healthy_rate": compute_health_rate(duplicate_ok_count, len(duplicate_flags)),
        },
        "contains_weekend": {
            "known_count": len(weekend_flags),
            "violation_count": sum(1 for flag in weekend_flags if flag),
            "healthy_rate": compute_health_rate(weekend_safe_count, len(weekend_flags)),
        },
        "is_first_time_destination": {
            "known_count": known_first_time,
            "first_time_count": first_time_count,
            "attention_rate": compute_health_rate(first_time_count, known_first_time),
        },
    }

    radar = [
        {"name": "审批顺序", "field": "is_booked_before_approval", "value": metrics["is_booked_before_approval"]["healthy_rate"]},
        {"name": "超标提醒", "field": "over_policy_alert", "value": metrics["over_policy_alert"]["healthy_rate"]},
        {"name": "重复预订", "field": "duplicate_booking_flag", "value": metrics["duplicate_booking_flag"]["healthy_rate"]},
        {"name": "周末差旅", "field": "contains_weekend", "value": metrics["contains_weekend"]["healthy_rate"]},
    ]

    alert_count = 0
    for item in records:
        if (
            item.get("is_booked_before_approval") is True
            or item.get("is_over_cabin_policy") is True
            or item.get("is_hotel_over_policy") is True
            or item.get("duplicate_booking_flag")
            or item.get("contains_weekend")
        ):
            alert_count += 1

    return {
        "metrics": metrics,
        "radar": radar,
        "alert_count": alert_count,
    }


def build_dashboard_payload(
    records: List[Dict[str, Any]],
    *,
    months: int,
    query_terms: Sequence[str],
    footprint_path: Path,
    mode: str = DEFAULT_COLLECTION_MODE,
    start_time_text: str = "",
    end_time_text: str = "",
    collection_audit: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now = dt.datetime.now()
    window_start, window_end = resolve_collection_window(
        months=months,
        start_time_text=start_time_text,
        end_time_text=end_time_text,
    )
    records = [dict(item) for item in records]
    for item in records:
        item["timeline_start"], item["timeline_end"] = compute_trip_window(item)
        item["contains_weekend"] = trip_contains_weekend(item)
    records = enrich_trip_ids(records)
    cluster_result = build_spatiotemporal_clusters(records)
    for item in records:
        item["compliance_risk_score"] = compute_trip_risk_score(item)
        item["compliance_risk_level"] = risk_level_from_score(float(item["compliance_risk_score"]))

    clusters = cluster_result["clusters"]
    cluster_lookup = {cluster["cluster_id"]: cluster for cluster in clusters}
    for item in records:
        cluster = cluster_lookup.get(item.get("travel_cluster_id") or "")
        if cluster and item.get("compliance_risk_level") == "high":
            cluster["high_risk_trip_count"] = int(cluster.get("high_risk_trip_count") or 0) + 1

    person_risk_rankings = build_person_risk_rankings(records)
    departure_counts = Counter(item["departure_city"] for item in records)
    destination_counts = Counter(item["destination_city"] for item in records)
    destination_first_counts = Counter(item["destination_city"] for item in records if item.get("is_first_time_destination"))
    people = sorted({item["name"] for item in records})
    ongoing = 0
    starts: List[dt.datetime] = []
    ends: List[dt.datetime] = []
    first_time_count = 0
    for item in records:
        start_dt = parse_dt_or_none(item.get("timeline_start") or item.get("departure_time"))
        end_dt = parse_dt_or_none(item.get("timeline_end") or item.get("return_time") or item.get("departure_time"))
        if start_dt:
            starts.append(start_dt)
        if end_dt:
            ends.append(end_dt)
        if start_dt and end_dt and start_dt <= now <= end_dt:
            ongoing += 1
        if item.get("is_first_time_destination"):
            first_time_count += 1

    compliance = build_compliance_summary(records)
    status_counts = Counter(item.get("record_status") or "complete" for item in records)
    review_count = sum(1 for item in records if item.get("needs_review"))
    travel_context_missing_count = sum(1 for item in records if item.get("travel_context_missing"))
    collection_audit = dict(collection_audit or {})
    for item in records:
        item.pop("_hotel_checkin_time", None)
        item.pop("_hotel_checkout_time", None)
    payload = {
        "version": "3.1",
        "generated_at": now.strftime("%Y-%m-%d"),
        "filters": {
            "months": months,
            "mode": resolve_collection_mode(mode),
            "query_terms": list(query_terms),
            "capture_scope": ALL_PARSED_TRAVELERS_LABEL,
            "window_start": window_start.strftime("%Y-%m-%d"),
            "window_end": window_end.strftime("%Y-%m-%d"),
        },
        "summary": {
            "total_trips": len(records),
            "active_people": len(people),
            "ongoing_trips": ongoing,
            "unique_destinations": len(destination_counts),
            "first_time_destinations": first_time_count,
            "compliance_alerts": compliance["alert_count"],
            "timeline_start": min(starts).strftime("%Y-%m-%d") if starts else "",
            "timeline_end": max(ends).strftime("%Y-%m-%d") if ends else "",
            "cluster_trip_groups": len(clusters),
            "high_risk_people": sum(1 for item in person_risk_rankings if item.get("risk_level") == "high"),
            "complete_trips": status_counts.get("complete", 0),
            "partial_trips": status_counts.get("partial", 0),
            "needs_review_count": review_count,
            "travel_context_missing_count": travel_context_missing_count,
        },
        "rankings": {
            "departure_cities": [{"name": k, "value": v} for k, v in departure_counts.most_common(8)],
            "destination_cities": [
                {"name": k, "value": v, "first_time_count": destination_first_counts.get(k, 0)}
                for k, v in destination_counts.most_common(12)
            ],
            "risk_blacklist": person_risk_rankings[:5],
            "risk_redlist": person_risk_rankings[:5],
            "risk_whitelist": sorted(person_risk_rankings, key=lambda row: (-row["risk_score"], row["alert_count"], row["name"]))[:5],
        },
        "risk_map": {
            "person_scores": person_risk_rankings,
            "scatter": [
                {
                    "name": item["name"],
                    "risk_score": item["risk_score"],
                    "trip_count": item["trip_count"],
                    "alert_count": item["alert_count"],
                    "first_time_count": item["first_time_count"],
                    "cluster_exposure": item["cluster_exposure"],
                    "avg_booking_lead_days": item["avg_booking_lead_days"],
                    "risk_level": item["risk_level"],
                    "latest_destination": item["latest_destination"],
                }
                for item in person_risk_rankings
            ],
            "clusters": clusters,
        },
        "compliance": compliance,
        "audit": {
            "booking_pipeline": collection_audit,
            "record_status_breakdown": dict(status_counts),
            "needs_review_count": review_count,
            "travel_context_missing_count": travel_context_missing_count,
        },
        "footprint_library": {
            "path": str(footprint_path),
        },
        "people": people,
        "trips": records,
    }
    return payload


def _sanitize_for_html_render(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_for_html_render(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_html_render(item) for item in value]
    if isinstance(value, str):
        return (
            value.replace("\r\n", "\\n")
            .replace("\r", "\\n")
            .replace("\n", "\\n")
            .replace("</script>", "<\\/script>")
            .replace("</SCRIPT>", "<\\/SCRIPT>")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
        )
    return value


def render_html(data: Dict[str, Any], *, template_path: Path, output_html: Path) -> Path:
    if not template_path.exists():
        raise DashboardError(f"模板不存在：{template_path}")
    template = template_path.read_text(encoding="utf-8")
    safe_data = _sanitize_for_html_render(data)
    rendered_data = json.dumps(safe_data, ensure_ascii=False, indent=2)
    if "__TRAVEL_DASHBOARD_DATA__" in template:
        rendered = template.replace("__TRAVEL_DASHBOARD_DATA__", rendered_data)
    else:
        rendered = re.sub(
            r"const\s+DASHBOARD_DATA\s*=\s*\{[\s\S]*?\n\s*};",
            f"const DASHBOARD_DATA = {rendered_data};",
            template,
            count=1,
        )
        if rendered == template:
            raise DashboardError("模板缺少 __TRAVEL_DASHBOARD_DATA__ 占位符，且未找到可替换的 DASHBOARD_DATA 静态块")
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(rendered, encoding="utf-8")
    return output_html


def materialize_dynamic_ui_card(input_html: Path, output_html: Path) -> Path:
    output_html.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(input_html, output_html)
    return output_html


def render_dynamic_ui_card(data: Dict[str, Any], *, template_path: Path, output_html: Path) -> Path:
    return render_html(data, template_path=template_path, output_html=output_html)


def collect_from_mail(
    *,
    months: int,
    max_messages: int,
    mailbox: str,
    query_terms: Sequence[str],
    mode: str = DEFAULT_COLLECTION_MODE,
    start_time_text: str = "",
    end_time_text: str = "",
    hotel_policy_table: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    ensure_mail_cli_ready()
    mode = resolve_collection_mode(mode)
    start_time, end_time = resolve_collection_window(
        months=months,
        start_time_text=start_time_text,
        end_time_text=end_time_text,
    )
    candidate_map: Dict[str, Dict[str, Any]] = {}
    hotel_policy_rules = load_hotel_policy_table(hotel_policy_table) if hotel_policy_table else []

    for query in query_terms:
        summaries = cli_triage(
            query,
            max_messages=max_messages,
            mailbox=mailbox,
            start_time=start_time,
            end_time=end_time,
        )
        for summary in summaries:
            sent_at = parse_dt_or_none(summary.get("date") or "")
            if sent_at and (sent_at < start_time or sent_at > end_time):
                continue
            candidate_map[summary["message_id"]] = summary

    inbox_summaries = cli_triage(
        max_messages=max_messages,
        mailbox=mailbox,
        start_time=start_time,
        end_time=end_time,
        folder="inbox",
    )
    for summary in inbox_summaries:
        sent_at = parse_dt_or_none(summary.get("date") or "")
        if sent_at and (sent_at < start_time or sent_at > end_time):
            continue
        if not summary_matches_collection(summary, mode=mode, query_terms=query_terms):
            continue
        candidate_map[summary["message_id"]] = summary

    message_ids = sorted(candidate_map.keys())
    messages = cli_fetch_messages(message_ids, mailbox=mailbox)
    parsed_records: List[Dict[str, Any]] = []
    booking_candidates: List[Dict[str, Any]] = []
    for message in messages:
        extracted = extract_records_from_message(message, allowed_mode=mode)
        for item in extracted:
            if item.get("source_channel") == "booking" or item.get("_booking_record_kind"):
                booking_candidates.append(item)
            else:
                parsed_records.append(item)
    finalized_booking_records, booking_audit = finalize_booking_records(
        booking_candidates,
        hotel_policy_rules=hotel_policy_rules,
    )
    parsed_records.extend(finalized_booking_records)
    normalized_records = [apply_hotel_policy_fields(item, hotel_policy_rules) for item in parsed_records]
    deduped = deduplicate_records(normalized_records)
    booking_audit["hotel_policy_rule_count"] = len(hotel_policy_rules)
    booking_audit["hotel_partial_retained"] = sum(
        1 for item in deduped if item.get("record_status") == "partial" and item.get("travel_context_missing")
    )
    booking_audit["hotel_partial_gap_after_dedup"] = max(
        int(booking_audit.get("hotel_partial_candidate_retained") or 0) - int(booking_audit.get("hotel_partial_retained") or 0),
        0,
    )
    return deduped, booking_audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build UK/EU/JP POP BD team travel dashboard assets.")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect-mails", help="抓取近 30 天差旅邮件并产出 JSON")
    collect.add_argument("--months", type=int, default=DEFAULT_MONTHS)
    collect.add_argument("--max-messages", type=int, default=DEFAULT_MAX_MESSAGES)
    collect.add_argument("--mailbox", default="me")
    collect.add_argument("--mode", choices=COLLECTION_MODE_CHOICES, default=DEFAULT_COLLECTION_MODE)
    collect.add_argument("--start-time", default="")
    collect.add_argument("--end-time", default="")
    collect.add_argument("--output-json", required=True)
    collect.add_argument("--geo-cache", default=DEFAULT_GEO_CACHE)
    collect.add_argument("--city-alias-cache", default=DEFAULT_CITY_ALIAS_CACHE)
    collect.add_argument("--footprint-library", default=DEFAULT_FOOTPRINT_LIBRARY)
    collect.add_argument("--hotel-policy-table", default=DEFAULT_HOTEL_POLICY_TABLE)
    collect.add_argument("--query", action="append", dest="queries")

    render = sub.add_parser("render-html", help="把 JSON 注入静态模板并输出大屏 HTML")
    render.add_argument("--input-json", required=True)
    render.add_argument("--template", default=f"assets/{DEFAULT_TEMPLATE_NAME}")
    render.add_argument("--output-html", required=True)

    render_dynamic = sub.add_parser("render-dynamic-ui", help="把 JSON 注入 dynamic-ui 专用模板并输出展示入口 HTML")
    render_dynamic.add_argument("--input-json", required=True)
    render_dynamic.add_argument("--template", default=f"assets/{DEFAULT_DYNAMIC_UI_TEMPLATE_NAME}")
    render_dynamic.add_argument("--output-html", required=True)

    build = sub.add_parser("build", help="全链路：抓邮件 -> 解析 -> geocode -> JSON -> HTML")
    build.add_argument("--months", type=int, default=DEFAULT_MONTHS)
    build.add_argument("--max-messages", type=int, default=DEFAULT_MAX_MESSAGES)
    build.add_argument("--mailbox", default="me")
    build.add_argument("--mode", choices=COLLECTION_MODE_CHOICES, default=DEFAULT_COLLECTION_MODE)
    build.add_argument("--start-time", default="")
    build.add_argument("--end-time", default="")
    build.add_argument("--output-json", required=True)
    build.add_argument("--output-html", required=True)
    build.add_argument("--template", default=f"assets/{DEFAULT_TEMPLATE_NAME}")
    build.add_argument("--geo-cache", default=DEFAULT_GEO_CACHE)
    build.add_argument("--city-alias-cache", default=DEFAULT_CITY_ALIAS_CACHE)
    build.add_argument("--footprint-library", default=DEFAULT_FOOTPRINT_LIBRARY)
    build.add_argument("--hotel-policy-table", default=DEFAULT_HOTEL_POLICY_TABLE)
    build.add_argument("--query", action="append", dest="queries")
    build.add_argument("--dynamic-ui-output", default="")

    materialize = sub.add_parser("materialize-dynamic-ui", help="把已生成 HTML 复制到动态展示目录")
    materialize.add_argument("--input-html", required=True)
    materialize.add_argument("--output-html", required=True)
    return parser


def process_records(
    records: List[Dict[str, Any]], *, geo_cache: Path, city_alias_cache: Path, footprint_path: Path
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    aliased = apply_city_aliases(records, cache_path=city_alias_cache)
    enriched = enrich_with_coordinates(aliased, cache_path=geo_cache)
    enriched = mark_duplicate_bookings(enriched)
    enriched, footprint_library = apply_first_time_destination_flags(enriched, footprint_path=footprint_path)
    return enriched, footprint_library


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    skill_root = Path(__file__).resolve().parents[1]

    if args.command == "collect-mails":
        mode = resolve_collection_mode(args.mode)
        queries = resolve_query_terms(mode, args.queries)
        records, collection_audit = collect_from_mail(
            months=args.months,
            max_messages=args.max_messages,
            mailbox=args.mailbox,
            query_terms=queries,
            mode=mode,
            start_time_text=args.start_time,
            end_time_text=args.end_time,
            hotel_policy_table=(skill_root / args.hotel_policy_table),
        )
        enriched, _ = process_records(
            records,
            geo_cache=(skill_root / args.geo_cache),
            city_alias_cache=(skill_root / args.city_alias_cache),
            footprint_path=(skill_root / args.footprint_library),
        )
        payload = build_dashboard_payload(
            enriched,
            months=args.months,
            query_terms=queries,
            footprint_path=(skill_root / args.footprint_library),
            mode=mode,
            start_time_text=args.start_time,
            end_time_text=args.end_time,
            collection_audit=collection_audit,
        )
        snapshot_dir = skill_root / "output" / "snapshots"
        payload = enrich_daily_alert_diff(payload, snapshot_dir=snapshot_dir)
        output_json = skill_root / args.output_json
        save_json(output_json, payload)
        snapshot_path = persist_daily_snapshot(payload, snapshot_dir=snapshot_dir)
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": mode,
                    "output_json": str(output_json.resolve()),
                    "snapshot_json": str(snapshot_path.resolve()),
                    "daily_new_alerts": payload.get("summary", {}).get("daily_new_alerts", 0),
                    "trip_count": len(enriched),
                    "footprint_library": str((skill_root / args.footprint_library).resolve()),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "render-html":
        data = load_json(skill_root / args.input_json, default={})
        data = enrich_daily_alert_diff(data, snapshot_dir=(skill_root / "output" / "snapshots"))
        output_html = render_html(data, template_path=(skill_root / args.template), output_html=(skill_root / args.output_html))
        print(json.dumps({"ok": True, "output_html": str(output_html.resolve()), "daily_new_alerts": data.get("summary", {}).get("daily_new_alerts", 0)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "render-dynamic-ui":
        data = load_json(skill_root / args.input_json, default={})
        data = enrich_daily_alert_diff(data, snapshot_dir=(skill_root / "output" / "snapshots"))
        output_html = render_dynamic_ui_card(
            data,
            template_path=(skill_root / args.template),
            output_html=(skill_root / args.output_html),
        )
        print(json.dumps({"ok": True, "dynamic_ui_html": str(output_html.resolve())}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "build":
        mode = resolve_collection_mode(args.mode)
        queries = resolve_query_terms(mode, args.queries)
        records, collection_audit = collect_from_mail(
            months=args.months,
            max_messages=args.max_messages,
            mailbox=args.mailbox,
            query_terms=queries,
            mode=mode,
            start_time_text=args.start_time,
            end_time_text=args.end_time,
            hotel_policy_table=(skill_root / args.hotel_policy_table),
        )
        enriched, _ = process_records(
            records,
            geo_cache=(skill_root / args.geo_cache),
            city_alias_cache=(skill_root / args.city_alias_cache),
            footprint_path=(skill_root / args.footprint_library),
        )
        payload = build_dashboard_payload(
            enriched,
            months=args.months,
            query_terms=queries,
            footprint_path=(skill_root / args.footprint_library),
            mode=mode,
            start_time_text=args.start_time,
            end_time_text=args.end_time,
            collection_audit=collection_audit,
        )
        output_json = skill_root / args.output_json
        output_html = skill_root / args.output_html
        snapshot_dir = skill_root / "output" / "snapshots"
        payload = enrich_daily_alert_diff(payload, snapshot_dir=snapshot_dir)
        save_json(output_json, payload)
        snapshot_path = persist_daily_snapshot(payload, snapshot_dir=snapshot_dir)
        render_html(payload, template_path=(skill_root / args.template), output_html=output_html)
        response = {
            "ok": True,
            "mode": mode,
            "output_json": str(output_json.resolve()),
            "output_html": str(output_html.resolve()),
            "snapshot_json": str(snapshot_path.resolve()),
            "daily_new_alerts": payload.get("summary", {}).get("daily_new_alerts", 0),
            "trip_count": len(enriched),
            "footprint_library": str((skill_root / args.footprint_library).resolve()),
        }
        if args.dynamic_ui_output:
            card_path = render_dynamic_ui_card(
                payload,
                template_path=(skill_root / f"assets/{DEFAULT_DYNAMIC_UI_TEMPLATE_NAME}"),
                output_html=(skill_root / args.dynamic_ui_output),
            )
            response["dynamic_ui_html"] = str(card_path.resolve())
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return 0

    if args.command == "materialize-dynamic-ui":
        card_path = materialize_dynamic_ui_card(skill_root / args.input_html, skill_root / args.output_html)
        print(json.dumps({"ok": True, "dynamic_ui_html": str(card_path.resolve())}, ensure_ascii=False, indent=2))
        return 0

    raise DashboardError(f"未知命令：{args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DashboardError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(2)
