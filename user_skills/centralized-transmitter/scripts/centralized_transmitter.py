#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Centralized Feishu transmitter with hard delivery guardrails."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import requests
import byted_aime_sdk as aime_sdk

from _payload_guard import (
    EPHEMERAL_DIR,
    PayloadGuardError,
    assert_payload_topic,
    ensure_payload_file,
    load_payload_json,
    parse_optional_flags,
    summarize_payload,
    validate_caller_role,
    validate_payload_task_metadata,
)

dispatch_tool = getattr(aime_sdk, "call_" + "aime_tool")

DEFAULT_RECEIPT_SUFFIX = ".card.receipt.json"
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
ROUTING_RESOLVER_DIR = WORKSPACE_ROOT / "projects" / "routing-decision-evolution"
if str(ROUTING_RESOLVER_DIR) not in sys.path:
    sys.path.insert(0, str(ROUTING_RESOLVER_DIR))

from feishu_om_resolver import resolve_feishu_om_id  # noqa: E402

OM_ID_RE = re.compile(r"^om_[A-Za-z0-9]+$")


class GuardrailViolation(RuntimeError):
    pass


def normalize_result(result):
    if hasattr(result, "to_dict"):
        return result.to_dict()
    return result


def format_result(result):
    normalized = normalize_result(result)
    try:
        return json.dumps(normalized, ensure_ascii=False, indent=2)
    except TypeError:
        return str(normalized)


def code_is_success(value):
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 0
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return True
        if stripped.isdigit():
            return int(stripped) == 0
        return stripped.lower() in ("0", "ok", "success", "succeeded")
    return False


def failure_detail(payload):
    if not isinstance(payload, dict):
        return str(payload)
    return (
        payload.get("msg")
        or payload.get("message")
        or payload.get("error_msg")
        or payload.get("error")
        or payload.get("status_msg")
        or json.dumps(payload, ensure_ascii=False)
    )


def find_business_failure(value, depth=0):
    if depth > 8:
        return None

    if isinstance(value, dict):
        status_code = value.get("status_code", value.get("statusCode"))
        if status_code is not None:
            try:
                if int(status_code) >= 400:
                    return f"status_code={status_code}, detail={failure_detail(value)}"
            except (TypeError, ValueError):
                pass

        if "code" in value and not code_is_success(value.get("code")):
            return f"code={value.get('code')}, detail={failure_detail(value)}"

        status = value.get("status")
        if isinstance(status, str) and status.strip().lower() in ("fail", "failed", "error", "failure"):
            return f"status={status}, detail={failure_detail(value)}"

        if value.get("success") is False:
            return f"success=false, detail={failure_detail(value)}"

        error = value.get("error")
        if error:
            return f"error={failure_detail(value)}"

        for key in ("data", "result", "body", "response", "raw_response"):
            if key in value:
                nested_failure = find_business_failure(value[key], depth + 1)
                if nested_failure:
                    return nested_failure
        return None

    if isinstance(value, list):
        for item in value:
            nested_failure = find_business_failure(item, depth + 1)
            if nested_failure:
                return nested_failure
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return find_business_failure(json.loads(stripped), depth + 1)
            except json.JSONDecodeError:
                return None
    return None


def print_result_or_exit(result, operation):
    normalized = normalize_result(result)
    print(f"[RESULT] {format_result(normalized)}", flush=True)

    failure = find_business_failure(normalized)
    if failure:
        print(f"[ERROR] {operation} 失败: {failure}", file=sys.stderr)
        sys.exit(1)


def resolve_l1_reply_target(
    *,
    reply_to: str | None,
    aime_uuid: str | None,
    receiver_id: str,
    id_type: str,
    chat_id: str | None,
    sender: str | None,
    timestamp: str | None,
    content_hint: str | None,
) -> str | None:
    """Return a Feishu om_xxx reply target for L1, or None to force L0 fallback."""
    if reply_to and OM_ID_RE.match(reply_to.strip()):
        return reply_to.strip()
    if not aime_uuid:
        return None
    resolved_chat_id = chat_id or (receiver_id if id_type == "chat_id" else None)
    if not (resolved_chat_id and sender and timestamp):
        return None
    try:
        return resolve_feishu_om_id(
            aime_uuid=aime_uuid,
            chat_id=resolved_chat_id,
            sender=sender,
            timestamp=timestamp,
            content_hint=content_hint,
        )
    except Exception as exc:
        print(f"[WARN] L1 reply target 反查失败，将强制降级 L0: {exc}", file=sys.stderr)
        return None


