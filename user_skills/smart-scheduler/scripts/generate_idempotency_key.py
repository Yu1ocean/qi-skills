#!/usr/bin/env python3
"""幂等性标识 (Idempotency Key) 生成脚本。

- `generate_key`：基础方法，根据会话 ID、用户 ID 和会议详情生成稳定的 SHA256 哈希；
- `generate_batch_key`：扩展方法，用于批量创建场景，将多个时段的信息固化到同一个
  `event_info` 中，方便在批量创建时统一使用一个幂等 Key。

注意：`event_info` 必须是 JSON 可序列化的结构（例如仅包含字符串、数字、列表和 dict），
不要直接放入 datetime 对象。
"""

import hashlib
import json
import os
from typing import Any, Dict, Iterable, List


def generate_key(session_id: str, user_id: str, event_info: Dict[str, Any]) -> str:
    """根据会话 ID、用户 ID 和会议详情生成唯一的、稳定的幂等性标识。

    生成规则：
      - 将 `session_id`、`user_id` 与 `event_info` 打包为一个 dict；
      - 使用 `json.dumps(..., sort_keys=True)` 进行稳定序列化；
      - 对序列化结果做 SHA256 哈希，返回 64 位十六进制字符串。
    """

    payload = {
        "session_id": session_id,
        "user_id": user_id,
        "event_info": event_info,
    }
    dumped = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def generate_batch_key(
    session_id: str,
    user_id: str,
    base_title: str,
    slots: Iterable[Dict[str, Any]],
    attendees: List[str],
    extra: Dict[str, Any] | None = None,
) -> str:
    """为批量创建场景生成统一的幂等性标识。

    参数：
        session_id: 会话 ID（可取自环境变量 `AIME_SESSION_ID`）
        user_id: 当前用户 ID（可取自环境变量 `AIME_CURRENT_USER` 或邮箱）
        base_title: 会议基础标题（不含前缀）
        slots: 时段列表，每个元素应为 JSON 可序列化的 dict，例如：
            {"start": "2026-04-01T10:00:00+08:00", "end": "2026-04-01T11:30:00+08:00"}
        attendees: 参会人列表（邮箱或 ID）
        extra: 其他希望纳入幂等性计算的字段（如 room_mode、title_prefix 等），可选

    返回：
        单个字符串形式的幂等性 Key，可在整批创建时复用。
    """

    event_info: Dict[str, Any] = {
        "title": base_title,
        "slots": list(slots),  # 确保为列表，便于 JSON 序列化
        "attendees": attendees,
    }
    if extra:
        event_info["extra"] = extra
    return generate_key(session_id, user_id, event_info)


if __name__ == "__main__":
    # 示例：从环境变量读取会话与用户信息，如无则使用占位值
    session_id = os.environ.get("AIME_SESSION_ID", "default_session")
    user_id = os.environ.get("AIME_CURRENT_USER", "default_user")

    # 单场会议示例
    single_event_info = {
        "title": "Smart Meeting",
        "start_time": "2026-04-01T10:00:00Z",
        "end_time": "2026-04-01T10:30:00Z",
        "attendees": ["yuqinan@example.com", "test@example.com"],
    }
    single_key = generate_key(session_id, user_id, single_event_info)
    print(f"Generated Idempotency Key (single): {single_key}")

    # 批量创建示例
    slots_demo = [
        {"start": "2026-04-01T10:00:00Z", "end": "2026-04-01T11:30:00Z"},
        {"start": "2026-04-02T15:00:00Z", "end": "2026-04-02T16:30:00Z"},
    ]
    batch_key = generate_batch_key(
        session_id,
        user_id,
        base_title="Smart Scheduler 深度共创会",
        slots=slots_demo,
        attendees=["yuqinan@example.com", "test@example.com"],
        extra={"room_mode": "auto", "title_prefix": "【预占】"},
    )
    print(f"Generated Idempotency Key (batch): {batch_key}")
