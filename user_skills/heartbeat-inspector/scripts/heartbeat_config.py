#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Target:
    id: str
    type: str
    title: str
    raw: Dict[str, Any]


def _extract_first_json_code_block(text: str) -> str | None:
    """Extract the first ```json ... ``` code block.

    Return None if not found.
    """
    m = re.search(r"```\s*json\s*(.*?)\s*```", text, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    return m.group(1)


def _short_hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


def _parse_shorthand(text: str) -> Dict[str, Any]:
    """Parse a lightweight human-friendly format.

    Supported examples:
    - 巡检群：项目A沟通群
    - 模式：全局群聊只看@我的消息

    This parser is intentionally conservative: if it cannot unambiguously parse,
    it will raise ConfigError instead of guessing.
    """

    targets: List[Dict[str, Any]] = []

    # Normalize Chinese colon variants and full-width spaces
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Handle list item prefix
        if line.startswith("-"):
            line = line[1:].strip()

        line = line.replace("：", ":")

        # 1) Chat inspection by name
        #    e.g. 巡检群: 项目A沟通群
        m = re.match(r"^(巡检群|群聊|群)\s*:\s*(.+)$", line)
        if m:
            name = m.group(2).strip()
            if not name:
                raise ConfigError(f"巡检群名称为空：{raw_line}")
            targets.append(
                {
                    "id": f"chat_{_short_hash(name)}",
                    "type": "feishu_chat",
                    "title": name,
                    "chat_name": name,
                }
            )
            continue

        # 2) Global mention-only mode
        #    e.g. 模式: 全局群聊只看@我的消息
        if line.startswith("模式") and ("全局" in line) and ("@" in line or "艾特" in line):
            if "@我" in line or "@我的" in line or "@我的消息" in line or "@我的消息" in line or "艾特" in line:
                targets.append(
                    {
                        "id": "mentions_me_global",
                        "type": "feishu_mentions_global",
                        "title": "全局@我",
                    }
                )
                continue

    if not targets:
        raise ConfigError(
            "未找到可解析的简写配置。建议在 HEARTBEAT.md 中提供 ```json ... ``` 配置块，或使用简写：\n"
            "- 巡检群：项目A沟通群\n"
            "- 模式：全局群聊只看@我的消息"
        )

    return {"version": 1, "targets": targets}


def load_heartbeat_config(heartbeat_md: Path) -> Dict[str, Any]:
    if not heartbeat_md.exists():
        raise ConfigError(f"未找到配置文件: {heartbeat_md}")

    text = heartbeat_md.read_text(encoding="utf-8")

    cfg_json = _extract_first_json_code_block(text)
    if cfg_json is not None:
        try:
            return json.loads(cfg_json)
        except Exception as e:
            raise ConfigError(f"HEARTBEAT.md 的 json 配置块无法解析: {e}")

    # Fallback to shorthand format
    return _parse_shorthand(text)


def validate_and_normalize_config(cfg: Dict[str, Any]) -> List[Target]:
    if not isinstance(cfg, dict):
        raise ConfigError("配置根对象必须是 JSON object")

    version = cfg.get("version")
    if version != 1:
        raise ConfigError(f"不支持的 version={version}（当前只支持 1）")

    targets = cfg.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ConfigError("targets 必须是非空数组")

    seen = set()
    normalized: List[Target] = []
    for i, t in enumerate(targets):
        if not isinstance(t, dict):
            raise ConfigError(f"targets[{i}] 必须是 object")

        tid = t.get("id")
        if not isinstance(tid, str) or not tid:
            tid = f"auto_{i}"

        if tid in seen:
            raise ConfigError(f"targets[{i}].id 重复：{tid}")
        seen.add(tid)

        ttype = t.get("type")
        if not isinstance(ttype, str) or not ttype:
            raise ConfigError(f"targets[{i}].type 必须是非空字符串")

        title = t.get("title") or tid

        normalized.append(Target(id=tid, type=ttype, title=str(title), raw=t))

    return normalized
