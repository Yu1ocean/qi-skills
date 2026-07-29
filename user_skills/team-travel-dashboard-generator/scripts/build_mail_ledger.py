#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from build_travel_dashboard import (
    DEFAULT_MONTHS,
    DashboardError,
    cli_fetch_messages,
    cli_triage,
    ensure_mail_cli_ready,
    extract_message_sender,
    extract_message_subject,
    extract_message_text,
    extract_records_from_message,
    infer_message_channel,
    normalize_text,
    parse_sent_at,
    pick_first_present,
    resolve_collection_window,
    save_json,
)

DEFAULT_OUTPUT_JSON = "output/mail_ledger.json"
DEFAULT_DETAILS_HTML = False
DEFAULT_BATCH_SIZE = 100
DEFAULT_ALLOWED_MODE = "auto"
DEFAULT_PRIMARY_FOLDERS = ["INBOX"]
DEFAULT_EXCLUDED_FOLDERS = ["SENT", "DRAFT", "SCHEDULED", "TRASH", "SPAM"]
DEFAULT_LEDGER_LOOKBACK_MONTHS = 1
CATEGORY_ORDER = [
    "travel_booking",
    "travel_approval",
    "travel_other",
    "finance_expense",
    "calendar_invite",
    "workspace_collaboration",
    "tiktok_notification",
    "system_alert",
    "hr_admin",
    "marketing_subscription",
    "general_other",
]

TRAVEL_FALLBACK_KEYWORDS = ["差旅", "出差", "travel approval", "trip approval", "员工商旅系统", "Hi Travel", "预订了机票", "预订了酒店", "火车票"]
TRAVEL_BOOKING_REQUIRED_KEYWORDS = ["【差旅】", "预订了机票", "预订了酒店", "Hi Travel", "员工商旅系统", "火车票"]
TRAVEL_APPROVAL_REQUIRED_KEYWORDS = ["差旅审批", "出差审批", "travel approval", "trip approval", "审批通过"]
NON_TRAVEL_AUTH_KEYWORDS = [
    "sso",
    "验证码",
    "verification code",
    "verify code",
    "login code",
    "auth code",
    "otp",
    "one-time password",
    "single sign-on",
    "双重验证",
    "二次验证",
    "login verification",
]
NON_TRAVEL_AUTH_SENDERS = ["bytedance sso", "sso"]

CATEGORY_RULES: List[Dict[str, Any]] = [
    {
        "category": "travel_booking",
        "keywords": ["【差旅】", "预订了机票", "预订了酒店", "Hi Travel", "员工商旅系统", "火车票"],
        "senders": ["travel", "trip", "hitravel", "员工商旅系统"],
    },
    {
        "category": "travel_approval",
        "keywords": ["差旅审批", "出差审批", "travel approval", "trip approval", "审批通过"],
        "senders": ["approval", "workflow", "oa"],
    },
    {
        "category": "finance_expense",
        "keywords": ["报销", "发票", "invoice", "付款", "payment", "reimbursement", "对账单", "费用"],
        "senders": ["finance", "billing", "invoice"],
    },
    {
        "category": "calendar_invite",
        "keywords": ["会议邀请", "calendar", "accepted", "declined", "tentative", "邀请你参加"],
        "senders": ["calendar", "vc", "meeting"],
    },
    {
        "category": "workspace_collaboration",
        "keywords": ["飞书文档", "评论", "@你", "任务", "Meego", "Lark", "Feishu", "文档", "表格", "Wiki", "代码评审"],
        "senders": ["lark", "feishu", "meego", "code", "review"],
    },
    {
        "category": "tiktok_notification",
        "keywords": ["TikTok", "posted:", "LIVE", "creator", "shop", "campaign"],
        "senders": ["tiktok", "notification@service.tiktok.com"],
    },
    {
        "category": "system_alert",
        "keywords": [
            "alert",
            "告警",
            "warning",
            "incident",
            "error",
            "failure",
            "forbidden",
            "权限",
            "sso",
            "验证码",
            "verification code",
            "verify code",
            "login code",
            "auth code",
            "otp",
            "single sign-on",
            "login verification",
        ],
        "senders": ["noreply", "no-reply", "system", "alert", "monitor", "security", "sso"],
    },
    {
        "category": "hr_admin",
        "keywords": ["绩效", "假期", "休假", "薪酬", "考勤", "培训", "入职", "离职", "offer"],
        "senders": ["hr", "people", "talent"],
    },
    {
        "category": "marketing_subscription",
        "keywords": ["newsletter", "subscribe", "promotion", "promo", "折扣", "优惠", "sale", "deals"],
        "senders": ["newsletter", "marketing", "promo"],
    },
]


