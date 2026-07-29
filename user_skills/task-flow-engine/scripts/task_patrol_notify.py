#!/usr/bin/env python3
"""任务巡检 + 飞书通知发送器。

本脚本负责把 `scripts/run_task_patrol_save.py` / `scripts/task_patrol.py`
产出的 alerts.json 真正“送达”。

当前行为：
- 群广播：chat_id 只能来自 Chat Registry，并在真实发送前做群元信息 + 群名关键字 pre-flight
- 私聊发送：默认关闭；通过 `--enable-private-chat` 显式开启后，逐负责人发送个人卡片
- 两段式提交：默认 dry-run；只有 `--commit-group-broadcast` + 确认口令通过后才允许群播
- committed send 硬约束：真实群播只能由 `scripts/run_daily_pipeline.py` 透传触发；一旦同主题群播成功，不允许再次执行 committed send

注意：
- 真正发送飞书消息时，请用 Aime 的 bash 工具执行，并设置 include_secrets=true。
- 本脚本严禁用于发送测试消息；dry-run 模式只落盘 payload + 写本地 Notification Log。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from task_flow_engine.chat_registry import (
    DEFAULT_BROADCAST_USAGE,
    ChatRegistryEntry,
    ChatRegistryError,
    default_broadcast_chat_id,
    get_chat_registry_entry,
)
from task_flow_engine.chat_registry_sync import DEFAULT_CHAT_REGISTRY_SPREADSHEET_URL
from task_flow_engine.broadcast_card import (
    build_minimal_broadcast_card,
    extract_broadcast_alert_items,
    pick_top_focus_owners,
    render_owner_category_table_image,
)
from task_flow_engine.patrol import build_patrol_card_a, default_task_workstation_url


DEFAULT_TARGET_CHAT_ID = default_broadcast_chat_id()
DEFAULT_WORKSTATION_URL = "https://bytedance.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV?sheet=KmlJhs"
SUPPORTED_PRIVATE_ID_TYPES: Tuple[str, ...] = ("email",)
COMMITTED_SEND_ENTRY_ENV = "TASK_FLOW_NOTIFY_ALLOW_COMMITTED_SEND"
COMMITTED_SEND_ENTRY_VALUE = "run_daily_pipeline"


def _repo_root() -> Path:
    # user_skills/task-flow-engine/scripts/task_patrol_notify.py
    return Path(__file__).resolve().parents[1]


def _workspace_root() -> Path:
    # user_skills/task-flow-engine/scripts/task_patrol_notify.py
    # parents[0]=scripts, [1]=task-flow-engine, [2]=user_skills, [3]=workspace root
    return Path(__file__).resolve().parents[3]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^A-Za-z0-9._@-]+", "_", s)
    return s[:180] or "unknown"


def _preview_text(s: str, *, max_len: int = 240) -> str:
    text = (s or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _as_non_empty_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_send_stdout(stdout: str) -> Optional[Dict[str, Any]]:
    stdout = (stdout or "").strip()
    if not stdout:
        return None

    if "[RESULT]" in stdout:
        stdout = stdout.split("[RESULT]", 1)[1].strip()

    try:
        parsed = json.loads(stdout)
        if isinstance(parsed, dict):
            return parsed
        return {"data": parsed}
    except json.JSONDecodeError:
        pass

    fallback: Dict[str, Any] = {}
    patterns = {
        "card_id": r"'card_id'\s*:\s*'?(\d+)'?",
        "message_id": r"'message_id'\s*:\s*'([^']+)'",
        "open_message_id": r"'open_message_id'\s*:\s*'([^']+)'",
        "image_key": r"'image_key'\s*:\s*'([^']+)'",
        "resource_key": r"'resource_key'\s*:\s*'([^']+)'",
        "file_key": r"'file_key'\s*:\s*'([^']+)'",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, stdout)
        if match:
            fallback[key] = match.group(1)

    return fallback or None


def _validate_safe_path_under_repo(path: Path, *, repo_root: Path, arg_name: str) -> Path:
    repo_root = repo_root.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(f"{arg_name} 必须位于任务目录内：{resolved} (repo_root={repo_root})") from exc
    return resolved


def _sync_chat_registry_from_feishu(*, repo_root: Path, chat_registry_output: Optional[str]) -> None:
    cmd = [
        sys.executable,
        "scripts/sync_registry_from_feishu.py",
        "--spreadsheet",
        DEFAULT_CHAT_REGISTRY_SPREADSHEET_URL,
        "--skip-auth",
    ]
    if chat_registry_output:
        cmd.extend(["--output", chat_registry_output])
    process = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if process.returncode == 0:
        return
    detail = (process.stderr or process.stdout or "").strip()
    raise ChatRegistryError(f"Chat Registry 飞书同步失败：{detail or 'unknown error'}")


@dataclass
class SendResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    parsed: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class NotificationLogger:
    def __init__(self, log_path: Path):
        self.log_path = log_path

    def append(self, record: Dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


SENT_CARDS_LOG_REL_PATH = ".aime/log/sent_cards/SENT_CARDS.jsonl"
DELIVERY_GUARD_DIR_REL_PATH = ".runtime/notify_delivery_guard"
DELIVERY_GUARD_STALE_SECONDS = 10 * 60


def _append_sent_cards_record(record: Dict[str, Any]) -> None:
    workspace_root = _workspace_root()
    log_path = workspace_root / SENT_CARDS_LOG_REL_PATH
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    text = _as_non_empty_str(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_receiver_identity(receiver: Mapping[str, Any]) -> Dict[str, str]:
    chat_id = _as_non_empty_str(receiver.get("chat_id"))
    email = _as_non_empty_str(receiver.get("email"))
    receiver_id = _as_non_empty_str(receiver.get("receiver_id"))
    id_type = _as_non_empty_str(receiver.get("id_type"))

    if chat_id:
        return {"receiver_key": f"chat_id:{chat_id}", "chat_id": chat_id}
    if email:
        return {"receiver_key": f"email:{email}", "email": email}
    if receiver_id and id_type:
        normalized = {"receiver_key": f"{id_type}:{receiver_id}", "receiver_id": receiver_id, "id_type": id_type}
        if id_type == "chat_id":
            normalized["chat_id"] = receiver_id
        if id_type == "email":
            normalized["email"] = receiver_id
        return normalized
    if receiver_id:
        return {"receiver_key": receiver_id, "receiver_id": receiver_id}
    return {}


def _delivery_guard_root() -> Path:
    return _repo_root() / DELIVERY_GUARD_DIR_REL_PATH


def _delivery_guard_key(*, logical_topic_key: Optional[str], receiver: Mapping[str, Any]) -> Optional[str]:
    topic = _as_non_empty_str(logical_topic_key)
    receiver_info = _normalize_receiver_identity(receiver)
    receiver_key = receiver_info.get("receiver_key")
    if not topic or not receiver_key:
        return None
    raw_key = f"{topic}|{receiver_key}"
    digest = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()
    return f"{digest}__{_safe_filename(raw_key)}"


def _delivery_guard_paths(*, logical_topic_key: Optional[str], receiver: Mapping[str, Any]) -> Tuple[Optional[Path], Optional[Path]]:
    key = _delivery_guard_key(logical_topic_key=logical_topic_key, receiver=receiver)
    if not key:
        return None, None
    root = _delivery_guard_root()
    return root / f"{key}.lock.json", root / f"{key}.receipt.json"


def _load_json_file(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json_file(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _claim_delivery_guard(
    *,
    logical_topic_key: Optional[str],
    receiver: Mapping[str, Any],
    run_id: str,
    within_seconds: int = 24 * 60 * 60,
    stale_seconds: int = DELIVERY_GUARD_STALE_SECONDS,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    lock_path, receipt_path = _delivery_guard_paths(logical_topic_key=logical_topic_key, receiver=receiver)
    if lock_path is None or receipt_path is None:
        return True, None

    now = datetime.now(timezone.utc)
    receipt = _load_json_file(receipt_path)
    if receipt:
        sent_at = _parse_iso_datetime(receipt.get("sent_at")) or _parse_iso_datetime(receipt.get("created_at"))
        if sent_at is not None and (now - sent_at).total_seconds() <= within_seconds:
            return False, receipt

    payload = {
        "run_id": run_id,
        "logical_topic_key": logical_topic_key,
        "receiver": dict(receiver),
        "created_at": now.isoformat(),
        "status": "sending",
    }
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        existing = _load_json_file(lock_path) or {}
        created_at = _parse_iso_datetime(existing.get("created_at"))
        if created_at is not None and (now - created_at).total_seconds() <= stale_seconds:
            return False, existing
        lock_path.unlink(missing_ok=True)
        fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, indent=2))
    return True, None


def _release_delivery_guard(
    *,
    logical_topic_key: Optional[str],
    receiver: Mapping[str, Any],
    record: Dict[str, Any],
    success: bool,
) -> None:
    lock_path, receipt_path = _delivery_guard_paths(logical_topic_key=logical_topic_key, receiver=receiver)
    if lock_path is None or receipt_path is None:
        return
    if success:
        receipt_payload = {
            "logical_topic_key": logical_topic_key,
            "receiver": dict(receiver),
            "run_id": record.get("run_id"),
            "created_at": record.get("created_at"),
            "sent_at": record.get("sent_at") or _now_iso(),
            "result": record.get("result"),
            "message_id": record.get("message_id"),
            "card_id": record.get("card_id"),
            "logical_msg_id": record.get("logical_msg_id"),
        }
        _write_json_file(receipt_path, receipt_payload)
    lock_path.unlink(missing_ok=True)


def _find_recent_sent_card(
    *,
    logical_topic_key: Optional[str],
    receiver: Mapping[str, Any],
    within_seconds: int = 24 * 60 * 60,
) -> Optional[Dict[str, Any]]:
    if not logical_topic_key or within_seconds <= 0:
        return None

    workspace_root = _workspace_root()
    log_path = workspace_root / SENT_CARDS_LOG_REL_PATH
    if not log_path.exists():
        return None

    receiver_info = _normalize_receiver_identity(receiver)
    receiver_chat_id = receiver_info.get("chat_id")
    receiver_email = receiver_info.get("email")
    receiver_key = receiver_info.get("receiver_key")
    now = datetime.now(timezone.utc)

    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    for raw_line in reversed(lines):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("result") != "success":
            continue
        if _as_non_empty_str(record.get("logical_topic_key")) != logical_topic_key:
            continue

        logged_receiver = record.get("receiver") if isinstance(record.get("receiver"), dict) else {}
        logged_receiver_info = _normalize_receiver_identity(logged_receiver)
        logged_chat_id = logged_receiver_info.get("chat_id")
        logged_email = logged_receiver_info.get("email")
        logged_receiver_key = logged_receiver_info.get("receiver_key")
        if receiver_key and logged_receiver_key and receiver_key != logged_receiver_key:
            continue
        if receiver_chat_id and receiver_chat_id != logged_chat_id:
            continue
        if receiver_email and receiver_email != logged_email:
            continue

        sent_at = _parse_iso_datetime(record.get("sent_at")) or _parse_iso_datetime(record.get("created_at"))
        if sent_at is None:
            continue
        if (now - sent_at).total_seconds() > within_seconds:
            continue
        return record
    return None


class FeishuBotSender:
    """通过 inner_skills/feishu-im-send 发送消息。"""

    supported_id_types: Tuple[str, ...] = ("email", "chat_id")

    def __init__(self):
        self.workspace_root = _workspace_root()
        self.skill_dir = self.workspace_root / "inner_skills" / "feishu-im-send"
        self.im_send = self.skill_dir / "scripts" / "im_send.py"

        if not self.im_send.exists():
            raise FileNotFoundError(f"找不到飞书发送脚本：{self.im_send}")

    def supports_id_type(self, id_type: str) -> bool:
        return id_type in self.supported_id_types

    def _run(self, cmd: Sequence[str]) -> SendResult:
        process = subprocess.run(
            list(cmd),
            cwd=str(self.skill_dir),
            capture_output=True,
            text=True,
        )

        parsed: Optional[Dict[str, Any]] = None
        err: Optional[str] = None
        if process.stdout.strip():
            parsed = _parse_send_stdout(process.stdout)

        ok = process.returncode == 0
        if not ok:
            err = (process.stderr or process.stdout or "").strip() or f"returncode={process.returncode}"

        return SendResult(
            ok=ok,
            returncode=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
            parsed=parsed,
            error=err,
        )

    def create_card(self, *, card_json_path: Path) -> SendResult:
        cmd = [sys.executable, "scripts/im_send.py", "create_card", str(card_json_path)]
        return self._run(cmd)

    def upload_image(self, *, image_path: Path) -> SendResult:
        cmd = [sys.executable, "scripts/im_send.py", "upload", str(image_path.resolve()), "image"]
        return self._run(cmd)

    def send_card(self, *, receiver_id: str, id_type: str, card_id: str) -> SendResult:
        if not self.supports_id_type(id_type):
            raise ValueError(f"当前底层发送脚本不支持 id_type={id_type}")

        cmd = [
            sys.executable,
            "scripts/im_send.py",
            "send",
            receiver_id,
            "interactive",
            str(card_id),
            f"--id-type={id_type}",
        ]
        return self._run(cmd)


class FeishuChatMetadataClient:
    """读取飞书群元信息，用于群播前的 pre-flight 群名断言。"""

    def __init__(self):
        self.workspace_root = _workspace_root()
        self.skill_dir = self.workspace_root / "inner_skills" / "feishu-im-read"
        self.search_chats = self.skill_dir / "scripts" / "feishu_im_user_search_chats.js"
        if not self.search_chats.exists():
            raise FileNotFoundError(f"找不到飞书群聊搜索脚本：{self.search_chats}")

    def get_chat_metadata(self, entry: ChatRegistryEntry) -> Dict[str, Any]:
        query = entry.lookup_query or entry.expected_name_keywords[0]
        cmd = [
            "node",
            "scripts/feishu_im_user_search_chats.js",
            "--input",
            json.dumps({"query": query, "page_size": 100}, ensure_ascii=False),
        ]
        process = subprocess.run(
            cmd,
            cwd=str(self.skill_dir),
            capture_output=True,
            text=True,
        )
        if process.returncode != 0:
            err = (process.stderr or process.stdout or "").strip() or f"returncode={process.returncode}"
            raise ChatRegistryError(f"pre-flight 拉取群元信息失败：{err}")

        parsed = _parse_json_object_from_stdout(process.stdout)
        chats = _extract_chats(parsed)
        for chat in chats:
            if str(chat.get("chat_id") or "").strip() == entry.chat_id:
                return dict(chat)
        raise ChatRegistryError(
            f"pre-flight 未能通过 lookup_query={query!r} 找到 registry chat_id={entry.chat_id}；"
            "请更新 Chat Registry 的 lookup_query / expected_name_keywords，或确认执行人仍在该群。"
        )


def _parse_json_object_from_stdout(stdout: str) -> Dict[str, Any]:
    text = (stdout or "").strip()
    if "[RESULT]" in text:
        text = text.split("[RESULT]", 1)[1].strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ChatRegistryError("pre-flight 群元信息返回无法解析为 JSON object")


def _extract_chats(parsed: Mapping[str, Any]) -> list[Dict[str, Any]]:
    candidates = [parsed, parsed.get("data") if isinstance(parsed.get("data"), dict) else None]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        chats = candidate.get("chats")
        if isinstance(chats, list):
            return [dict(chat) for chat in chats if isinstance(chat, dict)]
        exact_match = candidate.get("exact_match")
        if isinstance(exact_match, dict):
            return [dict(exact_match)]
    return []


def _preflight_group_target(entry: ChatRegistryEntry, *, metadata_client: Optional[FeishuChatMetadataClient] = None) -> Dict[str, Any]:
    client = metadata_client or FeishuChatMetadataClient()
    metadata = client.get_chat_metadata(entry)
    entry.assert_metadata(metadata)
    return metadata


def _write_payload_file(*, out_dir: Path, filename: str, payload: Dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _load_alerts(alerts_file: Path) -> Dict[str, Any]:
    obj = json.loads(alerts_file.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("alerts_file 内容不是 JSON object")
    return obj


def _pick_broadcast_route(alerts: Dict[str, Any]) -> Dict[str, Any]:
    routes = alerts.get("routes") or {}
    if isinstance(routes.get("group_broadcast"), dict):
        return routes["group_broadcast"]
    if isinstance(routes.get("group"), dict):
        return routes["group"]
    return {}


def _pick_private_routes(alerts: Dict[str, Any]) -> Tuple[str, Dict[str, Dict[str, Any]]]:
    routes = alerts.get("routes") or {}
    for source in ("p2p", "private"):
        candidate = routes.get(source)
        if isinstance(candidate, dict) and candidate:
            return source, candidate
    for source in ("p2p", "private"):
        candidate = routes.get(source)
        if isinstance(candidate, dict):
            return source, candidate
    return "private", {}


def _build_fallback_card_payload(
    *,
    route: Dict[str, Any],
    alerts: Dict[str, Any],
    title: str,
    template: str,
) -> Optional[Dict[str, Any]]:
    if isinstance(route.get("card"), dict):
        return route["card"]

    message = _as_non_empty_str(route.get("message"))
    count = route.get("count")
    today = _as_non_empty_str((alerts.get("summary") or {}).get("today"))

    body_parts = []
    if today:
        body_parts.append(f"**日期**：{today}")
    if count is not None:
        body_parts.append(f"**需关注条目**：{count}")
    if message:
        body_parts.append(message)

    body_md = "\n\n".join(body_parts).strip() or "（本次巡检无可展示内容）"
    return build_patrol_card_a(
        title=title,
        template=template,
        body_md=body_md,
        action_text="前往任务工作站处理",
        action_url=default_task_workstation_url() or DEFAULT_WORKSTATION_URL,
    )


def _path_for_record(path: Path, *, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path.resolve())



def _alerts_today_text(alerts: Dict[str, Any]) -> str:
    return _as_non_empty_str((alerts.get("summary") or {}).get("today")) or date.today().isoformat()



def _build_visual_group_card_bundle(
    *,
    alerts: Dict[str, Any],
    payload_root: Path,
    sender: Optional[FeishuBotSender],
) -> Dict[str, Any]:
    items = extract_broadcast_alert_items(alerts)
    if not items:
        return {
            "payload": None,
            "image_path": None,
            "summary_counts": {},
            "top_focus_owners": [],
            "upload_result": None,
        }

    today_text = _alerts_today_text(alerts)
    top_focus_owners = pick_top_focus_owners(items, top_n=3)
    stats_image_path = payload_root / "group_broadcast_stats.png"
    image_meta = render_owner_category_table_image(
        items=items,
        today_text=today_text,
        output_path=stats_image_path,
        top_focus_owners=top_focus_owners,
    )

    image_key: Optional[str] = None
    upload_result: Optional[SendResult] = None
    if sender is not None:
        upload_result = sender.upload_image(image_path=stats_image_path)
        if upload_result.ok and isinstance(upload_result.parsed, dict):
            image_key = _as_non_empty_str(upload_result.parsed.get("image_key")) or _as_non_empty_str(
                upload_result.parsed.get("resource_key")
            )
        if not image_key:
            raise RuntimeError(upload_result.error or "统计表图片上传失败，未返回 image_key/resource_key")

    payload = build_minimal_broadcast_card(
        today_text=today_text,
        summary_counts=image_meta.get("summary_counts") or {},
        top_focus_owners=top_focus_owners,
        action_text="前往任务工作站处理",
        action_url=default_task_workstation_url() or DEFAULT_WORKSTATION_URL,
        image_key=image_key,
        title="📌 任务巡检提醒",
        template="blue",
    )
    return {
        "payload": payload,
        "image_path": stats_image_path,
        "image_key": image_key,
        "summary_counts": image_meta.get("summary_counts") or {},
        "top_focus_owners": top_focus_owners,
        "upload_result": upload_result,
    }


def _resolve_group_target(entry: ChatRegistryEntry, *assertion_candidates: Optional[str]) -> Tuple[str, list[str]]:
    ignored: list[str] = []
    for candidate in assertion_candidates:
        value = _as_non_empty_str(candidate)
        if not value:
            continue
        if value != entry.chat_id:
            raise ChatRegistryError(
                f"群播目标断言失败：requested={value}, registry={entry.chat_id}, usage={entry.usage}。"
                "chat_id 必须来自 Chat Registry，禁止从 alerts/context/缓存改写。"
            )
    return entry.chat_id, ignored


def _resolve_private_receiver(
    owner: Dict[str, Any],
    *,
    supported_id_types: Sequence[str],
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    open_id = _as_non_empty_str(owner.get("open_id"))
    email = _as_non_empty_str(owner.get("email"))

    if open_id and "open_id" in supported_id_types:
        return "open_id", open_id, None
    if email and "email" in supported_id_types:
        return "email", email, None
    if open_id and email:
        return None, None, "supported_id_type_missing_for_open_id_and_email"
    if open_id and "open_id" not in supported_id_types:
        return None, None, "open_id_only_but_sender_does_not_support_open_id"
    if email and "email" not in supported_id_types:
        return None, None, "email_only_but_sender_does_not_support_email"
    return None, None, "missing_open_id_and_email"


def _route_count(route: Dict[str, Any]) -> int:
    count = route.get("count")
    if isinstance(count, int):
        return count
    items = route.get("items")
    if isinstance(items, list):
        return len(items)
    return 0


def _base_record(
    *,
    run_id: str,
    mode: str,
    alerts_path: Path,
    repo_root: Path,
    payload_path: Optional[Path],
    count: int,
    message_preview: str,
) -> Dict[str, Any]:
    alerts = _load_alerts(alerts_path)
    logical_topic_key = f"task-flow-engine|{mode}|{_alerts_today_text(alerts)}"
    record: Dict[str, Any] = {
        "run_id": run_id,
        "created_at": _now_iso(),
        "mode": mode,
        "alerts_file": str(alerts_path.relative_to(repo_root)),
        "msg_type": "interactive",
        "count": count,
        "message_preview": _preview_text(message_preview),
        "logical_topic_key": logical_topic_key,
    }
    if payload_path is not None:
        record["payload_path"] = str(payload_path.relative_to(repo_root))
    return record


def _attach_send_result(record: Dict[str, Any], *, key: str, result: SendResult) -> None:
    record[key] = {
        "returncode": result.returncode,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
        "parsed": result.parsed,
        "error": result.error,
    }


def _send_payload(
    *,
    sender: FeishuBotSender,
    payload_path: Path,
    receiver_id: str,
    id_type: str,
    record: Dict[str, Any],
    logger: NotificationLogger,
) -> bool:
    res_create = sender.create_card(card_json_path=payload_path)
    _attach_send_result(record, key="create_card", result=res_create)
    if not res_create.ok:
        record.update({"sent_at": _now_iso(), "result": "failed_create_card", "error": res_create.error})
        logger.append(record)
        return False

    card_id = None
    if isinstance(res_create.parsed, dict):
        card_id = res_create.parsed.get("card_id")
    if not card_id:
        record.update({"sent_at": _now_iso(), "result": "failed_create_card_no_id", "error": "missing card_id"})
        logger.append(record)
        return False

    record["card_id"] = str(card_id)
    res_send = sender.send_card(receiver_id=receiver_id, id_type=id_type, card_id=str(card_id))
    _attach_send_result(record, key="im_send", result=res_send)

    if isinstance(res_send.parsed, dict):
        message_id = _as_non_empty_str(res_send.parsed.get("message_id"))
        open_message_id = _as_non_empty_str(res_send.parsed.get("open_message_id"))
        if message_id:
            record["message_id"] = message_id
        if open_message_id:
            record["open_message_id"] = open_message_id

    record.update(
        {
            "sent_at": _now_iso(),
            "result": "success" if res_send.ok else "failed_send",
            "error": res_send.error,
        }
    )
    logical_msg_id = f"task-flow-engine|{record.get('mode') or 'unknown'}|{record.get('run_id')}"
    record["logical_msg_id"] = logical_msg_id
    sent_cards_record = {
        "logical_msg_id": logical_msg_id,
        "logical_topic_key": record.get("logical_topic_key"),
        "created_at": record.get("created_at"),
        "sent_at": record.get("sent_at"),
        "skill": "task-flow-engine",
        "topic": record.get("mode"),
        "run_id": record.get("run_id"),
        "receiver": record.get("receiver"),
        "msg_type": record.get("msg_type"),
        "card_id": record.get("card_id"),
        "message_id": record.get("message_id"),
        "open_message_id": record.get("open_message_id"),
        "result": record.get("result"),
        "error": record.get("error"),
        "payload_path": record.get("payload_path"),
    }
    _append_sent_cards_record(sent_cards_record)
    logger.append(record)
    return res_send.ok


def _group_dry_run_effective(args: argparse.Namespace) -> bool:
    if args.dry_run:
        return True
    if args.send_to_admin_only:
        return False
    return not args.commit_group_broadcast


def _validate_group_commit_gate(args: argparse.Namespace) -> None:
    if args.send_to_admin_only or args.dry_run:
        return
    if not args.commit_group_broadcast:
        return
    if args.confirm_group_broadcast != "CONFIRM_GROUP_BROADCAST":
        raise ChatRegistryError(
            "真实群播必须同时传入 --commit-group-broadcast "
            "和 --confirm-group-broadcast CONFIRM_GROUP_BROADCAST"
        )


def _process_group_broadcast(
    *,
    args: argparse.Namespace,
    alerts: Dict[str, Any],
    alerts_path: Path,
    repo_root: Path,
    payload_root: Path,
    run_id: str,
    logger: NotificationLogger,
    group_entry: ChatRegistryEntry,
) -> bool:
    route = _pick_broadcast_route(alerts)
    requested_route_chat_id = None
    if isinstance(route, dict):
        requested_route_chat_id = _as_non_empty_str(((route.get("target_chat") or {}).get("chat_id")))

    target_chat_id, ignored_chat_ids = _resolve_group_target(group_entry, requested_route_chat_id, args.target_chat_id)
    effective_dry_run = _group_dry_run_effective(args)
    _validate_group_commit_gate(args)

    preflight_metadata: Optional[Dict[str, Any]] = None
    if not effective_dry_run and not args.send_to_admin_only:
        try:
            preflight_metadata = _preflight_group_target(group_entry)
        except Exception as exc:
            record = _base_record(
                run_id=run_id,
                mode="group",
                alerts_path=alerts_path,
                repo_root=repo_root,
                payload_path=None,
                count=_route_count(route),
                message_preview=_as_non_empty_str(route.get("message")) or "",
            )
            record.update(
                {
                    "receiver": {"chat_id": target_chat_id},
                    "chat_registry": {
                        "usage": group_entry.usage,
                        "expected_name_keywords": list(group_entry.expected_name_keywords),
                        "lookup_query": group_entry.lookup_query,
                    },
                    "sent_at": _now_iso(),
                    "result": "fused_preflight_failed",
                    "error": str(exc),
                }
            )
            logger.append(record)
            return False

    sender = None if effective_dry_run else FeishuBotSender()

    visual_bundle: Dict[str, Any] = {}
    visual_build_error: Optional[str] = None
    try:
        visual_bundle = _build_visual_group_card_bundle(
            alerts=alerts,
            payload_root=payload_root,
            sender=sender,
        )
        card_payload = visual_bundle.get("payload")
    except Exception as exc:
        visual_build_error = str(exc)
        card_payload = None

    if not card_payload or not isinstance(card_payload, dict):
        card_payload = _build_fallback_card_payload(
            route=route,
            alerts=alerts,
            title="📌 任务巡检提醒",
            template="blue",
        )

    if not card_payload or not isinstance(card_payload, dict):
        record = _base_record(
            run_id=run_id,
            mode="admin_only" if args.send_to_admin_only else "group",
            alerts_path=alerts_path,
            repo_root=repo_root,
            payload_path=None,
            count=_route_count(route),
            message_preview=_as_non_empty_str(route.get("message")) or "",
        )
        record.update(
            {
                "receiver": {"email": args.admin_email} if args.send_to_admin_only else {"chat_id": target_chat_id},
                "result": "skipped_empty_card",
            }
        )
        if ignored_chat_ids:
            record["requested_chat_ids_ignored"] = ignored_chat_ids
        logger.append(record)
        return True

    payload_path = _write_payload_file(
        out_dir=payload_root,
        filename=f"group_{_safe_filename(target_chat_id)}.card.json",
        payload=card_payload,
    )
    record = _base_record(
        run_id=run_id,
        mode="admin_only" if args.send_to_admin_only else "group",
        alerts_path=alerts_path,
        repo_root=repo_root,
        payload_path=payload_path,
        count=_route_count(route),
        message_preview=_as_non_empty_str(route.get("message")) or "",
    )
    record["receiver"] = {"email": args.admin_email} if args.send_to_admin_only else {"chat_id": target_chat_id}
    if ignored_chat_ids:
        record["requested_chat_ids_ignored"] = ignored_chat_ids
    if visual_build_error:
        record["visual_card_warning"] = visual_build_error
    image_path = visual_bundle.get("image_path") if isinstance(visual_bundle, dict) else None
    if isinstance(image_path, Path):
        record["stats_image_path"] = _path_for_record(image_path, repo_root=repo_root)
    top_focus_owners = visual_bundle.get("top_focus_owners") if isinstance(visual_bundle, dict) else []
    if top_focus_owners:
        record["top_focus_owners"] = [
            {
                "display_name": owner.get("display_name"),
                "email": owner.get("email"),
                "open_id": owner.get("open_id"),
                "counts": owner.get("counts"),
                "total": owner.get("total"),
            }
            for owner in top_focus_owners
        ]
    summary_counts = visual_bundle.get("summary_counts") if isinstance(visual_bundle, dict) else None
    if summary_counts:
        record["summary_counts"] = summary_counts
    upload_result = visual_bundle.get("upload_result") if isinstance(visual_bundle, dict) else None
    if isinstance(upload_result, SendResult):
        _attach_send_result(record, key="upload_image", result=upload_result)

    record["chat_registry"] = {
        "usage": group_entry.usage,
        "expected_name_keywords": list(group_entry.expected_name_keywords),
        "lookup_query": group_entry.lookup_query,
    }
    if effective_dry_run:
        record["result"] = "skipped_dry_run" if args.dry_run else "skipped_default_dry_run"
        logger.append(record)
        return True

    receiver = record.get("receiver") if isinstance(record.get("receiver"), dict) else {}
    logical_topic_key = _as_non_empty_str(record.get("logical_topic_key"))
    guard_claimed, guard_record = _claim_delivery_guard(
        logical_topic_key=logical_topic_key,
        receiver=receiver,
        run_id=run_id,
    )
    if not guard_claimed:
        duplicate_record = guard_record or _find_recent_sent_card(
            logical_topic_key=logical_topic_key,
            receiver=receiver,
        )
        record.update(
            {
                "sent_at": _now_iso(),
                "result": "skipped_duplicate_recent_send",
                "duplicate_of": {
                    "message_id": duplicate_record.get("message_id") if isinstance(duplicate_record, dict) else None,
                    "card_id": duplicate_record.get("card_id") if isinstance(duplicate_record, dict) else None,
                    "sent_at": duplicate_record.get("sent_at") if isinstance(duplicate_record, dict) else None,
                    "logical_msg_id": duplicate_record.get("logical_msg_id") if isinstance(duplicate_record, dict) else None,
                    "run_id": duplicate_record.get("run_id") if isinstance(duplicate_record, dict) else None,
                    "status": duplicate_record.get("status") if isinstance(duplicate_record, dict) else None,
                  },
            }
        )
        logger.append(record)
        return True

    if preflight_metadata is not None:
        record["preflight"] = {
            "result": "passed",
            "chat_id": preflight_metadata.get("chat_id"),
            "name": preflight_metadata.get("name"),
            "expected_name_keywords": list(group_entry.expected_name_keywords),
        }

    if sender is None:
        sender = FeishuBotSender()
    receiver_id = args.admin_email if args.send_to_admin_only else target_chat_id
    receiver_type = "email" if args.send_to_admin_only else "chat_id"
    send_ok = False
    try:
        send_ok = _send_payload(
            sender=sender,
            payload_path=payload_path,
            receiver_id=receiver_id,
            id_type=receiver_type,
            record=record,
            logger=logger,
        )
        return send_ok
    finally:
        _release_delivery_guard(
            logical_topic_key=logical_topic_key,
            receiver=receiver,
            record=record,
            success=send_ok,
        )


def _process_private_routes(
    *,
    args: argparse.Namespace,
    alerts: Dict[str, Any],
    alerts_path: Path,
    repo_root: Path,
    payload_root: Path,
    run_id: str,
    logger: NotificationLogger,
) -> bool:
    if not args.enable_private_chat:
        return True

    route_source, private_routes = _pick_private_routes(alerts)
    if not private_routes:
        record = _base_record(
            run_id=run_id,
            mode="private_batch",
            alerts_path=alerts_path,
            repo_root=repo_root,
            payload_path=None,
            count=0,
            message_preview="",
        )
        record.update({"route_source": route_source, "result": "skipped_no_private_routes"})
        logger.append(record)
        return True

    if args.send_to_admin_only and not args.dry_run:
        record = _base_record(
            run_id=run_id,
            mode="private_batch",
            alerts_path=alerts_path,
            repo_root=repo_root,
            payload_path=None,
            count=len(private_routes),
            message_preview="",
        )
        record.update(
            {
                "route_source": route_source,
                "result": "skipped_send_to_admin_only_conflict",
                "skip_reason": "send_to_admin_only 模式下不执行真实私聊；如需演练请改用 --dry-run",
            }
        )
        logger.append(record)
        return True

    sender = None if args.dry_run else FeishuBotSender()
    supported_id_types = SUPPORTED_PRIVATE_ID_TYPES if sender is None else sender.supported_id_types

    all_ok = True
    for route_key, route in sorted(private_routes.items(), key=lambda item: item[0]):
        owner = route.get("owner") or {}
        owner_display_name = _as_non_empty_str(owner.get("display_name")) or _as_non_empty_str(owner.get("raw")) or route_key
        card_payload = _build_fallback_card_payload(
            route=route,
            alerts=alerts,
            title="📌 任务巡检提醒",
            template="blue",
        )

        payload_path: Optional[Path] = None
        if card_payload and isinstance(card_payload, dict):
            preferred_key = _as_non_empty_str(owner.get("email")) or _as_non_empty_str(owner.get("open_id")) or route_key
            payload_path = _write_payload_file(
                out_dir=payload_root,
                filename=f"owner_{_safe_filename(preferred_key)}.card.json",
                payload=card_payload,
            )

        record = _base_record(
            run_id=run_id,
            mode="private",
            alerts_path=alerts_path,
            repo_root=repo_root,
            payload_path=payload_path,
            count=_route_count(route),
            message_preview=_as_non_empty_str(route.get("message")) or "",
        )
        record.update(
            {
                "route_source": route_source,
                "route_key": route_key,
                "owner": owner,
            }
        )

        if not card_payload or not isinstance(card_payload, dict):
            record.update({"result": "skipped_empty_card", "skip_reason": "route card/message 为空"})
            logger.append(record)
            continue

        receiver_type, receiver_id, skip_reason = _resolve_private_receiver(
            owner,
            supported_id_types=supported_id_types,
        )
        record["receiver"] = {
            "display_name": owner_display_name,
            "email": _as_non_empty_str(owner.get("email")),
            "open_id": _as_non_empty_str(owner.get("open_id")),
            "id_type": receiver_type,
            "receiver_id": receiver_id,
        }

        if not receiver_type or not receiver_id:
            record.update({"result": "skipped_missing_receiver", "skip_reason": skip_reason})
            logger.append(record)
            continue

        if args.dry_run:
            record["result"] = "skipped_dry_run"
            logger.append(record)
            continue

        logical_topic_key = _as_non_empty_str(record.get("logical_topic_key"))
        receiver = record.get("receiver") if isinstance(record.get("receiver"), dict) else {}
        guard_claimed, guard_record = _claim_delivery_guard(
            logical_topic_key=logical_topic_key,
            receiver=receiver,
            run_id=run_id,
        )
        if not guard_claimed:
            duplicate_record = guard_record or _find_recent_sent_card(
                logical_topic_key=logical_topic_key,
                receiver=receiver,
            )
            record.update(
                {
                    "sent_at": _now_iso(),
                    "result": "skipped_duplicate_recent_send",
                    "duplicate_of": {
                        "message_id": duplicate_record.get("message_id") if isinstance(duplicate_record, dict) else None,
                        "card_id": duplicate_record.get("card_id") if isinstance(duplicate_record, dict) else None,
                        "sent_at": duplicate_record.get("sent_at") if isinstance(duplicate_record, dict) else None,
                        "logical_msg_id": duplicate_record.get("logical_msg_id") if isinstance(duplicate_record, dict) else None,
                        "run_id": duplicate_record.get("run_id") if isinstance(duplicate_record, dict) else None,
                        "status": duplicate_record.get("status") if isinstance(duplicate_record, dict) else None,
                    },
                }
            )
            logger.append(record)
            continue

        assert sender is not None
        ok = False
        try:
            ok = _send_payload(
                sender=sender,
                payload_path=payload_path,
                receiver_id=receiver_id,
                id_type=receiver_type,
                record=record,
                logger=logger,
            )
        finally:
            _release_delivery_guard(
                logical_topic_key=logical_topic_key,
                receiver=receiver,
                record=record,
                success=ok,
            )
        all_ok = all_ok and ok

    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--alerts-file",
        required=True,
        help="run_task_patrol_save.py 输出的 alerts.json 路径（建议用相对路径，强制限制在仓库内）",
    )
    parser.add_argument(
        "--target-chat-id",
        default=None,
        help="兼容旧参数：仅作为 Chat Registry 断言值；不再作为 chat_id 来源。",
    )
    parser.add_argument(
        "--chat-registry",
        default=None,
        help="Chat Registry JSON 路径（相对路径默认相对于 task-flow-engine 根目录）。",
    )
    parser.add_argument(
        "--broadcast-usage",
        default=DEFAULT_BROADCAST_USAGE,
        help="Chat Registry 中的群用途 key（默认：task_patrol_broadcast）。",
    )
    parser.add_argument(
        "--admin-email",
        default="yuqinan@bytedance.com",
        help="管理员邮箱（dry-run / 演练模式下可用于私聊核对）",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="通知日志文件（JSONL）。默认写入 notification_logs/notify_<UTC日期>.jsonl",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="不真实发送，只生成 payload + 写 Notification Log（默认即为群播 dry-run）",
    )
    parser.add_argument(
        "--commit-group-broadcast",
        action="store_true",
        help="开启真实群播提交。必须同时提供 --confirm-group-broadcast CONFIRM_GROUP_BROADCAST。",
    )
    parser.add_argument(
        "--confirm-group-broadcast",
        default=None,
        help="真实群播二次确认口令；固定为 CONFIRM_GROUP_BROADCAST。",
    )
    parser.add_argument(
        "--send-to-admin-only",
        action="store_true",
        help="演练模式：仅把群广播卡片私聊发给管理员（不发群）；私聊链路请优先使用 --dry-run 演练",
    )
    parser.add_argument(
        "--enable-private-chat",
        action="store_true",
        help="开启逐负责人私聊发送；默认关闭。开启后会从 routes.p2p（或 routes.private）逐人发送个人卡片。",
    )
    parser.add_argument(
        "--fail-on-private-errors",
        action="store_true",
        help="严格模式：即便群播已成功，只要私聊链路存在真实发送失败也返回非 0；默认关闭，避免触发 committed send 重放。",
    )

    args = parser.parse_args()
    repo_root = _repo_root()

    if args.commit_group_broadcast:
        committed_entry = _as_non_empty_str(os.environ.get(COMMITTED_SEND_ENTRY_ENV))
        if committed_entry != COMMITTED_SEND_ENTRY_VALUE:
            raise ChatRegistryError(
                "真实群播已强制收敛为单一入口：请只通过 scripts/run_daily_pipeline.py 发起 committed send；"
                "一旦检测到 group broadcast 成功，不允许对同一逻辑主题再次执行 committed send。"
            )

    _sync_chat_registry_from_feishu(repo_root=repo_root, chat_registry_output=args.chat_registry)

    registry_path: Optional[Path] = None
    if args.chat_registry:
        p_registry = Path(args.chat_registry)
        if not p_registry.is_absolute():
            p_registry = repo_root / p_registry
        registry_path = _validate_safe_path_under_repo(p_registry, repo_root=repo_root, arg_name="chat-registry")
    group_entry = get_chat_registry_entry(usage=args.broadcast_usage, path=registry_path)
    if args.admin_email == "yuqinan@bytedance.com" and group_entry.admin_email:
        args.admin_email = group_entry.admin_email

    alerts_path = Path(args.alerts_file)
    if not alerts_path.is_absolute():
        alerts_path = repo_root / alerts_path
    alerts_path = _validate_safe_path_under_repo(alerts_path, repo_root=repo_root, arg_name="alerts-file")

    if args.log_file:
        log_path = Path(args.log_file)
        if not log_path.is_absolute():
            log_path = repo_root / log_path
        log_path = _validate_safe_path_under_repo(log_path, repo_root=repo_root, arg_name="log-file")
    else:
        utc_day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_path = repo_root / "notification_logs" / f"notify_{utc_day}.jsonl"

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    payload_root = repo_root / "notification_payloads" / run_id
    logger = NotificationLogger(log_path)
    alerts = _load_alerts(alerts_path)

    group_ok = _process_group_broadcast(
        args=args,
        alerts=alerts,
        alerts_path=alerts_path,
        repo_root=repo_root,
        payload_root=payload_root,
        run_id=run_id,
        logger=logger,
        group_entry=group_entry,
    )
    private_ok = _process_private_routes(
        args=args,
        alerts=alerts,
        alerts_path=alerts_path,
        repo_root=repo_root,
        payload_root=payload_root,
        run_id=run_id,
        logger=logger,
    )
    effective_private_ok = private_ok
    if not private_ok and group_ok and args.commit_group_broadcast and not args.fail_on_private_errors:
        effective_private_ok = True
        logger.append(
            {
                "run_id": run_id,
                "mode": "meta",
                "result": "private_errors_ignored_after_group_success",
                "group_ok": group_ok,
                "private_ok": private_ok,
                "effective_private_ok": effective_private_ok,
                "reason": "group broadcast 已成功；为避免对同一逻辑主题重放 committed send，本次不因私聊失败返回非 0。",
            }
        )
    return 0 if (group_ok and effective_private_ok) else 2


if __name__ == "__main__":
    raise SystemExit(main())
