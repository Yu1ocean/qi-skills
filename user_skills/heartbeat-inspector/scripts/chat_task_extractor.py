#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests


class TaskExtractionError(RuntimeError):
    pass


DEFAULT_LLM_MODEL = os.environ.get("HEARTBEAT_TASK_EXTRACTOR_MODEL", "image-gen")
DEFAULT_MAX_CONTEXT_MESSAGES = int(os.environ.get("HEARTBEAT_TASK_CONTEXT_MAX_MESSAGES", "30"))
DEFAULT_TIMEOUT_SEC = int(os.environ.get("HEARTBEAT_TASK_LLM_TIMEOUT_SEC", "60"))
DEFAULT_MAX_RETRIES = int(os.environ.get("HEARTBEAT_TASK_LLM_MAX_RETRIES", "2"))

# Ack-Lock window: look for acknowledgements after task creation.
DEFAULT_ACK_LOCK_WINDOW_MINUTES = int(os.environ.get("HEARTBEAT_TASK_ACK_WINDOW_MINUTES", "180"))

# Use Asia/Shanghai as the default anchoring timezone for business communication.
TZ_SHANGHAI = timezone(timedelta(hours=8))

# A lightweight absolute-time format for downstream sheets/docs.
ABS_TIME_FMT = "%Y-%m-%d %H:%M"


def _runtime_api_base_url() -> str:
    base = (os.environ.get("IRIS_RUNTIME_API_BASE_URL") or "").strip()
    if not base:
        raise TaskExtractionError("missing env var: IRIS_RUNTIME_API_BASE_URL")
    return base.rstrip("/")


def _cloud_jwt() -> str:
    jwt = (os.environ.get("AIME_USER_CLOUD_JWT") or "").strip()
    if not jwt:
        raise TaskExtractionError("missing env var: AIME_USER_CLOUD_JWT (run with include_secrets=true)")
    return jwt


def _session_id() -> str:
    return (os.environ.get("AIME_SESSION_ID") or "").strip()


def _to_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False, default=str)


def _now_shanghai() -> datetime:
    return datetime.now(TZ_SHANGHAI)


def _parse_create_time(v: Any) -> Optional[datetime]:
    """Parse message create_time into timezone-aware datetime.

    Supports:
    - Unix seconds / milliseconds (int or digit string)
    - ISO format strings
    - Fallback: None
    """

    if v is None:
        return None

    if isinstance(v, (int, float)):
        ts = float(v)
        if ts > 1e12:  # ms
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=TZ_SHANGHAI)

    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if s.isdigit():
            ts = float(s)
            if ts > 1e12:
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, tz=TZ_SHANGHAI)

        # Try ISO parsing
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ_SHANGHAI)
            return dt.astimezone(TZ_SHANGHAI)
        except Exception:
            return None

    return None


def _is_absolute_time_str(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    v = s.strip()
    if not v:
        return False
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", v))


def _anchor_relative_due_time(raw: Optional[str], *, base_time: Optional[datetime]) -> Optional[str]:
    """Convert relative phrases into absolute time string.

    Rules are intentionally conservative. If the phrase cannot be anchored,
    return None so the caller can trigger suggestion_reply.
    """

    if not raw:
        return None

    text = raw.strip()
    if not text:
        return None

    # If already absolute, keep it.
    if _is_absolute_time_str(text):
        return text

    bt = base_time or _now_shanghai()

    # explicit HH:MM
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            # default to base date unless mentions tomorrow
            day = bt.date() + (timedelta(days=1) if ("明天" in text or "明日" in text) else timedelta(days=0))
            return datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ_SHANGHAI).strftime(ABS_TIME_FMT)

    # explicit "11点" or "11 点"
    m = re.search(r"(\d{1,2})\s*点", text)
    if m:
        hh = int(m.group(1))
        if 0 <= hh <= 23:
            mm = 0
            day = bt.date() + (timedelta(days=1) if ("明天" in text or "明日" in text) else timedelta(days=0))
            return datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ_SHANGHAI).strftime(ABS_TIME_FMT)

    # Common business anchors
    if "下班前" in text:
        day = bt.date()
        return datetime(day.year, day.month, day.day, 19, 0, tzinfo=TZ_SHANGHAI).strftime(ABS_TIME_FMT)

    if "明早" in text:
        day = bt.date() + timedelta(days=1)
        return datetime(day.year, day.month, day.day, 10, 0, tzinfo=TZ_SHANGHAI).strftime(ABS_TIME_FMT)

    if "明天" in text or "明日" in text:
        day = bt.date() + timedelta(days=1)
        # default to 10:00 if not specified
        return datetime(day.year, day.month, day.day, 10, 0, tzinfo=TZ_SHANGHAI).strftime(ABS_TIME_FMT)

    if "今天" in text or "今日" in text:
        day = bt.date()
        # default to 19:00 if not specified
        return datetime(day.year, day.month, day.day, 19, 0, tzinfo=TZ_SHANGHAI).strftime(ABS_TIME_FMT)

    # Un-anchorable vague phrases
    if any(k in text for k in ["尽快", "有空", "抽空", "稍后"]):
        return None

    # still cannot anchor
    return None


