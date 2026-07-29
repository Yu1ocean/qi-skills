from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from byted_aime_sdk import call_aime_tool

from .taskflow_ack_renderer import (
    DEFAULT_TASKFLOW_SHEET_URL,
    build_taskflow_ack_post,
    render_taskflow_ack_text,
)

SENT_CARDS_LOG_REL_PATH = ".aime/log/sent_cards/SENT_CARDS.jsonl"
DEFAULT_NOTIFICATION_LOG_DIR = "notification_logs"
DEFAULT_NOTIFICATION_LOG_PREFIX = "taskflow_ack_"


@dataclass
class ToolSendResult:
    ok: bool
    payload: Optional[Dict[str, Any]]
    error: Optional[str]
    parse_warning: Optional[str]
    message_id: Optional[str]
    open_message_id: Optional[str]


class NotificationLogger:
    def __init__(self, log_path: Path):
        self.log_path = log_path

    def append(self, record: Dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(s: str) -> str:
    text = (s or "").strip()
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in text)[:180] or "unknown"


def _as_non_empty_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_feishu_message_id(value: Optional[str]) -> bool:
    text = _as_non_empty_str(value)
    if text is None:
        return False
    return text.startswith("om_")


SOURCE_MESSAGE_ID_KEYS = (
    "source_message_id",
    "feishu_om_id",
    "message_id",
    "open_message_id",
    "reply_to",
)


def extract_source_message_id(payload: Any) -> Optional[str]:
    """从 TaskFlow 触发入口载荷中提取 Feishu 原生 om_xxx message_id。

    入口可能来自主进程 prompt、Heartbeat 事件、脚本 CLI 或已标准化的 ack payload；
    只接受 om_ 前缀，避免把本地 UUID / Aime trace id 错当成可盖楼父消息。
    """
    if isinstance(payload, str):
        text = payload.strip()
        if _is_feishu_message_id(text):
            return text
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None

    for item in _walk_dicts(payload):
        for key in SOURCE_MESSAGE_ID_KEYS:
            candidate = _as_non_empty_str(item.get(key))
            if _is_feishu_message_id(candidate):
                return candidate
    return None


def require_source_message_id(payload: Any, *, field_name: str = "source_message_id") -> str:
    source_message_id = extract_source_message_id(payload)
    if not source_message_id:
        raise ValueError(f"{field_name} 必须包含 Feishu 原始 message_id（应以 om_ 开头）")
    return source_message_id


def _default_notification_log_path() -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _repo_root() / DEFAULT_NOTIFICATION_LOG_DIR / f"{DEFAULT_NOTIFICATION_LOG_PREFIX}{today}.jsonl"


def _append_sent_cards_record(record: Dict[str, Any]) -> None:
    path = _workspace_root() / SENT_CARDS_LOG_REL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def _safe_getattr(obj: Any, attr_name: str) -> tuple[bool, Any]:
    try:
        return True, getattr(obj, attr_name)
    except Exception as exc:  # pragma: no cover - defensive branch
        return False, exc


def _safe_repr(value: Any) -> str:
    try:
        return repr(value)
    except Exception:  # pragma: no cover - defensive branch
        return f"<{type(value).__name__}>"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    has_to_dict, to_dict_or_exc = _safe_getattr(value, "to_dict")
    if has_to_dict and callable(to_dict_or_exc):
        try:
            return _json_safe(to_dict_or_exc())
        except Exception as exc:
            return {
                "_raw_type": type(value).__name__,
                "_repr": _safe_repr(value),
                "_to_dict_error": f"{type(exc).__name__}: {exc}",
            }
    return {"_raw_type": type(value).__name__, "_repr": _safe_repr(value)}


def _payload_to_dict(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}
        return parsed if isinstance(parsed, dict) else {"data": parsed}
    safe_value = _json_safe(value)
    if isinstance(safe_value, dict):
        return safe_value
    return {"data": safe_value}


