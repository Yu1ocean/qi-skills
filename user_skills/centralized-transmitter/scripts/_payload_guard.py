#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Payload guard for zero-trust centralized Feishu delivery."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, List, Optional

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
EPHEMERAL_DIR = (WORKSPACE_ROOT / ".ephemeral_pool").resolve()
STATIC_FILENAMES = {"card.json", "post.json", "payload.json"}
TASK_ID_ENV_KEYS = ("AIME_TASK_ID", "TASK_ID", "RUN_ID")
TOPIC_ENV_KEYS = ("AIME_TASK_TITLE", "TASK_TITLE", "AIME_MAIN_TASK", "TASK_TOPIC")
CALLER_ROLE_ENV_KEYS = ("AIME_CALLER_ROLE", "CALLER_ROLE")
ALLOWED_CALLER_ROLES = {"main", "comm-agent", "communication-agent"}
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
ASCII_RE = re.compile(r"[a-z0-9]+")


class PayloadGuardError(RuntimeError):
    """Raised when a payload violates centralized delivery constraints."""


def resolve_current_task_id(explicit_task_id: Optional[str] = None) -> Optional[str]:
    if explicit_task_id and explicit_task_id.strip():
        return explicit_task_id.strip()
    for key in TASK_ID_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def resolve_current_topic(explicit_topic: Optional[str] = None) -> Optional[str]:
    if explicit_topic and explicit_topic.strip():
        return explicit_topic.strip()
    for key in TOPIC_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def resolve_caller_role(explicit_role: Optional[str] = None) -> Optional[str]:
    if explicit_role and explicit_role.strip():
        return explicit_role.strip().lower()
    for key in CALLER_ROLE_ENV_KEYS:
        value = os.environ.get(key, "").strip().lower()
        if value:
            return value
    return None


def validate_caller_role(explicit_role: Optional[str] = None) -> str:
    role = resolve_caller_role(explicit_role)
    if not role:
        raise PayloadGuardError(
            "缺少调用者角色声明。请通过 `--caller-role=main|comm-agent`（或环境变量 AIME_CALLER_ROLE/CALLER_ROLE）传入。"
        )
    if role not in ALLOWED_CALLER_ROLES:
        raise PayloadGuardError(
            f"调用者角色 `{role}` 不被允许。此技能仅允许 Aime 主进程或专职通信特工调用。"
        )
    return role


def parse_optional_flags(args: List[str]) -> tuple[List[str], Optional[str], Optional[str], Optional[str]]:
    remaining: List[str] = []
    task_id: Optional[str] = None
    topic: Optional[str] = None
    caller_role: Optional[str] = None
    for arg in args:
        if arg.startswith("--task-id="):
            task_id = arg.split("=", 1)[1].strip()
        elif arg.startswith("--topic="):
            topic = arg.split("=", 1)[1].strip()
        elif arg.startswith("--caller-role="):
            caller_role = arg.split("=", 1)[1].strip()
        else:
            remaining.append(arg)
    return remaining, task_id, topic, caller_role


