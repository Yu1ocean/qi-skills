#!/usr/bin/env python3
"""根据选中的多个时段生成批量创建日程的请求载荷。

本脚本不直接调用飞书创建日程 API，而是生成结构化的 JSON 结果，供上层
通过 `feishu-calendar` 等工具批量创建日程时复用：

- 统一生成一个幂等性 Key（batch 级）；
- 对每个选中时段生成一条待创建的事件载荷，自动应用：
  - `title_prefix`（若非空）；
  - `room_mode`（auto/skip）；

输入：
    一个 JSON 文件路径，内容示例：

    {
      "session_id": "...",              # 可选，缺省从环境变量 AIME_SESSION_ID 读取
      "user_id": "...",                 # 可选，缺省从环境变量 AIME_CURRENT_USER 读取
      "counterpart_name": "齐临",         # 可选，用于默认标题推导（同义字段：colleague_name）
      "base_title": "深度约会会谈",        # 可选；缺省或为空时，默认使用 `【Sync：[同事姓名] / 奇楠】`
      "title_prefix": "【预占】",         # 可选，默认空字符串
      "room_mode": "auto",              # "auto" | "skip"
      "online_only": false,              # 可选，仅作为下游参考
      "attendees": ["a@example.com", "b@example.com"],
      "slots": [
        {"start": "2026-04-01T10:00:00+08:00", "end": "2026-04-01T11:30:00+08:00"},
        {"start": "2026-04-02T15:00:00+08:00", "end": "2026-04-02T16:30:00+08:00"}
      ]
    }

输出：
    通过 stdout 打印 JSON，对象结构示例：

    {
      "idempotency_key": "...",
      "events": [
        {
          "title": "【预占】深度约会会谈",
          "start_time": "...",
          "end_time": "...",
          "attendees": [...],
          "room_mode": "auto",
          "online_only": false
        },
        ...
      ]
    }

上层可以直接遍历 `events` 列表，对每个元素调用飞书日历创建接口，并统一
携带同一个 `idempotency_key`，从而实现批量发车的防重保护。
"""

import json
import os
import re
import sys
import logging
from typing import Any, Dict, List

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

from generate_idempotency_key import generate_batch_key  # noqa: E402

def validate_title(title: str, attendees_count: int) -> None:
    """校验生成的最终标题是否符合 Title 规范。"""
    if not title.startswith("【预占】"):
        raise ValueError(f"标题必须以【预占】开头，当前标题为：{title}")
    
    if attendees_count == 2:
        if " × 奇楠" not in title:
            logging.warning(f"WARNING: 单对单会议标题不符合推荐模板（【预占】<对方> × 奇楠），当前标题为：{title}")
    elif attendees_count >= 3:
        if title == "【预占】" or title.startswith("【预占】多人会议"):
            raise ValueError(f"多人会议必须包含具体主题，不能仅使用泛泛的标题：{title}。请询问用户具体主题。")


def extract_base_title_from_input(raw_text: str) -> str:
    """从原始输入里提取最高优先级主题。

    规则：只要用户输入里出现【xxx】，就强制把 xxx 提取为 base_title。
    """
    if not raw_text:
        return ""

    matches = re.findall(r"【([^\[\]【】]+)】", raw_text)
    for match in matches:
        candidate = str(match).strip()
        if candidate:
            return candidate
    return ""


def has_explicit_title_signal(raw_text: str) -> bool:
    """判断原始输入中是否存在显式主题信号。"""
    if not raw_text:
        return False
    if extract_base_title_from_input(raw_text):
        return True

    lowered = raw_text.lower()
    explicit_markers = [
        "主题",
        "会议主题",
        "标题",
        "topic",
        "subject",
        "讨论",
        "同步",
        "评审",
        "复盘",
        "沟通",
    ]
    return any(marker in lowered for marker in explicit_markers)


