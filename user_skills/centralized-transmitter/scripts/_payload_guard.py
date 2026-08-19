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
            # v1.3 根因修复：`task_id` / `taskId` / `run_id` 属于元数据，绝不能被当成
            # 「可提取主题素材」，否则顶层字段污染时主题断言会误判通过。
            if isinstance(item, str):
                # 只有白名单键的字符串才算「可提取主题素材」；元数据字符串
                # （task_id / topic / run_id 等）必须被彻底忽略。
                if key in {"content", "text", "title", "name", "summary", "subtitle"}:
                    chunks.append(item)
                continue
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


# ---------------------------------------------------------------------------
# v1.3 结构护栏：post payload 顶层字段白名单（GUARD-POST-001~005）
#
# P1 事故根因：post payload 的 `content` 顶层同时出现 `task_id` / `topic` 等元数据
# 字段与语种键 `zh_cn`，飞书返回 `230001 invalid message content`。原护栏只做
# 「内容断言」，无法拦结构污染，因此新增结构护栏，且必须先于内容/主题断言执行。
# ---------------------------------------------------------------------------

POST_LANG_KEYS = {
    "zh_cn",
    "zh_hk",
    "zh_tw",
    "en_us",
    "ja_jp",
    "ko_kr",
    "th_th",
    "id_id",
    "vi_vn",
    "fr_fr",
    "de_de",
    "es_es",
    "it_it",
    "pt_br",
    "ru_ru",
    "hi_in",
    "ar_sa",
}

POST_GUARD_FIX_HINT = (
    "修复建议：post payload 的 content 顶层只允许语种键（如 zh_cn/en_us/ja_jp），"
    "元数据（task_id/topic/run_id 等）必须放在 payload 顶层而非 content 内，"
    "语种块结构必须为 {\"title\": str?, \"content\": [[{\"tag\": ...}]]}。"
)


def _is_legacy_bridge_shape(payload: Any) -> bool:
    """v1.2 旧版差旅大盘摘要 payload（title/summary/content 均为字符串）。

    该形态本身不符合飞书 post schema，由发送阶段的兼容桥自动升级为 interactive
    card，因此结构护栏对其显式豁免（豁免范围窄且有明确升级路径，不构成绕过）。
    """

    if not isinstance(payload, dict):
        return False
    if payload.get("msg_type") != "post":
        return False
    return all(
        isinstance(payload.get(key), str) and payload.get(key).strip()
        for key in ("title", "summary", "content")
    )


def looks_like_post_payload(payload: Any, *, filename: str = "") -> bool:
    if filename.endswith(".post.json"):
        return True
    if not isinstance(payload, dict):
        return False
    if str(payload.get("msg_type") or "").strip() == "post":
        return True
    if any(key in POST_LANG_KEYS for key in payload.keys()):
        return True
    content = payload.get("content")
    if isinstance(content, dict) and any(key in POST_LANG_KEYS for key in content.keys()):
        return True
    return False


def assert_post_content_shape(payload: Any) -> str:
    """结构护栏：断言 post payload 的 content 顶层只含合法语种键与合法语种块。

    返回 "ok" 或 "legacy_bridge"；违规一律 raise PayloadGuardError。
    """

    if _is_legacy_bridge_shape(payload):
        return "legacy_bridge"

    if not isinstance(payload, dict):
        raise PayloadGuardError(
            f"GUARD-POST-001 post payload 必须是 JSON 对象，实际类型：{type(payload).__name__}。{POST_GUARD_FIX_HINT}"
        )

    content = payload.get("content")
    if content is None and any(key in POST_LANG_KEYS for key in payload.keys()):
        # payload 本体即 content（顶层直接是语种键）
        content = payload
    if not isinstance(content, dict):
        raise PayloadGuardError(
            "GUARD-POST-001 post payload 缺少合法 `content` 对象（当前："
            f"{type(content).__name__}）。{POST_GUARD_FIX_HINT}"
        )

    keys = list(content.keys())
    if not keys:
        raise PayloadGuardError(
            f"GUARD-POST-003 post payload 的 content 顶层为空，未发现任何语种键。{POST_GUARD_FIX_HINT}"
        )

    illegal = [key for key in keys if key not in POST_LANG_KEYS]
    if illegal:
        raise PayloadGuardError(
            "GUARD-POST-002 post payload 的 content 顶层出现非语种键（顶层字段污染）："
            f"{', '.join(sorted(illegal))}；合法语种键示例：zh_cn/en_us/ja_jp。{POST_GUARD_FIX_HINT}"
        )

    for lang in keys:
        block = content[lang]
        if not isinstance(block, dict):
            raise PayloadGuardError(
                f"GUARD-POST-004 语种块 `{lang}` 结构非法：必须是对象，实际 {type(block).__name__}。{POST_GUARD_FIX_HINT}"
            )
        title = block.get("title")
        if title is not None and not isinstance(title, str):
            raise PayloadGuardError(
                f"GUARD-POST-004 语种块 `{lang}` 的 `title` 必须是字符串，实际 {type(title).__name__}。{POST_GUARD_FIX_HINT}"
            )
        body = block.get("content")
        if not isinstance(body, list) or not body:
            raise PayloadGuardError(
                f"GUARD-POST-004 语种块 `{lang}` 的 `content` 必须是非空「段落列表的列表」，"
                f"实际 {type(body).__name__}。{POST_GUARD_FIX_HINT}"
            )
        for index, paragraph in enumerate(body):
            if not isinstance(paragraph, list):
                raise PayloadGuardError(
                    f"GUARD-POST-004 语种块 `{lang}` 的第 {index + 1} 个段落必须是列表，"
                    f"实际 {type(paragraph).__name__}。{POST_GUARD_FIX_HINT}"
                )
            for element in paragraph:
                if not isinstance(element, dict):
                    raise PayloadGuardError(
                        f"GUARD-POST-005 语种块 `{lang}` 第 {index + 1} 段内的元素必须是对象，"
                        f"实际 {type(element).__name__}。{POST_GUARD_FIX_HINT}"
                    )
                if not str(element.get("tag") or "").strip():
                    raise PayloadGuardError(
                        f"GUARD-POST-005 语种块 `{lang}` 第 {index + 1} 段内存在缺少 `tag` 字段的元素："
                        f"{sorted(element.keys())}。{POST_GUARD_FIX_HINT}"
                    )
    return "ok"


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