def contains_any(text: str, keywords: Sequence[str]) -> bool:
    lowered = (text or "").lower()
    return any(keyword and keyword.lower() in lowered for keyword in keywords)


def read_nested(message: Dict[str, Any], path: Sequence[str]) -> Any:
    node: Any = message
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def extract_sender_email(message: Dict[str, Any]) -> str:
    candidates = [
        read_nested(message, ["from", "email"]),
        read_nested(message, ["from", "address"]),
        message.get("from_address"),
        message.get("sender_email"),
    ]
    for value in candidates:
        if value:
            return normalize_text(str(value))
    sender = extract_message_sender(message)
    if "<" in sender and ">" in sender:
        return normalize_text(sender.split("<", 1)[1].split(">", 1)[0])
    return ""


def extract_folder(message: Dict[str, Any]) -> str:
    for key in ["folder", "folder_id", "mail_folder", "folder_name"]:
        value = message.get(key)
        if value:
            return normalize_text(str(value))
    return ""


def extract_label_list(message: Dict[str, Any]) -> List[str]:
    raw = message.get("labels") or message.get("label_ids") or []
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.split(",") if part.strip()]
        return parts
    if isinstance(raw, list):
        return [normalize_text(str(item)) for item in raw if normalize_text(str(item))]
    return []


def extract_thread_id(message: Dict[str, Any]) -> str:
    return normalize_text(str(message.get("thread_id") or message.get("conversation_id") or ""))


def detect_calendar_signal(message: Dict[str, Any], text: str) -> bool:
    return bool(message.get("calendar_event")) or contains_any(text, ["会议邀请", "calendar", "RSVP", "accepted", "declined"])


def build_signal_text(message: Dict[str, Any], text: str) -> str:
    subject = extract_message_subject(message)
    sender = extract_message_sender(message)
    sender_email = extract_sender_email(message)
    folder = extract_folder(message)
    labels = " ".join(extract_label_list(message))
    return "\n".join([subject, sender, sender_email, folder, labels, text]).strip()


def score_rule(signal_text: str, sender_email: str, rule: Dict[str, Any]) -> Tuple[int, List[str]]:
    score = 0
    evidence: List[str] = []
    for keyword in rule.get("keywords", []):
        if keyword and keyword.lower() in signal_text.lower():
            score += 2
            evidence.append(f"kw:{keyword}")
    for sender_kw in rule.get("senders", []):
        if sender_kw and sender_kw.lower() in sender_email.lower():
            score += 3
            evidence.append(f"sender:{sender_kw}")
    return score, evidence


def has_evidence_prefix(evidence: Sequence[str], prefix: str) -> bool:
    return any(item.startswith(prefix) for item in evidence)


def is_non_travel_auth_message(*, signal_text: str, sender: str, sender_email: str) -> bool:
    sender_signal = f"{sender}\n{sender_email}"
    return contains_any(signal_text, NON_TRAVEL_AUTH_KEYWORDS) or contains_any(sender_signal, NON_TRAVEL_AUTH_SENDERS)