def _extract_message_text_full(msg: Dict[str, Any]) -> str:
    """Best-effort extract message text without truncation or whitespace normalization.

    Goal: preserve the raw text as much as possible.
    If a plain-text field is not available, fallback to JSON dump of content.
    """

    # Common shapes:
    # - {"content": "..."}
    # - {"content": {"text": "..."}}
    # - {"body": {"content": "..."}}
    for k in ["text", "content", "body", "message", "msg"]:
        v = msg.get(k)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, dict):
            for kk in ["text", "content", "body", "value"]:
                vv = v.get(kk)
                if isinstance(vv, str) and vv:
                    return vv

    # Some Feishu tool outputs already normalize to "content" as dict.
    c = msg.get("content")
    if c is not None:
        return _to_str(c)

    return _to_str(msg)


def _guess_sender_name(msg: Dict[str, Any]) -> str:
    for k in ["sender_name", "sender", "user_name", "name"]:
        v = msg.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, dict):
            n = v.get("name") or v.get("sender_name")
            if isinstance(n, str) and n.strip():
                return n.strip()
    return ""


def _guess_chat_name(msg: Dict[str, Any]) -> str:
    for k in ["chat_name", "group_name", "conversation_name"]:
        v = msg.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _ensure_task_name_bracketed(name: str) -> str:
    """Preserve task name as original text without auto-adding 【】.

    历史上这里会强制把任务名包装成【...】。
    现在恢复为“原样写入”：仅做首尾空白清理，不再补括号、也不改写原文。
    """

    return (name or "").strip()


_BRACKET_TASK_RE = re.compile(r"【[^【】]+】")

_GENERIC_OWNER_HINTS = [
    "大家",
    "各负责类目同学",
    "各负责类目的同学",
    "相关同学",
    "各位",
    "全体",
    "全体成员",
]


def _extract_bracketed_task_names(text: str) -> List[str]:
    """Return all 【...】 phrases in order (de-duplicated)."""

    if not text:
        return []

    names = _BRACKET_TASK_RE.findall(text)
    if not names:
        return []

    seen: set[str] = set()
    out: List[str] = []
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def _extract_due_time_from_task_name(task_name: str) -> Optional[str]:
    """Extract due time hint from task_name parentheses, e.g. （明日会前）."""

    if not task_name:
        return None

    m = re.findall(r"[（(]([^（）()]{1,80})[)）]", task_name)
    if not m:
        return None

    v = (m[-1] or "").strip()
    return v or None


def _status_from_trigger_word(text: str) -> Optional[Dict[str, Any]]:
    """Parse magic words (State-Triggers) from message text."""

    if not text:
        return None

    # Order matters: more specific first.
    m = re.search(r"/(延期至|延期到)([^\s]+)", text)
    if m:
        return {"trigger": m.group(0), "status": "postponed", "postponed_to": m.group(2)}

    if "/阻塞" in text:
        return {"trigger": "/阻塞", "status": "blocked"}

    if "/done" in text or "/完成" in text:
        return {"trigger": "/done" if "/done" in text else "/完成", "status": "done"}

    return None


