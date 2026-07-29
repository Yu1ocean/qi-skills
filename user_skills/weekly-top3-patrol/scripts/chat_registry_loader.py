"""
chat_registry_loader.py — CHAT_REGISTRY.json 单一真相源加载器

强制约束：
1. 群 ID 必须从 CHAT_REGISTRY.json 读取，禁止从历史 / 缓存 / 上下文猜测
2. 加载后必须做群名关键字断言（pre-flight assertion）
3. 校验失败立即 raise，不允许默默降级
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any


# 向上递归找 workspace 根（含 CHAT_REGISTRY.json）
def _find_registry_path() -> Path:
    """从当前文件出发向上找 CHAT_REGISTRY.json，最多上溯 6 层。"""
    here = Path(__file__).resolve()
    for parent in [here] + list(here.parents):
        candidate = parent / "CHAT_REGISTRY.json"
        if candidate.exists():
            return candidate
        # 也允许在 workspace 根找
    # 兜底：使用 cwd
    cwd_candidate = Path.cwd() / "CHAT_REGISTRY.json"
    if cwd_candidate.exists():
        return cwd_candidate
    raise FileNotFoundError(
        "CHAT_REGISTRY.json 未找到。请确认运行时 cwd 在 workspace 根目录，"
        "或在 workspace 根存在 CHAT_REGISTRY.json。"
    )


def load_chat(
    chat_key: str = "task_patrol_broadcast",
    expected_keywords: list[str] | None = None,
    registry_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """加载 CHAT_REGISTRY 中指定 key 的群信息，并做群名关键字断言。

    Args:
        chat_key: 注册表中的群 key，默认 'task_patrol_broadcast'
        expected_keywords: 必须在 name 中出现的关键字列表；若为 None 则使用注册表里的
                           expected_name_keywords
        registry_path: 可选，注册表路径，默认自动搜索

    Returns:
        群信息 dict（含 chat_id / name / admin_email 等）

    Raises:
        ValueError: 群 key 不存在 / 群名关键字断言失败
        FileNotFoundError: 注册表文件未找到
    """
    path = Path(registry_path) if registry_path else _find_registry_path()
    with open(path, "r", encoding="utf-8") as f:
        registry = json.load(f)

    chats = registry.get("chats", {})
    if chat_key not in chats:
        raise ValueError(
            f"[CHAT_REGISTRY] key='{chat_key}' 未在 CHAT_REGISTRY.json 中注册。"
            f"已注册 keys: {list(chats.keys())}"
        )
    chat = chats[chat_key]

    # 群名关键字断言（pre-flight）
    keywords = expected_keywords or chat.get("expected_name_keywords", [])
    name = chat.get("name", "")
    for kw in keywords:
        if kw not in name:
            raise ValueError(
                f"[CHAT_REGISTRY] 群名关键字断言失败：期望 '{kw}' 在 name='{name}' 中。"
                f"chat_id={chat.get('chat_id')}。检查 CHAT_REGISTRY.json 是否被错误修改。"
            )

    return chat


def get_patrol_chat_id() -> str:
    """便捷入口：获取 task_patrol_broadcast 的 chat_id。"""
    chat = load_chat("task_patrol_broadcast")
    chat_id = chat.get("chat_id")
    if not chat_id or not chat_id.startswith("oc_"):
        raise ValueError(f"[CHAT_REGISTRY] chat_id 格式异常: {chat_id}")
    return chat_id


if __name__ == "__main__":
    # 自检入口
    chat = load_chat("task_patrol_broadcast")
    print(f"[OK] CHAT_REGISTRY 加载成功")
    print(f"     chat_id: {chat['chat_id']}")
    print(f"     name:    {chat['name']}")
    print(f"     admin:   {chat.get('admin_email')}")