def apply_category_guards(
    *,
    subject: str,
    sender: str,
    sender_email: str,
    signal_text: str,
    travel_records: Sequence[Dict[str, Any]],
    scores: Dict[str, int],
    evidence_map: Dict[str, List[str]],
) -> None:
    non_travel_auth_hit = is_non_travel_auth_message(signal_text=signal_text, sender=sender, sender_email=sender_email)
    booking_has_hard_signal = contains_any(subject, TRAVEL_BOOKING_REQUIRED_KEYWORDS) or has_evidence_prefix(
        evidence_map.get("travel_booking", []), "travel_parser:"
    )
    approval_has_hard_signal = contains_any(signal_text, TRAVEL_APPROVAL_REQUIRED_KEYWORDS) or has_evidence_prefix(
        evidence_map.get("travel_approval", []), "travel_parser:"
    )
    has_travel_records = bool(travel_records)

    if non_travel_auth_hit and not has_travel_records:
        scores["travel_booking"] = 0
        scores["travel_approval"] = 0
        scores["travel_other"] = 0
        evidence_map["travel_booking"] = ["guard:non_travel_auth_suppressed"]
        evidence_map["travel_approval"] = ["guard:non_travel_auth_suppressed"]
        evidence_map["travel_other"] = ["guard:non_travel_auth_suppressed"]
        scores["system_alert"] = max(scores.get("system_alert", 0), 8)
        evidence_map.setdefault("system_alert", [])
        evidence_map["system_alert"] = list(dict.fromkeys(evidence_map["system_alert"] + ["guard:sso_verification"]))
        return

    if scores.get("travel_booking", 0) > 0 and not booking_has_hard_signal and not has_travel_records:
        scores["travel_booking"] = 0
        evidence_map["travel_booking"] = ["guard:sender_only_booking_suppressed"]

    if scores.get("travel_approval", 0) > 0 and not approval_has_hard_signal and not has_travel_records:
        scores["travel_approval"] = 0
        evidence_map["travel_approval"] = ["guard:sender_only_approval_suppressed"]


def classify_message(message: Dict[str, Any], *, allowed_mode: str) -> Dict[str, Any]:
    text = extract_message_text(message)
    subject = extract_message_subject(message)
    sender = extract_message_sender(message)
    sender_email = extract_sender_email(message)
    folder = extract_folder(message)
    labels = extract_label_list(message)
    sent_at = parse_sent_at(
        pick_first_present(message, ["date", "date_formatted", "sent_at", "timestamp", "internal_date", "create_time"])
    )
    signal_text = build_signal_text(message, text)
    scores: Dict[str, int] = {}
    evidence_map: Dict[str, List[str]] = {}
    for rule in CATEGORY_RULES:
        score, evidence = score_rule(signal_text, sender_email, rule)
        scores[rule["category"]] = score
        evidence_map[rule["category"]] = evidence

    travel_records = []
    if allowed_mode in {"auto", "travel-only"}:
        try:
            travel_records = extract_records_from_message(message, allowed_mode="auto")
        except Exception:
            travel_records = []

    inferred_channel = infer_message_channel(message, text) if text else ""
    if travel_records:
        if inferred_channel == "booking":
            scores["travel_booking"] = max(scores.get("travel_booking", 0), 8)
            evidence_map.setdefault("travel_booking", []).append("travel_parser:booking")
        else:
            scores["travel_approval"] = max(scores.get("travel_approval", 0), 8)
            evidence_map.setdefault("travel_approval", []).append("travel_parser:approval")
    elif contains_any(signal_text, TRAVEL_FALLBACK_KEYWORDS):
        scores["travel_other"] = max(scores.get("travel_other", 0), 3)
        evidence_map.setdefault("travel_other", []).append("fallback:travel_keyword")

    if detect_calendar_signal(message, text):
        scores["calendar_invite"] = max(scores.get("calendar_invite", 0), 4)
        evidence_map.setdefault("calendar_invite", []).append("calendar_signal")

    apply_category_guards(
        subject=subject,
        sender=sender,
        sender_email=sender_email,
        signal_text=signal_text,
        travel_records=travel_records,
        scores=scores,
        evidence_map=evidence_map,
    )

    ranked = sorted(scores.items(), key=lambda item: (-item[1], CATEGORY_ORDER.index(item[0]) if item[0] in CATEGORY_ORDER else 999))
    primary_category = ranked[0][0] if ranked and ranked[0][1] > 0 else "general_other"
    secondary_categories = [name for name, score in ranked[1:] if score > 0][:3]
    is_travel_related = primary_category.startswith("travel_") or any(cat.startswith("travel_") for cat in secondary_categories)

    travel_people = sorted({normalize_text(str(item.get("name") or "")) for item in travel_records if item.get("name")})
    travel_routes = sorted(
        {
            f"{item.get('departure_city') or ''}->{item.get('destination_city') or ''}"
            for item in travel_records
            if item.get("departure_city") and item.get("destination_city")
        }
    )
    record = {
        "message_id": normalize_text(str(message.get("message_id") or message.get("id") or "")),
        "thread_id": extract_thread_id(message),
        "folder": folder,
        "subject": subject,
        "sender": sender,
        "sender_email": sender_email,
        "sent_at": sent_at or "",
        "labels": labels,
        "primary_category": primary_category,
        "secondary_categories": secondary_categories,
        "category_scores": {key: value for key, value in ranked if value > 0},
        "classification_evidence": evidence_map.get(primary_category, []),
        "is_travel_related": is_travel_related,
        "travel_channel": inferred_channel if is_travel_related else "",
        "travel_record_count": len(travel_records),
        "travel_people": travel_people,
        "travel_routes": travel_routes,
        "security_level": normalize_text(str(message.get("security_level") or "")),
        "raw_excerpt": text[:800],
    }
    return record


