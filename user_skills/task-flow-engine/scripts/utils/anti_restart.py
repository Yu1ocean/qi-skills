from __future__ import annotations

import json
import os
import signal
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ACTIVE_STATUSES = {"started", "running", "in_progress", "terminating"}
DEFAULT_STALE_SECONDS = 2 * 60 * 60


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(dt: Optional[datetime] = None) -> str:
    return (dt or _utcnow()).isoformat()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    _ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _safe_pid_exists(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class CheckpointStore:
    """Reusable checkpoint store for long-running tasks.

    The payload is intentionally JSON-only, so future scripts can inspect / recover
    without importing Python objects.
    """

    def __init__(self, path: Path, *, task_name: Optional[str] = None, task_id: Optional[str] = None):
        self.path = Path(path)
        self.task_name = task_name
        self.task_id = task_id
        self.version = 1

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload

    def save(
        self,
        *,
        status: str,
        step: str,
        progress: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        note: Optional[str] = None,
        pid: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        current = self.load()
        started_at = current.get("started_at") or _isoformat()
        body: Dict[str, Any] = {
            "version": self.version,
            "task_name": self.task_name or current.get("task_name") or self.path.stem,
            "task_id": self.task_id or current.get("task_id") or self.path.stem,
            "status": status,
            "step": step,
            "pid": int(pid if pid is not None else current.get("pid") or os.getpid()),
            "started_at": started_at,
            "updated_at": _isoformat(),
            "heartbeat_at": _isoformat(),
            "progress": progress or current.get("progress") or {},
            "payload": payload or current.get("payload") or {},
        }
        if note:
            body["note"] = note
        if extra:
            body.update(extra)
        _atomic_write_json(self.path, body)
        return body

    def heartbeat(
        self,
        *,
        step: Optional[str] = None,
        progress: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        note: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        current = self.load()
        return self.save(
            status=str(current.get("status") or "running"),
            step=step or str(current.get("step") or "heartbeat"),
            progress=progress or current.get("progress") or {},
            payload=payload or current.get("payload") or {},
            note=note or current.get("note"),
            pid=int(current.get("pid") or os.getpid()),
            extra=extra,
        )

    def mark_completed(
        self,
        *,
        step: str = "completed",
        progress: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        note: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.save(
            status="completed",
            step=step,
            progress=progress,
            payload=payload,
            note=note,
            extra=extra,
        )

    def mark_failed(
        self,
        *,
        step: str,
        note: str,
        progress: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.save(
            status="failed",
            step=step,
            progress=progress,
            payload=payload,
            note=note,
            extra=extra,
        )


class SigtermGuard:
    """Persist a last-gasp checkpoint when SIGTERM / SIGINT arrives."""

    def __init__(
        self,
        checkpoint: CheckpointStore,
        *,
        snapshot_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        exit_code: Optional[int] = 143,
    ):
        self.checkpoint = checkpoint
        self.snapshot_provider = snapshot_provider
        self.exit_code = exit_code
        self._previous: Dict[int, Any] = {}
        self.triggered = False

    def install(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            self._previous[sig] = signal.getsignal(sig)
            signal.signal(sig, self._handle)

    def uninstall(self) -> None:
        for sig, previous in self._previous.items():
            signal.signal(sig, previous)
        self._previous = {}

    def _handle(self, signum: int, _frame: Any) -> None:
        self.triggered = True
        signal_name = signal.Signals(signum).name
        payload = self.snapshot_provider() if self.snapshot_provider else {}
        self.checkpoint.save(
            status="terminating",
            step=str(payload.get("current_step") or "signal_interrupt"),
            progress={"signal": signal_name},
            payload=payload,
            note=f"⚠️ [被系统强杀] 捕获到 {signal_name}，已执行最后一次断点落盘。",
            extra={"signal": signal_name, "terminated_at": _isoformat()},
        )
        if self.exit_code is not None:
            raise SystemExit(self.exit_code)


@dataclass
class ZombieFinding:
    task_id: str
    task_name: str
    checkpoint_path: str
    pid: Optional[int]
    status_before: str
    last_heartbeat_at: Optional[str]
    stale_seconds: int
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": f"zombie:{self.task_id}:{self.pid or 'no_pid'}",
            "row": 0,
            "task": self.task_name,
            "status": self.status_before,
            "owners": [],
            "ddl_raw": None,
            "ddl_parsed": None,
            "delta_days": None,
            "alert_category": "僵尸任务",
            "reason": self.reason,
            "issue_type": "zombie_task",
            "overdue_days": None,
            "abnormal_days": None,
            "stage": "admin",
            "checkpoint_path": self.checkpoint_path,
            "pid": self.pid,
            "last_heartbeat_at": self.last_heartbeat_at,
            "stale_seconds": self.stale_seconds,
        }


class ZombieSweeper:
    """Scan checkpoint files and mark fake-dead tasks as zombie."""

    def __init__(self, checkpoint_root: Path, *, stale_after_seconds: int = DEFAULT_STALE_SECONDS):
        self.checkpoint_root = Path(checkpoint_root)
        self.stale_after_seconds = stale_after_seconds

    def scan(self) -> List[ZombieFinding]:
        if not self.checkpoint_root.exists():
            return []

        findings: List[ZombieFinding] = []
        for path in sorted(self.checkpoint_root.rglob("*.json")):
            payload = self._load_candidate(path)
            if not payload:
                continue
            finding = self._inspect(path, payload)
            if finding is None:
                continue
            findings.append(finding)
        return findings

    def _load_candidate(self, path: Path) -> Dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        if "status" not in payload or "heartbeat_at" not in payload:
            return {}
        return payload

    def _inspect(self, path: Path, payload: Dict[str, Any]) -> Optional[ZombieFinding]:
        status = str(payload.get("status") or "").strip()
        if status not in ACTIVE_STATUSES:
            return None

        heartbeat_text = str(payload.get("heartbeat_at") or payload.get("updated_at") or "").strip()
        if not heartbeat_text:
            return None
        try:
            heartbeat_at = datetime.fromisoformat(heartbeat_text)
        except ValueError:
            return None
        if heartbeat_at.tzinfo is None:
            heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)

        stale_seconds = int((_utcnow() - heartbeat_at).total_seconds())
        if stale_seconds < self.stale_after_seconds:
            return None

        pid = payload.get("pid")
        pid_int = int(pid) if isinstance(pid, int) or (isinstance(pid, str) and pid.isdigit()) else None
        if _safe_pid_exists(pid_int):
            return None

        task_id = str(payload.get("task_id") or path.stem)
        task_name = str(payload.get("task_name") or task_id)
        reason = (
            f"Heartbeat 超时 {stale_seconds}s，且 PID {pid_int if pid_int is not None else '[MISSING_PID]'} 已失联，"
            f"判定为假死任务 [断链_待自愈]。"
        )

        payload["status"] = "zombie"
        payload["zombie_detected_at"] = _isoformat()
        payload["zombie_reason"] = reason
        payload["last_known_pid_alive"] = False
        _atomic_write_json(path, payload)

        return ZombieFinding(
            task_id=task_id,
            task_name=task_name,
            checkpoint_path=str(path),
            pid=pid_int,
            status_before=status,
            last_heartbeat_at=heartbeat_text,
            stale_seconds=stale_seconds,
            reason=reason,
        )


def inject_zombie_alerts(alerts: Dict[str, Any], findings: List[ZombieFinding], *, checkpoint_root: Path, stale_after_seconds: int) -> Dict[str, Any]:
    """Merge Zombie Sweeper findings into QA Patrol alert payload."""

    report = {
        "scan_root": str(checkpoint_root),
        "stale_after_seconds": stale_after_seconds,
        "detected_count": len(findings),
        "findings": [item.to_dict() for item in findings],
    }
    alerts["zombie_sweeper"] = report
    if not findings:
        return alerts

    items = report["findings"]
    grouped = alerts.setdefault("grouped_results", {})
    grouped["僵尸任务"] = list(items)

    summary = alerts.setdefault("summary", {})
    counts = summary.setdefault("counts", {})
    counts["僵尸任务"] = len(items)
    summary["zombie_count"] = len(items)
    summary["total_findings"] = int(summary.get("total_findings") or 0) + len(items)

    routes = alerts.setdefault("routes", {})
    admin = routes.setdefault("admin", {"count": 0, "items": [], "message": ""})
    existing_admin_items = list(admin.get("items") or [])
    admin["items"] = existing_admin_items + items
    admin["count"] = len(admin["items"])

    today = summary.get("today") or _utcnow().date().isoformat()
    lines = [
        f"🧟 **僵尸任务扫盲告警**（{today}，共 {len(items)} 条）",
        "",
    ]
    for item in items:
        lines.append(
            f"- `{item['task']}` · PID={item['pid'] if item['pid'] is not None else '[MISSING_PID]'} · {item['reason']}"
        )
    zombie_message = "\n".join(lines).strip()
    admin_message = str(admin.get("message") or "").strip()
    admin["message"] = f"{admin_message}\n\n{zombie_message}".strip() if admin_message else zombie_message
    return alerts