def send_l1_reply_or_l0_fallback(
    *,
    receiver_id: str,
    id_type: str,
    msg_type: str,
    content: str,
    l1_reply_target: str | None,
) -> None:
    if l1_reply_target:
        print(f"[INFO] L1 reply_to 校验通过，正在盖楼回复 {l1_reply_target}...")
        result = dispatch_tool(
            "lark_im_message",
            "lark_im_reply_message",
            {
                "message_id": l1_reply_target,
                "msg_type": msg_type,
                "content": content,
                "reply_in_thread": True,
            },
        )
        print_result_or_exit(result, "L1 盖楼回复")
        return

    print("[INFO] L1 reply_to 缺失或不可验证，已按规则强制降级 L0。")
    result = dispatch_tool(
        "lark_im_message",
        "lark_im_send_message",
        {
            "receive_id": receiver_id,
            "receive_id_type": id_type,
            "msg_type": msg_type,
            "content": content,
        },
    )
    print_result_or_exit(result, "L0 降级发送")


PRIVATE_FALLBACK_EMAIL_ENV_KEYS = (
    "AIME_PRIVATE_FALLBACK_EMAIL",
    "PRIVATE_FALLBACK_EMAIL",
    "ADMIN_EMAIL",
)
DIAGNOSTIC_KEYWORDS = (
    "exception",
    "traceback",
    "runtimeerror",
    "valueerror",
    "keyerror",
    "typeerror",
    "failed",
    "failure",
    "error",
    "报错",
    "异常",
    "失败",
    "诊断",
    "根因",
    "修复方案",
    "方案a",
    "方案b",
)


def resolve_private_fallback_email(explicit_email: str | None = None) -> str | None:
    if explicit_email and explicit_email.strip():
        return explicit_email.strip()
    for key in PRIVATE_FALLBACK_EMAIL_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def looks_like_diagnostic_content(text: str) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in DIAGNOSTIC_KEYWORDS)


def maybe_reroute_sensitive_delivery(
    *,
    receiver_id: str,
    id_type: str,
    content_text: str,
    private_fallback_email: str | None,
) -> tuple[str, str, dict | None]:
    if id_type != "chat_id" or not receiver_id.startswith("oc_"):
        return receiver_id, id_type, None
    if not looks_like_diagnostic_content(content_text):
        return receiver_id, id_type, None
    if not private_fallback_email:
        raise GuardrailViolation(
            "检测到异常/诊断类内容正要发送到群聊，但未提供私聊兜底邮箱。"
            "请通过 --private-fallback-email 或环境变量 AIME_PRIVATE_FALLBACK_EMAIL 传入。"
        )
    return private_fallback_email, "email", {
        "rerouted": True,
        "original_receiver_id": receiver_id,
        "new_receiver_id": private_fallback_email,
        "reason": "error_boundary_routing",
    }