def _is_ack_text(text: str) -> bool:
    if not text:
        return False
    s = text.strip().lower()
    if not s:
        return False

    # Common acknowledgements and lightweight receipts.
    ack_keywords = [
        "收到",
        "1",
        "ok",
        "okay",
        "好的",
        "明白",
        "已收到",
        "👌",
        "👍",
        "安排",
    ]

    if any(k in text for k in ["👌", "👍"]):
        return True

    for k in ack_keywords:
        if k == "1":
            if s == "1":
                return True
            continue
        if k in s:
            return True

    return False


def _apply_ack_lock(
    *,
    task: Dict[str, Any],
    view_messages: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Mark task as acked/pending by sniffing acknowledgements in later messages."""

    owners = task.get("owners")
    owners_set = set([o for o in owners if isinstance(o, str) and o.strip()]) if isinstance(owners, list) else set()

    src_ids = task.get("source_message_ids")
    if not isinstance(src_ids, list) or not src_ids:
        return task

    src_id = str(src_ids[0])

    idx_map = {m.get("message_id"): i for i, m in enumerate(view_messages)}
    src_idx = idx_map.get(src_id)

    src_ct = None
    if src_idx is not None:
        src_ct = _parse_create_time(view_messages[src_idx].get("create_time"))

    ack_deadline = (src_ct + timedelta(minutes=DEFAULT_ACK_LOCK_WINDOW_MINUTES)) if src_ct else None

    ack_info: Optional[Dict[str, Any]] = None
    if src_idx is not None:
        for m in view_messages[src_idx + 1 :]:
            sender = (m.get("sender") or "").strip() if isinstance(m.get("sender"), str) else ""
            text = m.get("text") or ""
            ct = _parse_create_time(m.get("create_time"))

            if ack_deadline and ct and ct > ack_deadline:
                break

            if owners_set and sender not in owners_set:
                continue

            if _is_ack_text(text):
                ack_info = {
                    "message_id": m.get("message_id"),
                    "sender": sender,
                    "create_time": m.get("create_time"),
                    "text": text,
                }
                break

    if ack_info:
        task["ack_lock"] = {
            "status": "acked",
            "tag": "",
            "evidence": "在上下文中检测到责任人已认领/回复",
            "ack_message": ack_info,
        }
    else:
        task["ack_lock"] = {
            "status": "pending",
            "tag": "[⚠️待接单/未响应]",
            "evidence": "未在时间窗口内检测到责任人认领（收到/1/OK/表情等）",
        }

    return task


def _extract_owners_from_text(text: str) -> Tuple[List[str], List[Dict[str, str]], str]:
    """Extract owners from raw text.

    - Explicit @ mentions are extracted first.
    - Generic roles (大家/相关同学/全体…) are also included if present.
    """

    owners: List[str] = []
    mapping: List[Dict[str, str]] = []

    if not text:
        return owners, mapping, "none"

    # @mentions (best-effort)
    mentions = re.findall(r"[@＠]([A-Za-z0-9_\-\u4e00-\u9fff]{1,32})", text)
    for raw in mentions:
        name = (raw or "").strip()
        if not name:
            continue
        if name in {"全体", "全体成员", "全体同学", "全员"}:
            name = "全体成员"
        if name not in owners:
            owners.append(name)

    # Generic roles
    for hint in _GENERIC_OWNER_HINTS:
        if hint in text and hint not in owners:
            owners.append(hint)

    for o in owners:
        mapping.append({"owner": o, "scope": ""})

    if not owners:
        status = "none"
    elif any(h in owners for h in _GENERIC_OWNER_HINTS):
        status = "partial"
    else:
        status = "full"

    return owners, mapping, status


def _has_due_time(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    return True


def _has_owners(v: Any) -> bool:
    if isinstance(v, list):
        return any(isinstance(x, str) and x.strip() for x in v) or any(isinstance(x, dict) for x in v)
    if isinstance(v, str):
        return bool(v.strip())
    return False


def _default_suggestion_reply(missing: List[str]) -> str:
    parts: List[str] = []
    if "owners" in missing:
        parts.append("负责人（可以直接 @ 一下具体同学）")
    if "due_time" in missing:
        parts.append("最晚截止时间 / DDL")
    if "action" in missing:
        parts.append("需要做的动作（例如：确认/整理/输出/定稿）")
    if not parts:
        parts.append("关键信息")

    return (
        "收到～为了方便大家后续跟进，建议按【动词+交付物/事项+时间节点】补全一下："
        + "、".join(parts)
        + "。另外也建议在消息里用【任务名称】格式明确指出待办。谢谢～"
    )


def _postprocess_task(
    *,
    task: Dict[str, Any],
    source_messages_full: List[Dict[str, Any]],
) -> Dict[str, Any]:
    # Anchor override: if the source text already contains 【任务名】, treat it as the highest-priority anchor.
    anchors: List[str] = []
    for m in source_messages_full:
        anchors.extend(_extract_bracketed_task_names(m.get("text") or ""))

    if anchors:
        # Direct inheritance (do NOT rewrite)
        task["task_name"] = anchors[0]
        task["summary"] = anchors[0]
        if not _has_due_time(task.get("due_time")):
            task["due_time"] = _extract_due_time_from_task_name(anchors[0])

        ev = task.get("evidence")
        if not isinstance(ev, list):
            ev = []
        ev.insert(0, "消息中包含【】锚点，任务名直接继承原话")
        task["evidence"] = ev

    else:
        # Preserve extractor output as original text; no auto-bracketing rewrite.
        summary = _to_str(task.get("summary") or "")
        task_name = _to_str(task.get("task_name") or summary)
        task["task_name"] = _ensure_task_name_bracketed(task_name)
        task["summary"] = task.get("task_name")

    # 100% source fidelity: override with code-collected raw messages
    task["source_messages_full"] = source_messages_full
    task["source_text_full"] = "\n".join([m.get("text") or "" for m in source_messages_full])

    # Due time anchoring: enforce absolute time where possible.
    base_time = _parse_create_time(source_messages_full[0].get("create_time")) if source_messages_full else None
    due_raw = task.get("due_time")
    if isinstance(due_raw, str):
        due_raw = due_raw.strip()
    if isinstance(due_raw, str) and due_raw:
        anchored = _anchor_relative_due_time(due_raw, base_time=base_time)
        if anchored:
            task["due_time"] = anchored
        else:
            # If provided but cannot be physically anchored, clear it to force reverse reminder.
            if not _is_absolute_time_str(due_raw):
                task["due_time"] = None

    # Suggestion reply if missing key fields / un-anchorable time
    missing: List[str] = []
    if not _has_owners(task.get("owners")):
        missing.append("owners")

    # If due_time exists but is not absolute, treat as missing (Relative Time Anchoring rule)
    if not _has_due_time(task.get("due_time")):
        missing.append("due_time")
    elif not _is_absolute_time_str(task.get("due_time")):
        missing.append("due_time")

    # action signal: try to infer from task_name prefix, keep this conservative
    if not task.get("task_name"):
        missing.append("action")

    if task.get("is_task") is True and missing:
        task.setdefault("missing_fields", missing)
        if not isinstance(task.get("suggestion_reply"), str) or not str(task.get("suggestion_reply") or "").strip():
            task["suggestion_reply"] = _default_suggestion_reply(missing)

    return task


def _call_llm_json(prompt_text: str, *, model: str) -> Dict[str, Any]:
    url = f"{_runtime_api_base_url()}/llmproxy/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Byte-Cloud-JWT {_cloud_jwt()}",
    }

    payload = {
        "stream": False,
        "model": model,
        "temperature": 0.0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt_text,
                    }
                ],
            }
        ],
        "max_tokens": 6000,
        "response_modalities": ["text"],
        "extra_options": {
            "session_id": _session_id(),
            "trace_id": "",
            "tag": "heartbeat_task_extractor",
        },
    }

    last_err: Optional[str] = None
    for attempt in range(DEFAULT_MAX_RETRIES + 1):
        try:
            resp = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=DEFAULT_TIMEOUT_SEC,
                proxies={"http": None, "https": None},
            )
            resp.raise_for_status()
            data = resp.json()
            content = (((data.get("choices") or [])[0] or {}).get("message") or {}).get("content")
            if not isinstance(content, str) or not content.strip():
                raise TaskExtractionError(f"empty llm content: {content}")

            # Some models may wrap JSON in markdown; strip conservatively.
            txt = content.strip()
            if txt.startswith("```"):
                txt = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", txt)
                txt = re.sub(r"\n```$", "", txt)
                txt = txt.strip()

            try:
                return json.loads(txt)
            except Exception as e:
                raise TaskExtractionError(f"llm returned non-json: {e}; raw={txt[:800]}")

        except Exception as e:
            last_err = str(e)
            if attempt >= DEFAULT_MAX_RETRIES:
                break
            time.sleep(1.0)

    raise TaskExtractionError(last_err or "unknown llm error")


def build_task_extraction_prompt(*, chat_title: str, payload: Dict[str, Any]) -> str:
    # NOTE: Keep prompt stable and explicit; rely on code to preserve source text.
    return (
        "你是一个‘群聊任务提取器’。\n"
        "请从输入的群聊消息中识别是否存在需要录入的任务，并输出严格的 JSON（不要输出 Markdown、不要输出解释）。\n\n"
        "【强制规则】\n"
        "1) 【】锚点高优识别：如果任意一条消息 text 中包含被【】包裹的短语（例如：大家看下文档，【审阅SKM和HIPO商家权益一页纸并定稿（明日会前）】@全体），必须最高优判定为任务（is_task=true）。\n"
        "   - 提取出的 task_name/summary 必须直接继承并等于该【...】原话（包含【】），不得改写或重新总结。\n"
        "   - 若同一条消息包含多个【...】，允许输出多个 tasks。\n"
        "2) 兜底提炼：若判定为任务但消息中没有【】锚点，才按照 [核心动词]+[交付物/事项]+[时间节点] 生成任务名，并在最终输出时补上【】。\n"
        "3) 原文 100% 保真：你可以基于 source_messages_full 进行判断，但不得改写原文内容。\n"
        "4) 责任人穷尽提取：必须提取所有被 @ 的人，以及‘大家/各负责类目同学/相关同学/全体’等泛指角色，输出 owners 与 owner_mapping。\n"
        "5) 信息补全检测：若判定为任务但缺少关键信息（如无明确 due_time 或 owners），必须输出 suggestion_reply（友好、可直接复制粘贴的提醒话术），并可提示建议用【任务名称】格式明确指出待办。\n"
        "6) 赛博时钟锚定：你必须基于每条消息的 create_time（绝对时间戳）把‘下班前/明早/明天 11 点’等相对时间翻译为绝对时间字符串 YYYY-MM-DD HH:MM；如果出现‘尽快/有空’等无法锚定的时态，due_time 必须置空，并触发 suggestion_reply 提醒补充明确 DDL。\n\n"
        "【输出 JSON Schema】\n"
        "{\n"
        "  \"tasks\": [\n"
        "    {\n"
        "      \"is_task\": true|false,\n"
        "      \"task_name\": \"【...】\",\n"
        "      \"summary\": \"【...】\",\n"
        "      \"task_type\": \"\",\n"
        "      \"assigner\": \"\",\n"
        "      \"owners\": [\"\"],\n"
        "      \"owner_mapping\": [{\"owner\":\"\",\"scope\":\"\"}],\n"
        "      \"owner_resolution_status\": \"full|partial|none\",\n"
        "      \"due_time\": \"YYYY-MM-DD HH:MM\"|null,\n"
        "      \"deliverable\": \"\"|null,\n"
        "      \"source_message_ids\": [\"\"],\n"
        "      \"suggestion_reply\": \"\"|null,\n"
        "      \"evidence\": [\"\"]\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"chat_title: {chat_title}\n"
        "input_json: "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    )


def extract_tasks_from_chat_messages(
    *,
    chat_title: str,
    messages: Sequence[Dict[str, Any]],
    new_message_ids: Sequence[str],
    model: str = DEFAULT_LLM_MODEL,
) -> List[Dict[str, Any]]:
    """Extract tasks from a chat message list (batch mode).

    Output includes additional human-collaboration fields:
    - 【接单闭环追踪 (Ack-Lock)】: task.ack_lock
    - 【赛博时钟锚定 (Relative Time Anchoring)】: due_time forced into absolute format

    - messages: full fetched window (any order is OK; will sort by create_time/message_id)
    - new_message_ids: ids that are considered "new" (only tasks using these ids should be emitted)

    Return: list of task dicts (already post-processed, source fields overridden for fidelity).
    """

    msgs = [m for m in messages if isinstance(m, dict)]
    msgs.sort(key=lambda m: (m.get("create_time") or "", m.get("message_id") or ""))

    new_id_set = set(str(x) for x in new_message_ids)

    # Build a compact message view for the LLM.
    view: List[Dict[str, Any]] = []
    for m in msgs[-DEFAULT_MAX_CONTEXT_MESSAGES :]:
        mid = str(m.get("message_id") or "")
        if not mid:
            continue
        view.append(
            {
                "message_id": mid,
                "create_time": m.get("create_time"),
                "sender": _guess_sender_name(m),
                "chat_id": m.get("chat_id"),
                "chat_name": _guess_chat_name(m),
                "chat_link": m.get("chat_link"),
                "message_link": m.get("message_link"),
                "jump_link": m.get("jump_link"),
                "text": _extract_message_text_full(m),
                "is_new": mid in new_id_set,
                "raw": m,
            }
        )

    msg_by_id: Dict[str, Dict[str, Any]] = {m["message_id"]: m for m in view if isinstance(m.get("message_id"), str)}

    final: List[Dict[str, Any]] = []

    # 0) High-priority: if a NEW message already contains 【任务名称】, treat it as a task anchor.
    llm_new_ids: List[str] = []
    for mid in [str(x) for x in new_message_ids]:
        mv = msg_by_id.get(mid)
        if not mv:
            continue

        text = mv.get("text") or ""
        anchors = _extract_bracketed_task_names(text)
        if anchors:
            owners, owner_mapping, owner_status = _extract_owners_from_text(text)

            for anchor in anchors:
                task = {
                    "is_task": True,
                    "task_name": anchor,
                    "summary": anchor,
                    "task_type": "",
                    "assigner": mv.get("sender") or "",
                    "owners": owners,
                    "owner_mapping": owner_mapping,
                    "owner_resolution_status": owner_status,
                    "due_time": _anchor_relative_due_time(
                        _extract_due_time_from_task_name(anchor) or _extract_due_time_from_task_name(text),
                        base_time=_parse_create_time(mv.get("create_time")),
                    ),
                    "deliverable": None,
                    "source_message_ids": [mid],
                    "suggestion_reply": None,
                    "evidence": ["消息中包含【】锚点，按规则高优判定为任务"],
                }

                source_messages_full = [
                    {
                        "message_id": mv.get("message_id"),
                        "sender": mv.get("sender"),
                        "chat_id": mv.get("chat_id"),
                        "chat_name": mv.get("chat_name"),
                        "chat_link": mv.get("chat_link"),
                        "message_link": mv.get("message_link"),
                        "jump_link": mv.get("jump_link"),
                        "create_time": mv.get("create_time"),
                        "text": mv.get("text"),
                    }
                ]

                final.append(
                    _apply_ack_lock(
                        task=_postprocess_task(task=task, source_messages_full=source_messages_full),
                        view_messages=view,
                    )
                )
        else:
            llm_new_ids.append(mid)

    # If all new messages were anchor-tasks, skip LLM.
    if not llm_new_ids:
        return final

    payload = {
        "new_message_ids": llm_new_ids,
        "messages": view,
        "now": _now_shanghai().strftime(ABS_TIME_FMT),
        "timezone": "Asia/Shanghai",
    }

    prompt = build_task_extraction_prompt(chat_title=chat_title, payload=payload)
    result = _call_llm_json(prompt, model=model)

    tasks = result.get("tasks") if isinstance(result, dict) else None
    if not isinstance(tasks, list):
        raise TaskExtractionError(f"unexpected llm schema (missing tasks): {result}")

    for t in tasks:
        if not isinstance(t, dict):
            continue

        is_task = t.get("is_task")
        if is_task is not True:
            continue

        ids = t.get("source_message_ids")
        if not isinstance(ids, list) or not ids:
            # fallback: treat as the newest new message
            ids = [payload["new_message_ids"][-1]] if payload["new_message_ids"] else []

        # Only emit tasks that are based on new messages.
        if not any(str(i) in set(payload["new_message_ids"]) for i in ids):
            continue

        source_messages_full: List[Dict[str, Any]] = []
        for mid in ids:
            mv = msg_by_id.get(str(mid))
            if not mv:
                continue
            source_messages_full.append(
                {
                    "message_id": mv.get("message_id"),
                    "sender": mv.get("sender"),
                    "chat_id": mv.get("chat_id"),
                    "chat_name": mv.get("chat_name"),
                    "chat_link": mv.get("chat_link"),
                    "message_link": mv.get("message_link"),
                    "jump_link": mv.get("jump_link"),
                    "create_time": mv.get("create_time"),
                    "text": mv.get("text"),
                }
            )

        final.append(
            _apply_ack_lock(
                task=_postprocess_task(task=t, source_messages_full=source_messages_full),
                view_messages=view,
            )
        )

    return final


def extract_status_updates_from_messages(
    *,
    view_messages: List[Dict[str, Any]],
    known_task_names: Sequence[str],
) -> List[Dict[str, Any]]:
    """Extract status updates based on magic words and anchors.

    A status update is emitted when:
    - message contains magic word (/done, /阻塞, /延期至...)
    - AND it can be associated to a task by 【任务名】 anchor or known_task_names match.

    Output schema:
    {
      "task_name": "【...】",
      "new_status": "done|blocked|postponed",
      "trigger": "/done|/阻塞|/延期至X",
      "postponed_to": "..."|null,
      "postponed_to_time": "YYYY-MM-DD HH:MM"|null,
      "message_id": "...",
      "sender": "...",
      "create_time": "...",
      "source_text_full": "..."
    }
    """

    known = [k for k in known_task_names if isinstance(k, str) and k.strip()]

    updates: List[Dict[str, Any]] = []
    for m in view_messages:
        text = m.get("text") or ""
        trig = _status_from_trigger_word(text)
        if not trig:
            continue

        anchors = _extract_bracketed_task_names(text)
        task_names: List[str] = []
        if anchors:
            task_names = anchors
        else:
            for k in known:
                if k and k in text:
                    task_names.append(k)

        if not task_names:
            continue

        for tn in task_names:
            upd: Dict[str, Any] = {
                "task_name": tn,
                "new_status": trig.get("status"),
                "trigger": trig.get("trigger"),
                "postponed_to": trig.get("postponed_to"),
                "postponed_to_time": None,
                "message_id": m.get("message_id"),
                "sender": m.get("sender"),
                "chat_id": m.get("chat_id"),
                "chat_name": m.get("chat_name"),
                "chat_link": m.get("chat_link"),
                "message_link": m.get("message_link"),
                "jump_link": m.get("jump_link"),
                "create_time": m.get("create_time"),
                "source_text_full": text,
            }

            if upd.get("new_status") == "postponed" and isinstance(upd.get("postponed_to"), str):
                base_time = _parse_create_time(m.get("create_time"))
                upd["postponed_to_time"] = _anchor_relative_due_time(str(upd.get("postponed_to")), base_time=base_time)

            updates.append(upd)

    return updates