def _walk_dicts(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def _extract_message_identifiers(payload: Optional[Dict[str, Any]]) -> tuple[Optional[str], Optional[str]]:
    if not isinstance(payload, dict):
        return None, None
    message_id = None
    open_message_id = None
    for item in _walk_dicts(payload):
        if message_id is None:
            message_id = _as_non_empty_str(item.get("message_id"))
        if open_message_id is None:
            open_message_id = _as_non_empty_str(item.get("open_message_id"))
        if message_id and open_message_id:
            break
    return message_id, open_message_id


def normalize_tool_send_result(raw_result: Any) -> ToolSendResult:
    success_accessed, success_or_exc = _safe_getattr(raw_result, "success")
    payload: Optional[Dict[str, Any]] = None
    parse_warnings: list[str] = []

    if success_accessed:
        ok = bool(success_or_exc)
    else:
        ok = False
        parse_warnings.append(f"读取 success 失败：{type(success_or_exc).__name__}: {success_or_exc}")

    data_accessed, data_or_exc = _safe_getattr(raw_result, "data")
    if data_accessed:
        payload = _payload_to_dict(data_or_exc)
    else:
        parse_warnings.append(f"读取 data 失败：{type(data_or_exc).__name__}: {data_or_exc}")
        payload = None

    if payload is None:
        to_dict_accessed, to_dict_or_exc = _safe_getattr(raw_result, "to_dict")
        if to_dict_accessed and callable(to_dict_or_exc):
            try:
                payload = _payload_to_dict(to_dict_or_exc())
            except Exception as exc:
                parse_warnings.append(f"to_dict 解析失败：{type(exc).__name__}: {exc}")
        elif not to_dict_accessed:
            parse_warnings.append(f"读取 to_dict 失败：{type(to_dict_or_exc).__name__}: {to_dict_or_exc}")

    message_id, open_message_id = _extract_message_identifiers(payload)

    error = None
    if not ok:
        if isinstance(payload, dict):
            error = (
                _as_non_empty_str(payload.get("msg"))
                or _as_non_empty_str(payload.get("message"))
                or _as_non_empty_str(payload.get("error"))
                or _as_non_empty_str(payload.get("error_msg"))
                or json.dumps(payload, ensure_ascii=False)
            )
        else:
            error = _safe_repr(raw_result)

    return ToolSendResult(
        ok=ok,
        payload=payload,
        error=error,
        parse_warning="；".join(parse_warnings) if parse_warnings else None,
        message_id=message_id,
        open_message_id=open_message_id,
    )


def _find_existing_sent_ack(*, chat_id: str, source_message_id: str) -> Optional[Dict[str, Any]]:
    path = _workspace_root() / SENT_CARDS_LOG_REL_PATH
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("result") != "success":
            continue
        if _as_non_empty_str(record.get("topic")) != "taskflow_ack":
            continue
        if _as_non_empty_str(record.get("source_message_id")) != source_message_id:
            continue
        receiver = record.get("receiver") if isinstance(record.get("receiver"), dict) else {}
        if _as_non_empty_str(receiver.get("chat_id")) != chat_id:
            continue
        return record
    return None


def _extract_json_object_from_stdout(stdout: str) -> Dict[str, Any]:
    text = (stdout or "").strip()
    if not text:
        raise ValueError("stdout 为空")
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.lstrip().startswith("{"):
            candidate = "\n".join(lines[index:])
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
            raise ValueError("stdout JSON 根节点不是 object")
    raise ValueError("stdout 中未找到 JSON 对象")


def probe_taskflow_thread_attachment(*, source_message_id: str, reply_message_id: str) -> Dict[str, Any]:
    script_path = _workspace_root() / "inner_skills" / "feishu-im-read" / "scripts" / "feishu_im_user_mget_messages.js"
    cmd = [
        "node",
        str(script_path),
        "--input",
        json.dumps({"message_ids": [source_message_id, reply_message_id]}, ensure_ascii=False),
    ]
    completed = subprocess.run(
        cmd,
        cwd=str(_workspace_root()),
        capture_output=True,
        text=True,
        check=False,
    )
    probe: Dict[str, Any] = {
        "source_message_id": source_message_id,
        "reply_message_id": reply_message_id,
        "command": cmd,
        "returncode": completed.returncode,
    }
    if completed.returncode != 0:
        probe["status"] = "probe_exec_failed"
        probe["stderr"] = (completed.stderr or "").strip() or None
        probe["stdout_preview"] = (completed.stdout or "").strip()[:500] or None
        return probe

    try:
        payload = _extract_json_object_from_stdout(completed.stdout)
    except Exception as exc:
        probe["status"] = "probe_parse_failed"
        probe["error"] = f"{type(exc).__name__}: {exc}"
        probe["stdout_preview"] = (completed.stdout or "").strip()[:1000] or None
        return probe

    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    probe["message_count"] = len(messages)
    indexed_messages = {}
    for item in messages:
        if isinstance(item, dict):
            message_id = _as_non_empty_str(item.get("message_id"))
            if message_id:
                indexed_messages[message_id] = item

    source_message = indexed_messages.get(source_message_id)
    reply_message = indexed_messages.get(reply_message_id)
    if source_message is None or reply_message is None:
        probe["status"] = "missing_message"
        probe["missing"] = {
            "source": source_message is None,
            "reply": reply_message is None,
        }
        return probe

    source_thread_id = _as_non_empty_str(source_message.get("thread_id"))
    reply_thread_id = _as_non_empty_str(reply_message.get("thread_id"))
    probe["source_thread_id"] = source_thread_id
    probe["reply_thread_id"] = reply_thread_id
    if not source_thread_id or not reply_thread_id:
        probe["status"] = "missing_thread_id"
        return probe
    if source_thread_id != reply_thread_id:
        probe["status"] = "thread_mismatch"
        return probe

    probe["status"] = "verified_same_thread"
    return probe


def send_taskflow_ack(
    *,
    chat_id: str,
    source_message_id: str,
    task_name: str,
    owner_text: str,
    status_text: str = "✅ 已入库",
    sheet_url: str = DEFAULT_TASKFLOW_SHEET_URL,
    notification_log_path: Optional[Path] = None,
) -> Dict[str, Any]:
    target_chat_id = _as_non_empty_str(chat_id)
    if not target_chat_id:
        raise ValueError("chat_id 不能为空")
    reply_to = require_source_message_id({"source_message_id": source_message_id})

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    logger = NotificationLogger(notification_log_path or _default_notification_log_path())
    logical_topic_key = f"task-flow-engine|taskflow_ack|{reply_to}"
    record: Dict[str, Any] = {
        "run_id": run_id,
        "created_at": _now_iso(),
        "mode": "taskflow_ack",
        "msg_type": "post",
        "logical_topic_key": logical_topic_key,
        "logical_msg_id": f"task-flow-engine|taskflow_ack|{run_id}",
        "receiver": {"chat_id": target_chat_id},
        "source_message_id": reply_to,
        "task_name": (task_name or "").strip(),
        "owner_text": (owner_text or "").strip(),
        "status_text": (status_text or "").strip(),
        "sheet_url": sheet_url,
    }

    existing = _find_existing_sent_ack(chat_id=target_chat_id, source_message_id=reply_to)
    if existing is not None:
        record.update(
            {
                "sent_at": _now_iso(),
                "result": "skipped_duplicate_source_message",
                "duplicate_of": {
                    "message_id": existing.get("message_id"),
                    "open_message_id": existing.get("open_message_id"),
                    "sent_at": existing.get("sent_at"),
                    "logical_msg_id": existing.get("logical_msg_id"),
                    "run_id": existing.get("run_id"),
                },
            }
        )
        logger.append(record)
        return record

    content = build_taskflow_ack_post(
        task_name=task_name,
        owner=owner_text,
        status=status_text,
        sheet_url=sheet_url,
    )
    record["message_preview"] = render_taskflow_ack_text(
        task_name=task_name,
        owner=owner_text,
        status=status_text,
        sheet_url=sheet_url,
    )
    record["content"] = content

    raw_result = call_aime_tool(
        "lark_im_message",
        "lark_im_reply_message",
        {
            "message_id": reply_to,
            "content": json.dumps(content, ensure_ascii=False),
            "content_type": "post",
            "reply_in_thread": True,
        },
    )
    normalized = normalize_tool_send_result(raw_result)
    record["im_send"] = {
        "ok": normalized.ok,
        "payload": normalized.payload,
        "error": normalized.error,
        "parse_warning": normalized.parse_warning,
    }
    if normalized.message_id:
        record["message_id"] = normalized.message_id
    if normalized.open_message_id:
        record["open_message_id"] = normalized.open_message_id
    if normalized.parse_warning:
        record["parse_warning"] = normalized.parse_warning

    thread_probe = None
    if normalized.ok and normalized.message_id:
        thread_probe = probe_taskflow_thread_attachment(
            source_message_id=reply_to,
            reply_message_id=normalized.message_id,
        )
        record["thread_probe"] = thread_probe

    result = "success" if normalized.ok else "failed_send"
    error = normalized.error
    if thread_probe is not None and thread_probe.get("status") != "verified_same_thread":
        result = "failed_thread_probe"
        error = f"thread_probe_failed:{thread_probe.get('status')}"

    record.update(
        {
            "sent_at": _now_iso(),
            "result": result,
            "error": error,
        }
    )

    sent_cards_record = {
        "logical_msg_id": record.get("logical_msg_id"),
        "logical_topic_key": logical_topic_key,
        "created_at": record.get("created_at"),
        "sent_at": record.get("sent_at"),
        "skill": "task-flow-engine",
        "topic": "taskflow_ack",
        "run_id": run_id,
        "receiver": record.get("receiver"),
        "msg_type": record.get("msg_type"),
        "message_id": record.get("message_id"),
        "open_message_id": record.get("open_message_id"),
        "result": record.get("result"),
        "error": record.get("error"),
        "source_message_id": reply_to,
    }
    _append_sent_cards_record(sent_cards_record)
    logger.append(record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="TaskFlow L1 回执标准发送器")
    parser.add_argument("--chat-id", required=True, help="目标群 chat_id")
    parser.add_argument("--source-message-id", required=True, help="原始触发消息 ID（必须为 Feishu 原始 message_id，形如 om_xxx），用于 L1 盖楼与防重")
    parser.add_argument("--task-name", required=True, help="任务名")
    parser.add_argument("--owner-text", required=True, help="负责人展示文本，如 @张三")
    parser.add_argument("--status-text", default="✅ 已入库", help="状态文本")
    parser.add_argument("--sheet-url", default=DEFAULT_TASKFLOW_SHEET_URL, help="任务库直达链接")
    parser.add_argument("--log-file", default=None, help="通知日志 JSONL 路径，默认写入 notification_logs/taskflow_ack_<UTC日期>.jsonl")
    args = parser.parse_args()

    log_file = Path(args.log_file).resolve() if args.log_file else None
    record = send_taskflow_ack(
        chat_id=args.chat_id,
        source_message_id=args.source_message_id,
        task_name=args.task_name,
        owner_text=args.owner_text,
        status_text=args.status_text,
        sheet_url=args.sheet_url,
        notification_log_path=log_file,
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if record.get("result") in {"success", "skipped_duplicate_source_message"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