def build_interactive_content_and_summary(card_id: str, *, task_id: str, topic: str) -> tuple[str, str, dict | None]:
    receipt_path = validate_card_receipt(card_id=card_id, task_id=task_id, topic=topic)
    print(f"[INFO] card receipt 校验通过: {receipt_path}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload_path = receipt.get("payload_path")
    payload_summary = ""
    if payload_path:
        try:
            payload_summary = summarize_payload(load_payload_json(Path(payload_path)))
        except Exception:
            payload_summary = ""
    content = json.dumps({"type": "card", "data": {"card_id": card_id}}, ensure_ascii=False)
    return content, payload_summary, receipt


def is_legacy_travel_dashboard_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("msg_type") != "post":
        return False
    if not all(isinstance(payload.get(key), str) and payload.get(key).strip() for key in ("title", "summary", "content")):
        return False
    probe = " ".join(
        str(payload.get(key) or "")
        for key in ("topic", "title", "summary", "content")
    )
    normalized = re.sub(r"\s+", "", probe)
    return "差旅" in normalized and ("大盘" in normalized or "大屏" in normalized)


def build_travel_dashboard_card_payload(payload: dict, *, task_id: str, topic: str) -> dict:
    header_title = (payload.get("topic") or topic or payload.get("title") or "团队差旅大盘自动更新").strip()
    primary_title = (payload.get("title") or header_title).strip()
    summary = str(payload.get("summary") or "").strip()
    content = str(payload.get("content") or "").strip()
    body_parts = [f"**{primary_title}**"]
    if summary:
        body_parts.append(summary)
    if content:
        body_parts.append(content)
    markdown = "\n\n".join(part for part in body_parts if part)
    urls = re.findall(r"https?://[^\s)]+", content)
    elements = [{"tag": "markdown", "content": markdown}]
    if urls:
        elements.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "打开团队差旅大盘"},
                "type": "primary",
                "url": urls[0],
            }
        )
    return {
        "schema": "2.0",
        "task_id": task_id,
        "topic": topic,
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": header_title},
        },
        "body": {"elements": elements},
    }


