from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence


DEFAULT_CHAT_REGISTRY_RELATIVE_PATH = "CHAT_REGISTRY.json"
DEFAULT_BROADCAST_USAGE = "task_patrol_broadcast"


class ChatRegistryError(ValueError):
    """Raised when Chat Registry is missing, malformed, or rejects a target."""


@dataclass(frozen=True)
class ChatRegistryEntry:
    usage: str
    chat_id: str
    name: str
    expected_name_keywords: tuple[str, ...]
    lookup_query: str
    description: str = ""
    admin_email: Optional[str] = None
    allow_group_broadcast_by_default: bool = False

    @classmethod
    def from_mapping(cls, usage: str, data: Mapping[str, Any]) -> "ChatRegistryEntry":
        chat_id = _non_empty_str(data.get("chat_id"), field=f"chats.{usage}.chat_id")
        if not chat_id.startswith("oc_"):
            raise ChatRegistryError(f"chats.{usage}.chat_id 必须是 oc_ 开头的群聊 chat_id")

        name = _non_empty_str(data.get("name"), field=f"chats.{usage}.name")
        keywords_raw = data.get("expected_name_keywords")
        if not isinstance(keywords_raw, list):
            raise ChatRegistryError(f"chats.{usage}.expected_name_keywords 必须是非空字符串数组")
        keywords = tuple(str(item).strip() for item in keywords_raw if str(item).strip())
        if not keywords:
            raise ChatRegistryError(f"chats.{usage}.expected_name_keywords 必须至少配置一个群名关键字")

        lookup_query = str(data.get("lookup_query") or keywords[0]).strip()
        if not lookup_query:
            raise ChatRegistryError(f"chats.{usage}.lookup_query 不能为空")

        admin_email = data.get("admin_email")
        return cls(
            usage=usage,
            chat_id=chat_id,
            name=name,
            expected_name_keywords=keywords,
            lookup_query=lookup_query,
            description=str(data.get("description") or "").strip(),
            admin_email=str(admin_email).strip() if admin_email else None,
            allow_group_broadcast_by_default=bool(data.get("allow_group_broadcast_by_default", False)),
        )

    def to_target_chat(self) -> Dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "name": self.name,
            "registry_usage": self.usage,
            "expected_name_keywords": list(self.expected_name_keywords),
            "lookup_query": self.lookup_query,
        }

    def assert_requested_chat_id(self, requested_chat_id: Optional[str]) -> None:
        value = (requested_chat_id or "").strip()
        if not value:
            return
        if value != self.chat_id:
            raise ChatRegistryError(
                f"target chat_id 与 Chat Registry 不一致：requested={value}, registry={self.chat_id}, usage={self.usage}"
            )

    def assert_metadata(self, metadata: Mapping[str, Any]) -> None:
        actual_chat_id = str(metadata.get("chat_id") or "").strip()
        actual_name = str(metadata.get("name") or "").strip()
        if actual_chat_id != self.chat_id:
            raise ChatRegistryError(
                f"pre-flight 群 ID 断言失败：registry={self.chat_id}, actual={actual_chat_id or '[missing]'}"
            )
        if not actual_name:
            raise ChatRegistryError("pre-flight 群名断言失败：群元信息缺少 name")
        missing = [keyword for keyword in self.expected_name_keywords if keyword not in actual_name]
        if missing:
            raise ChatRegistryError(
                f"pre-flight 群名关键字断言失败：actual_name={actual_name}, missing_keywords={missing}, usage={self.usage}"
            )


class ChatRegistry:
    def __init__(self, path: Path, entries: Mapping[str, ChatRegistryEntry], default_usage: str):
        self.path = path
        self.entries = dict(entries)
        self.default_usage = default_usage

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "ChatRegistry":
        registry_path = path or default_chat_registry_path()
        registry_path = registry_path.resolve()
        if not registry_path.exists():
            raise ChatRegistryError(f"Chat Registry 不存在：{registry_path}")

        try:
            obj = json.loads(registry_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ChatRegistryError(f"Chat Registry 不是合法 JSON：{registry_path}: {exc}") from exc

        chats = obj.get("chats")
        if not isinstance(chats, dict) or not chats:
            raise ChatRegistryError("Chat Registry 必须包含非空 chats 对象")

        entries: Dict[str, ChatRegistryEntry] = {}
        for usage, data in chats.items():
            if not isinstance(data, dict):
                raise ChatRegistryError(f"chats.{usage} 必须是对象")
            entries[str(usage)] = ChatRegistryEntry.from_mapping(str(usage), data)

        default_usage = str(obj.get("default_usage") or DEFAULT_BROADCAST_USAGE).strip()
        if default_usage not in entries:
            raise ChatRegistryError(f"default_usage={default_usage} 不存在于 chats 中")
        return cls(registry_path, entries, default_usage)

    def get(self, usage: Optional[str] = None) -> ChatRegistryEntry:
        key = (usage or self.default_usage or "").strip()
        if key not in self.entries:
            raise ChatRegistryError(f"Chat Registry 未配置用途：{key}")
        return self.entries[key]


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_chat_registry_path() -> Path:
    return _workspace_root() / DEFAULT_CHAT_REGISTRY_RELATIVE_PATH


def load_chat_registry(path: Optional[Path] = None) -> ChatRegistry:
    return ChatRegistry.load(path)


def get_chat_registry_entry(*, usage: Optional[str] = None, path: Optional[Path] = None) -> ChatRegistryEntry:
    return load_chat_registry(path).get(usage)


def default_broadcast_target_chat(*, registry_path: Optional[Path] = None, usage: Optional[str] = None) -> Dict[str, Any]:
    return get_chat_registry_entry(usage=usage or DEFAULT_BROADCAST_USAGE, path=registry_path).to_target_chat()


def default_broadcast_chat_id() -> str:
    return get_chat_registry_entry(usage=DEFAULT_BROADCAST_USAGE).chat_id


def _non_empty_str(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ChatRegistryError(f"{field} 不能为空")
    return text