def summarize_records(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    category_counter = Counter(item.get("primary_category") or "general_other" for item in records)
    folder_counter = Counter(item.get("folder") or "UNKNOWN" for item in records)
    sender_counter = Counter(item.get("sender_email") or item.get("sender") or "UNKNOWN" for item in records)
    travel_count = sum(1 for item in records if item.get("is_travel_related"))
    return {
        "total_messages": len(records),
        "travel_related_messages": travel_count,
        "non_travel_messages": len(records) - travel_count,
        "categories": dict(category_counter.most_common()),
        "folders": dict(folder_counter.most_common()),
        "top_senders": [{"sender": sender, "count": count} for sender, count in sender_counter.most_common(20)],
    }


def collect_message_summaries(
    *,
    months: int,
    max_messages: int,
    mailbox: str,
    start_time_text: str = "",
    end_time_text: str = "",
    folders: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    start_time, end_time = resolve_collection_window(months=months, start_time_text=start_time_text, end_time_text=end_time_text)
    target_folders = [normalize_text(folder) for folder in (folders or DEFAULT_PRIMARY_FOLDERS) if normalize_text(folder)]
    collected: Dict[str, Dict[str, Any]] = {}
    per_folder_limit = max_messages if max_messages and len(target_folders) == 1 else 0
    for folder in target_folders:
        summaries = cli_triage(
            query="",
            max_messages=per_folder_limit,
            mailbox=mailbox,
            start_time=start_time,
            end_time=end_time,
            folder=folder,
        )
        for item in summaries:
            raw = dict(item.get("raw") or {})
            raw.setdefault("folder", folder)
            collected[item["message_id"]] = raw
            if max_messages and len(collected) >= max_messages:
                return list(collected.values())[:max_messages]
    return list(collected.values())[:max_messages] if max_messages else list(collected.values())


def chunked(items: Sequence[str], size: int) -> Iterable[List[str]]:
    for idx in range(0, len(items), size):
        yield list(items[idx : idx + size])


def collect_mail_ledger(
    *,
    months: int,
    max_messages: int,
    mailbox: str,
    output_json: Path,
    start_time_text: str = "",
    end_time_text: str = "",
    folders: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    ensure_mail_cli_ready()
    summaries = collect_message_summaries(
        months=months,
        max_messages=max_messages,
        mailbox=mailbox,
        start_time_text=start_time_text,
        end_time_text=end_time_text,
        folders=folders,
    )
    message_ids = [normalize_text(str(item.get("message_id") or item.get("id") or "")) for item in summaries]
    message_ids = [item for item in message_ids if item]
    details: Dict[str, Dict[str, Any]] = {}
    for batch in chunked(message_ids, DEFAULT_BATCH_SIZE):
        for message in cli_fetch_messages(batch, mailbox=mailbox):
            message_id = normalize_text(str(message.get("message_id") or message.get("id") or ""))
            if message_id:
                details[message_id] = message

    merged_records: List[Dict[str, Any]] = []
    for summary in summaries:
        message_id = normalize_text(str(summary.get("message_id") or summary.get("id") or ""))
        message = dict(summary)
        if message_id in details:
            rich = dict(details[message_id])
            merged = dict(summary)
            for key, value in rich.items():
                if value in (None, "", [], {}):
                    continue
                merged[key] = value
            merged.setdefault("folder", summary.get("folder") or "")
            message = merged
        elif summary.get("folder"):
            message.setdefault("folder", summary.get("folder"))
        merged_records.append(classify_message(message, allowed_mode=DEFAULT_ALLOWED_MODE))

    payload = {
        "version": "1.2",
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mailbox": mailbox,
        "qa": {
            "purpose": "zero_trust_qa",
            "travel_dashboard_skill_version": "2.8",
            "allowed_mode": DEFAULT_ALLOWED_MODE,
            "mail_ledger_guardrails": [
                "travel_booking_requires_booking_subject_or_parser_evidence",
                "sso_verification_and_auth_mail_are_forced_out_of_travel_categories",
                "generic_noreply_sender_no_longer_counts_as_travel_booking_signal",
            ],
        },
        "filters": {
            "months": months,
            "max_messages": max_messages,
            "start_time": start_time_text,
            "end_time": end_time_text,
            "folders": list(folders or DEFAULT_PRIMARY_FOLDERS),
            "excluded_folders": list(DEFAULT_EXCLUDED_FOLDERS),
            "scope_note": "当前版本默认扫 INBOX；如后续补齐 folder read scope，可升级为多文件夹全量 sweep。",
        },
        "summary": summarize_records(merged_records),
        "messages": sorted(
            merged_records,
            key=lambda item: ((item.get("sent_at") or ""), (item.get("message_id") or "")),
            reverse=True,
        ),
    }
    save_json(output_json, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an auditable mail ledger for travel dashboard zero-trust QA and cross-skill review."
    )
    parser.add_argument("--months", type=int, default=DEFAULT_LEDGER_LOOKBACK_MONTHS, help="回溯最近 N 个月，默认 1（约近 30 天）")
    parser.add_argument("--max-messages", type=int, default=0, help="最多抓取多少封邮件，0 表示不设上限")
    parser.add_argument("--mailbox", default="me", help="邮箱标识，默认 me")
    parser.add_argument("--start-time", default="", help="可选，显式起始时间 YYYY-MM-DD")
    parser.add_argument("--end-time", default="", help="可选，显式结束时间 YYYY-MM-DD")
    parser.add_argument("--folder", action="append", dest="folders", help="指定要扫描的 folder，可重复传入；默认 INBOX")
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON, help=f"输出 JSON，默认 {DEFAULT_OUTPUT_JSON}")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    skill_root = Path(__file__).resolve().parents[1]
    output_json = skill_root / args.output_json
    payload = collect_mail_ledger(
        months=args.months,
        max_messages=args.max_messages,
        mailbox=args.mailbox,
        output_json=output_json,
        start_time_text=args.start_time,
        end_time_text=args.end_time,
        folders=args.folders,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "output_json": str(output_json.resolve()),
                "summary": payload["summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DashboardError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