def resolve_base_title(config: Dict[str, Any], attendees_count: int, counterpart_name: str) -> str:
    """统一处理 base_title 提取与熔断规则。"""
    raw_base_title = config.get("base_title")
    base_title = str(raw_base_title).strip() if raw_base_title is not None else ""
    raw_user_input = str(
        config.get("raw_user_input")
        or config.get("user_input")
        or config.get("original_input")
        or ""
    ).strip()

    bracket_title = extract_base_title_from_input(raw_user_input)
    if bracket_title:
        return bracket_title

    explicit_title_flag = bool(
        config.get("explicit_title_in_input")
        or config.get("has_explicit_topic_in_input")
        or has_explicit_title_signal(raw_user_input)
    )

    if explicit_title_flag and not base_title:
        raise ValueError("检测到原始输入存在显式主题，但建会参数 base_title 为空；已触发硬闸熔断，禁止回退到双人默认标题。")

    if base_title:
        return base_title

    try:
        default_title = build_default_title(attendees_count, counterpart_name)
        if default_title.startswith("【预占】"):
            return default_title[4:]
        return default_title
    except ValueError as e:
        raise ValueError(f"缺少会议主题(base_title): {str(e)}")


def build_default_title(attendees_count: int, counterpart_name: str) -> str:
    """根据参会人数生成默认的基础标题（不含动态前缀，或直接包含前缀）。"""
    if attendees_count == 2:
        return f"【预占】{counterpart_name} × 奇楠"
    else:
        # 多人会议必须有主题，这里直接触发校验或留空让上层抛错
        raise ValueError("多人会议（3人及以上）必须提供明确的会议主题，无法使用默认模板，请询问用户。")

def build_batch_payload(config: Dict[str, Any]) -> Dict[str, Any]:
    """根据配置 JSON 构建批量创建日程的载荷。"""

    session_id = config.get("session_id") or os.environ.get("AIME_SESSION_ID", "default_session")
    user_id = config.get("user_id") or os.environ.get("AIME_CURRENT_USER", "default_user")

    title_prefix = str(config.get("title_prefix", ""))
    room_mode = str(config.get("room_mode", "auto"))
    online_only = bool(config.get("online_only", False))
    attendees = list(config.get("attendees", []))
    slots = list(config.get("slots", []))
    attendees_count = len(attendees)

    counterpart_name = (
        str(config.get("counterpart_name") or config.get("colleague_name") or "同事").strip()
        or "同事"
    )
    base_title = resolve_base_title(config, attendees_count, counterpart_name)

    extra = {
        "room_mode": room_mode,
        "title_prefix": title_prefix,
        "online_only": online_only,
    }

    # 统一生成 batch 级幂等 Key
    idempotency_key = generate_batch_key(
        session_id=session_id,
        user_id=user_id,
        base_title=base_title,
        slots=slots,
        attendees=attendees,
        extra=extra,
    )

    def _build_title() -> str:
        # Avoid double prefix
        if title_prefix and base_title.startswith(title_prefix):
            return base_title
        return f"{title_prefix}{base_title}" if title_prefix else f"【预占】{base_title}"

    events: List[Dict[str, Any]] = []
    for slot in slots:
        start_time = slot.get("start")
        end_time = slot.get("end")
        if not start_time or not end_time:
            continue
        final_title = _build_title()
        validate_title(final_title, attendees_count)

        events.append(
            {
                "title": final_title,
                "start_time": start_time,
                "end_time": end_time,
                "attendees": attendees,
                "room_mode": room_mode,
                "online_only": online_only,
            }
        )

    return {
        "idempotency_key": idempotency_key,
        "events": events,
    }


def main(argv: List[str]) -> None:
    if len(argv) < 2:
        print(
            "Usage: python3 batch_create_events.py <selected_slots.json> [output.json]",
            file=sys.stderr,
        )
        sys.exit(1)

    input_path = argv[1]
    output_path = argv[2] if len(argv) >= 3 else None

    with open(input_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    payload = build_batch_payload(config)

    # 优先写入文件（如指定），同时在 stdout 打印 JSON，方便上层直接使用
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f_out:
            f_out.write(payload_text)
        print(f"Generated batch payload to {output_path}", file=sys.stderr)

    print(payload_text)


if __name__ == "__main__":  # pragma: no cover - 脚本入口
    main(sys.argv)