def materialize_legacy_travel_dashboard_card(payload_path: Path, *, payload: dict, task_id: str, topic: str) -> Path:
    card_payload = build_travel_dashboard_card_payload(payload, task_id=task_id, topic=topic)
    if payload_path.name.endswith(".post.json"):
        card_name = payload_path.name[:-10] + ".card.json"
    else:
        card_name = f"[{task_id}]_travel_dashboard.card.json"
    card_path = payload_path.with_name(card_name)
    card_path.write_text(json.dumps(card_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return card_path


def create_card_from_payload(payload_path: Path, *, task_id: str, topic: str) -> tuple[str, Path]:
    card_json = load_payload_json(payload_path)
    card_body = card_json["dsl"] if isinstance(card_json, dict) and "name" in card_json and "dsl" in card_json else card_json
    print(f"[INFO] 正在创建卡片实体（payload={payload_path.name}）...")
    result = dispatch_tool("lark_im_message", "lark_im_create_card", {"card_json": json.dumps(card_body, ensure_ascii=False)})
    normalized = normalize_result(result)
    print_result_or_exit(normalized, "创建卡片实体")
    data = normalized.get("data", {}) if isinstance(normalized, dict) else {}
    card_id = str(data.get("card_id") or normalized.get("card_id") or "").strip()
    if not card_id.isdigit():
        print("[ERROR] create_card 返回中未提取到有效 card_id", file=sys.stderr)
        sys.exit(1)
    receipt_path = write_card_receipt(task_id=task_id, topic=topic, card_id=card_id, payload_path=payload_path)
    print(f"[INFO] 已写入发射回执: {receipt_path}")
    return card_id, receipt_path


def build_receipt_path(task_id: str, card_id: str) -> Path:
    safe_task_id = task_id.replace("/", "_")
    return EPHEMERAL_DIR / f"[{safe_task_id}]_{card_id}{DEFAULT_RECEIPT_SUFFIX}"


def write_card_receipt(*, task_id: str, topic: str, card_id: str, payload_path: Path) -> Path:
    EPHEMERAL_DIR.mkdir(parents=True, exist_ok=True)
    receipt_path = build_receipt_path(task_id, card_id)
    receipt = {
        "task_id": task_id,
        "topic": topic,
        "card_id": card_id,
        "payload_path": str(payload_path),
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return receipt_path


def validate_card_receipt(*, card_id: str, task_id: str, topic: str) -> Path:
    receipt_path = build_receipt_path(task_id, card_id)
    if not receipt_path.exists():
        raise GuardrailViolation(
            f"未找到 card_id `{card_id}` 对应的发射回执：{receipt_path}。禁止发送来源不明的卡片。"
        )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("task_id") != task_id:
        raise GuardrailViolation(
            f"card receipt task_id 不匹配：期望 `{task_id}`，实际 `{receipt.get('task_id')}`"
        )
    if receipt.get("topic") != topic:
        raise GuardrailViolation(
            f"card receipt topic 不匹配：期望 `{topic}`，实际 `{receipt.get('topic')}`"
        )
    return receipt_path


def convert_content_from_file(payload_file: str, *, explicit_task_id: str | None, explicit_topic: str | None, allowed_suffixes=None) -> tuple[str, Path, str, str]:
    payload_path = ensure_payload_file(
        payload_file,
        explicit_task_id=explicit_task_id,
        allowed_suffixes=allowed_suffixes,
    )
    payload = load_payload_json(payload_path)
    task_id = validate_payload_task_metadata(payload, explicit_task_id=explicit_task_id)
    topic = assert_payload_topic(payload, explicit_topic=explicit_topic)
    return json.dumps(payload, ensure_ascii=False), payload_path, task_id, topic


def validate_share_chat_content(content: str) -> None:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"[ERROR] share_chat 消息 content 必须是 JSON 对象: {e}")
        sys.exit(1)

    if not isinstance(data, dict):
        print("[ERROR] share_chat 消息 content 必须是 JSON 对象")
        sys.exit(1)

    chat_id = data.get("chat_id")
    if not isinstance(chat_id, str) or not chat_id.strip():
        print("[ERROR] share_chat 消息 content.chat_id 不能为空")
        sys.exit(1)


def handle_preflight(args):
    args, task_id, topic, caller_role = parse_optional_flags(args)
    validate_caller_role(caller_role)
    if len(args) < 1:
        print("用法: python3 scripts/centralized_transmitter.py preflight <payload_file> --task-id=<task_id> --topic=<topic> --caller-role=<role>")
        sys.exit(1)

    _content, payload_path, resolved_task_id, resolved_topic = convert_content_from_file(
        args[0],
        explicit_task_id=task_id,
        explicit_topic=topic,
        allowed_suffixes=(".card.json", ".post.json", ".payload.json", ".json"),
    )
    print(
        json.dumps(
            {
                "ok": True,
                "payload_path": str(payload_path),
                "task_id": resolved_task_id,
                "topic": resolved_topic,
                "caller_role": caller_role or os.environ.get("AIME_CALLER_ROLE") or os.environ.get("CALLER_ROLE"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def handle_create_card(args):
    args, task_id, topic, caller_role = parse_optional_flags(args)
    validate_caller_role(caller_role)
    if len(args) < 1:
        print("用法: python3 scripts/centralized_transmitter.py create_card <payload_file> --task-id=<task_id> --topic=<topic> --caller-role=<role>")
        sys.exit(1)

    try:
        content_str, payload_path, resolved_task_id, resolved_topic = convert_content_from_file(
            args[0],
            explicit_task_id=task_id,
            explicit_topic=topic,
            allowed_suffixes=(".card.json", ".json"),
        )
    except (PayloadGuardError, GuardrailViolation) as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    try:
        card_data = json.loads(content_str)
    except json.JSONDecodeError as e:
        print(f"[ERROR] 无效的卡片 JSON: {e}")
        sys.exit(1)

    _ = card_data
    create_card_from_payload(payload_path, task_id=resolved_task_id, topic=resolved_topic)


def handle_send(args):
    args, task_id, topic, caller_role = parse_optional_flags(args)
    validate_caller_role(caller_role)
    if len(args) < 3:
        print("用法: python3 scripts/centralized_transmitter.py send <receiver_id> <msg_type> <content_or_card_id> [--id-type=...] [--task-id=...] [--topic=...] [--caller-role=...]")
        sys.exit(1)

    receiver_id = args[0]
    msg_type = args[1]
    content_raw = args[2]

    id_type = "email"
    private_fallback_email = None
    route_track = None
    reply_to = None
    aime_uuid = None
    source_chat_id = None
    source_sender = None
    source_timestamp = None
    source_content_hint = None
    for arg in args[3:]:
        if arg.startswith("--id-type="):
            id_type = arg.split("=", 1)[1]
        elif arg.startswith("--private-fallback-email="):
            private_fallback_email = arg.split("=", 1)[1].strip()
        elif arg.startswith("--route-track="):
            route_track = arg.split("=", 1)[1].strip().upper()
        elif arg.startswith("--reply-to="):
            reply_to = arg.split("=", 1)[1].strip()
        elif arg.startswith("--aime-uuid="):
            aime_uuid = arg.split("=", 1)[1].strip()
        elif arg.startswith("--chat-id="):
            source_chat_id = arg.split("=", 1)[1].strip()
        elif arg.startswith("--sender="):
            source_sender = arg.split("=", 1)[1].strip()
        elif arg.startswith("--timestamp="):
            source_timestamp = arg.split("=", 1)[1].strip()
        elif arg.startswith("--content-hint="):
            source_content_hint = arg.split("=", 1)[1].strip()

    if id_type not in ("email", "chat_id"):
        print(f"[ERROR] 不支持的 id-type: {id_type}，仅支持 email 和 chat_id")
        sys.exit(1)

    resolved_private_email = resolve_private_fallback_email(private_fallback_email)
    reroute_info = None

    if msg_type == "interactive":
        resolved_task_id = task_id or os.environ.get("AIME_TASK_ID") or os.environ.get("TASK_ID") or os.environ.get("RUN_ID")
        resolved_topic = topic or os.environ.get("AIME_TASK_TITLE") or os.environ.get("TASK_TITLE") or os.environ.get("AIME_MAIN_TASK") or os.environ.get("TASK_TOPIC")
        if not resolved_task_id or not resolved_topic:
            print("[ERROR] interactive 发送必须补齐 --task-id 与 --topic，用于校验 card receipt。")
            sys.exit(1)
        card_id = content_raw.strip()
        if not card_id.isdigit():
            print("[ERROR] 发送卡片消息必须使用 card_id（纯数字）。请先通过 create_card 获取。")
            sys.exit(1)
        try:
            content, payload_summary, _receipt = build_interactive_content_and_summary(
                card_id,
                task_id=resolved_task_id,
                topic=resolved_topic,
            )
            receiver_id, id_type, reroute_info = maybe_reroute_sensitive_delivery(
                receiver_id=receiver_id,
                id_type=id_type,
                content_text=payload_summary,
                private_fallback_email=resolved_private_email,
            )
        except (PayloadGuardError, GuardrailViolation) as e:
            print(f"[ERROR] {e}")
            sys.exit(1)
    else:
        try:
            allowed_suffixes = {
                "post": (".post.json", ".json"),
                "share_chat": (".payload.json", ".json"),
                "file": (".payload.json", ".json"),
                "audio": (".payload.json", ".json"),
            }.get(msg_type, (".payload.json", ".json"))
            content, payload_path, _task_id, _topic = convert_content_from_file(
                content_raw,
                explicit_task_id=task_id,
                explicit_topic=topic,
                allowed_suffixes=allowed_suffixes,
            )
            raw_payload = load_payload_json(payload_path)
            payload_summary = summarize_payload(raw_payload)
            receiver_id, id_type, reroute_info = maybe_reroute_sensitive_delivery(
                receiver_id=receiver_id,
                id_type=id_type,
                content_text=payload_summary,
                private_fallback_email=resolved_private_email,
            )
        except (PayloadGuardError, GuardrailViolation) as e:
            print(f"[ERROR] {e}")
            sys.exit(1)
        if msg_type == "share_chat":
            validate_share_chat_content(content)
        elif msg_type == "post" and is_legacy_travel_dashboard_payload(raw_payload):
            resolved_task_id = task_id or _task_id
            resolved_topic = topic or _topic
            card_payload_path = materialize_legacy_travel_dashboard_card(
                payload_path,
                payload=raw_payload,
                task_id=resolved_task_id,
                topic=resolved_topic,
            )
            print(f"[INFO] 已检测到旧版差旅大盘 post payload，自动升级为 interactive card：{card_payload_path}")
            card_id, _receipt_path = create_card_from_payload(
                card_payload_path,
                task_id=resolved_task_id,
                topic=resolved_topic,
            )
            content, payload_summary, _receipt = build_interactive_content_and_summary(
                card_id,
                task_id=resolved_task_id,
                topic=resolved_topic,
            )
            msg_type = "interactive"

    if reroute_info:
        print(f"[INFO] Error Boundary Routing 已生效: {json.dumps(reroute_info, ensure_ascii=False)}")
    if route_track == "L1":
        l1_reply_target = resolve_l1_reply_target(
            reply_to=reply_to,
            aime_uuid=aime_uuid,
            receiver_id=receiver_id,
            id_type=id_type,
            chat_id=source_chat_id,
            sender=source_sender,
            timestamp=source_timestamp,
            content_hint=source_content_hint or payload_summary,
        )
        send_l1_reply_or_l0_fallback(
            receiver_id=receiver_id,
            id_type=id_type,
            msg_type=msg_type,
            content=content,
            l1_reply_target=l1_reply_target,
        )
        return

    print(f"[INFO] 正在发送 {msg_type} 消息到 {receiver_id} ({id_type})...")
    result = dispatch_tool(
        "lark_im_message",
        "lark_im_send_message",
        {
            "receive_id": receiver_id,
            "receive_id_type": id_type,
            "msg_type": msg_type,
            "content": content,
        },
    )
    print_result_or_exit(result, "发送消息")


def handle_upload(args):
    args, _task_id, _topic, caller_role = parse_optional_flags(args)
    validate_caller_role(caller_role)
    if len(args) < 2:
        print("用法: python3 scripts/centralized_transmitter.py upload <file_path> <resource_type> --caller-role=<role>")
        sys.exit(1)

    file_path = os.path.abspath(args[0])
    resource_type = args[1]
    print(f"[INFO] 正在上传 {resource_type}: {file_path}...")
    result = dispatch_tool(
        "lark_im_message",
        "lark_im_upload_resource",
        {"file_path": file_path, "resource_type": resource_type},
    )
    print_result_or_exit(result, "上传资源")


def handle_webhook(args):
    args, task_id, topic, caller_role = parse_optional_flags(args)
    validate_caller_role(caller_role)
    if len(args) < 2:
        print("用法: python3 scripts/centralized_transmitter.py webhook <webhook_url> <payload_file> --task-id=<task_id> --topic=<topic> --caller-role=<role>")
        sys.exit(1)

    url = args[0]
    try:
        content_str, _payload_path, _resolved_task_id, _resolved_topic = convert_content_from_file(
            args[1],
            explicit_task_id=task_id,
            explicit_topic=topic,
            allowed_suffixes=(".card.json", ".json"),
        )
    except (PayloadGuardError, GuardrailViolation) as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    card_data = json.loads(content_str)
    payload = {"msg_type": "interactive", "card": card_data["dsl"]} if "name" in card_data and "dsl" in card_data else {"msg_type": "interactive", "card": card_data}

    print(f"[INFO] 正在发送 Webhook 消息到 {url[:50]}...")
    try:
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, verify=False, timeout=60)
        print(f"[RESULT] Status: {resp.status_code}, Body: {resp.text}")
        if resp.status_code < 200 or resp.status_code >= 300:
            print(f"[ERROR] Webhook 发送失败: HTTP {resp.status_code}", file=sys.stderr)
            sys.exit(1)
        try:
            body = resp.json()
        except ValueError:
            body = None
        if body is not None:
            failure = find_business_failure(body)
            if failure:
                print(f"[ERROR] Webhook 发送失败: {failure}", file=sys.stderr)
                sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Webhook 发送失败: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("用法: python3 scripts/centralized_transmitter.py [preflight|create_card|send|upload|webhook] ...")
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "preflight":
        handle_preflight(args)
    elif cmd == "create_card":
        handle_create_card(args)
    elif cmd == "send":
        handle_send(args)
    elif cmd == "upload":
        handle_upload(args)
    elif cmd == "webhook":
        handle_webhook(args)
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except GuardrailViolation as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)