def _normalized_text(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", lowered)
    return lowered


def derive_keywords(topic: str) -> List[str]:
    normalized = _normalized_text(topic)
    keywords: List[str] = []
    if len(normalized) >= 2:
        keywords.append(normalized)

    seen = set(keywords)
    for token in CHINESE_RE.findall(topic):
        normalized_token = _normalized_text(token)
        if len(normalized_token) >= 2 and normalized_token not in seen:
            keywords.append(normalized_token)
            seen.add(normalized_token)
    for token in ASCII_RE.findall(topic.lower()):
        if len(token) >= 2 and token not in seen:
            keywords.append(token)
            seen.add(token)
    return keywords


def _extract_text_chunks(value: Any) -> List[str]:
    chunks: List[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"content", "text", "title", "name", "summary", "subtitle", "task_id", "taskId", "run_id"} and isinstance(item, str):
                chunks.append(item)
            chunks.extend(_extract_text_chunks(item))
    elif isinstance(value, list):
        for item in value:
            chunks.extend(_extract_text_chunks(item))
    elif isinstance(value, str):
        chunks.append(value)
    return chunks


def summarize_payload(payload: Any) -> str:
    return "\n".join(chunk for chunk in _extract_text_chunks(payload) if chunk and chunk.strip())


def ensure_payload_file(payload_input: str, *, explicit_task_id: Optional[str], allowed_suffixes: Optional[Iterable[str]] = None) -> Path:
    payload_path = Path(payload_input).expanduser()
    if not payload_path.is_absolute():
        payload_path = (Path.cwd() / payload_path).resolve()
    else:
        payload_path = payload_path.resolve()

    if not payload_path.exists() or not payload_path.is_file():
        raise PayloadGuardError(
            "payload 必须以文件路径传入，且文件必须已存在。禁止直接传入 JSON 字符串。"
        )

    filename = payload_path.name
    if filename in STATIC_FILENAMES:
        raise PayloadGuardError(
            f"检测到静态 payload 文件名 `{filename}`。请改用 `.ephemeral_pool/[TASK_ID]_[TOPIC_SLUG].*.json`。"
        )

    try:
        payload_path.relative_to(EPHEMERAL_DIR)
    except ValueError as exc:
        raise PayloadGuardError(
            f"payload 必须位于 `{EPHEMERAL_DIR}` 下，当前路径不合规：{payload_path}"
        ) from exc

    task_id = resolve_current_task_id(explicit_task_id)
    if not task_id:
        raise PayloadGuardError(
            "缺少任务唯一标识。请通过 `--task-id=...`（或环境变量 AIME_TASK_ID/TASK_ID）传入。"
        )

    if task_id not in filename:
        raise PayloadGuardError(
            f"payload 文件名必须包含当前 task_id `{task_id}`，当前文件名：{filename}"
        )

    if allowed_suffixes and not any(filename.endswith(suffix) for suffix in allowed_suffixes):
        suffix_text = ", ".join(allowed_suffixes)
        raise PayloadGuardError(
            f"payload 文件后缀不合规。允许后缀：{suffix_text}；当前文件名：{filename}"
        )

    return payload_path


def load_payload_json(payload_path: Path) -> Any:
    try:
        return json.loads(payload_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PayloadGuardError(f"payload 不是合法 JSON：{exc}") from exc


def validate_payload_task_metadata(payload: Any, *, explicit_task_id: Optional[str]) -> str:
    task_id = resolve_current_task_id(explicit_task_id)
    if not task_id:
        raise PayloadGuardError("无法建立 task_id 约束，禁止继续发送。")

    if isinstance(payload, dict):
        candidates = []
        for key in ("task_id", "taskId", "run_id"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append((key, value.strip()))
        if not candidates:
            return task_id
        mismatch = [f"{key}={value}" for key, value in candidates if value != task_id]
        if mismatch:
            raise PayloadGuardError(
                f"payload 内部任务标识与当前 task_id 不匹配：期望 `{task_id}`，实际 {', '.join(mismatch)}"
            )
    return task_id


def assert_payload_topic(payload: Any, *, explicit_topic: Optional[str]) -> str:
    topic = resolve_current_topic(explicit_topic)
    if not topic:
        raise PayloadGuardError(
            "缺少主题断言上下文。请通过 `--topic=...`（或环境变量 AIME_TASK_TITLE/TASK_TITLE）传入当前主任务意图。"
        )

    summary = summarize_payload(payload)
    normalized_summary = _normalized_text(summary)
    if not normalized_summary:
        raise PayloadGuardError("payload 主题断言失败：未能从 payload 中提取标题/摘要文本。")

    keywords = derive_keywords(topic)
    matched = [keyword for keyword in keywords if keyword in normalized_summary]
    if not matched:
        preview = summary[:160].replace("\n", " ")
        raise PayloadGuardError(
            f"payload 主题断言失败：当前任务主题 `{topic}` 未在 payload 标题/摘要中命中。payload 摘要预览：{preview}"
        )
    return topic
