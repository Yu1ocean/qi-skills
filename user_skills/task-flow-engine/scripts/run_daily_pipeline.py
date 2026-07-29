#!/usr/bin/env python3
"""Daily pipeline for QA Patrol.

把每日早 8 点的 QA Patrol 收敛为“底层安全体检 + 条件式业务催办”脚本：
- 周二 / 周四：执行完整业务链路（任务巡检 → 催办分发 → 通知日志回写）
- 其余日期：强制进入 `safety_only`，仅保留鉴权、Chat Registry 同步、Zombie Sweeper 等安全检查

说明：
- 保留原 CLI 参数以兼容既有 cron 配置，避免因为入口签名变化误伤定时任务
- 运行环境仍建议通过 Aime bash include_secrets=true 执行（否则飞书鉴权会缺参数）
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from scripts.utils.anti_restart import ACTIVE_STATUSES, CheckpointStore, SigtermGuard, ZombieSweeper, _safe_pid_exists
from task_flow_engine.chat_registry import DEFAULT_BROADCAST_USAGE, default_broadcast_target_chat
from task_flow_engine.chat_registry_sync import DEFAULT_CHAT_REGISTRY_SPREADSHEET_URL


def _repo_root() -> Path:
    # user_skills/task-flow-engine/scripts/run_daily_pipeline.py
    return Path(__file__).resolve().parents[1]


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _run(cmd: Sequence[str], *, cwd: Optional[Path] = None) -> int:
    p = subprocess.run(list(cmd), cwd=str(cwd) if cwd else None)
    return p.returncode


def _checkpoint_has_active_owner(checkpoint: CheckpointStore) -> bool:
    current = checkpoint.load()
    status = str(current.get("status") or "").strip()
    pid = current.get("pid")
    if status not in ACTIVE_STATUSES:
        return False
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int == os.getpid():
        return False
    return _safe_pid_exists(pid_int)


def _resolve_path_under_repo(repo_root: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = repo_root / path
    path = path.resolve()
    try:
        path.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ValueError(f"路径必须位于任务目录内：{path}") from exc
    return path


def _run_zombie_sweeper(*, checkpoint_root: Path, stale_after_seconds: int) -> Dict[str, Any]:
    findings = ZombieSweeper(checkpoint_root, stale_after_seconds=stale_after_seconds).scan()
    return {
        "ok": True,
        "scan_root": str(checkpoint_root),
        "stale_after_seconds": stale_after_seconds,
        "detected_count": len(findings),
        "findings": [item.to_dict() for item in findings],
    }


def _write_safety_report(report_path: Path, payload: Dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_notification_log(log_path: Path, record: Dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def _sync_chat_registry_from_feishu(*, repo_root: Path, chat_registry_output: Optional[str]) -> int:
    cmd = [
        sys.executable,
        "scripts/sync_registry_from_feishu.py",
        "--spreadsheet",
        DEFAULT_CHAT_REGISTRY_SPREADSHEET_URL,
        "--skip-auth",
    ]
    if chat_registry_output:
        cmd.extend(["--output", chat_registry_output])
    return _run(cmd, cwd=repo_root)


TRAVEL_DASHBOARD_STABLE_ALIAS = "travel-dashboard-live"
TRAVEL_DASHBOARD_DEPLOY_META_REL = f"published/{TRAVEL_DASHBOARD_STABLE_ALIAS}/deploy_meta.json"


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
    card_match = re.search(r"'card_id'\s*:\s*'?(\d+)'?", stdout)
    if card_match:
        fallback["card_id"] = card_match.group(1)
    message_match = re.search(r"'message_id'\s*:\s*'([^']+)'", stdout)
    if message_match:
        fallback["message_id"] = message_match.group(1)
    return fallback or None


def _materialize_travel_dashboard_publish_dir(*, workspace_root: Path, production_html: Path, production_json: Path) -> Dict[str, str]:
    publish_dir = workspace_root / "published" / TRAVEL_DASHBOARD_STABLE_ALIAS
    publish_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(production_html, publish_dir / "index.html")
    if production_json.exists():
        shutil.copyfile(production_json, publish_dir / production_json.name)
    deploy_meta_path = workspace_root / TRAVEL_DASHBOARD_DEPLOY_META_REL
    if not deploy_meta_path.exists():
        deploy_meta_path.write_text(
            json.dumps(
                {
                    "stable_alias": TRAVEL_DASHBOARD_STABLE_ALIAS,
                    "live_url": "",
                    "updated_at": "",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return {
        "publish_dir": str(publish_dir),
        "stable_alias": TRAVEL_DASHBOARD_STABLE_ALIAS,
        "deploy_meta_path": str(deploy_meta_path),
    }


def _maybe_push_travel_dashboard_card(
    *,
    workspace_root: Path,
    repo_root: Path,
    weekday: int,
    args: argparse.Namespace,
    travel_refresh_result: Dict[str, Any],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"enabled": weekday == 5, "status": "skipped", "reason": "not_saturday"}
    if weekday != 5:
        return result

    deploy_meta_path = workspace_root / TRAVEL_DASHBOARD_DEPLOY_META_REL
    if not deploy_meta_path.exists():
        return {"enabled": True, "status": "skipped", "reason": f"deploy_meta_missing:{deploy_meta_path}"}

    try:
        deploy_meta = json.loads(deploy_meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"enabled": True, "status": "skipped", "reason": f"deploy_meta_invalid:{exc}"}

    live_url = str(deploy_meta.get("live_url") or "").strip()
    if not live_url:
        return {"enabled": True, "status": "skipped", "reason": "live_url_missing"}

    receiver_id = args.admin_email
    id_type = "email"
    if args.commit_group_broadcast and args.confirm_group_broadcast:
        registry_path = Path(args.chat_registry).resolve() if args.chat_registry else None
        target_chat = default_broadcast_target_chat(registry_path=registry_path, usage=args.broadcast_usage)
        receiver_id = str(target_chat.get("chat_id") or "").strip() or args.admin_email
        id_type = "chat_id" if receiver_id.startswith("oc_") else "email"

    payload_dir = repo_root / "notification_payloads" / datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    payload_dir.mkdir(parents=True, exist_ok=True)
    card_path = payload_dir / f"travel_dashboard_{weekday}.card.json"
    dashboard_window = travel_refresh_result.get("window") or {}
    card_payload = {
        "name": "TravelDashboardLiveCard",
        "dsl": {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": "周六差旅大屏快照"},
                "template": "blue",
            },
            "body": {
                "elements": [
                    {"tag": "markdown", "content": "#### 周六自动推送\n已刷新最新差旅大屏，可直接点开查看。"},
                    {
                        "tag": "div",
                        "text": {
                            "tag": "plain_text",
                            "content": f"时间窗：{dashboard_window.get('start_time', '--')} ~ {dashboard_window.get('end_time', '--')}",
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "打开固定大屏链接"},
                        "type": "primary",
                        "behaviors": [{"type": "open_url", "default_url": live_url}],
                    },
                ]
            },
        },
    }
    card_path.write_text(json.dumps(card_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.dry_run:
        return {
            "enabled": True,
            "status": "dry_run",
            "receiver_id": receiver_id,
            "id_type": id_type,
            "card_payload": str(card_path),
            "live_url": live_url,
        }

    im_skill_dir = workspace_root / "inner_skills" / "feishu-im-send"
    create_cmd = [sys.executable, "scripts/im_send.py", "create_card", str(card_path)]
    create_proc = subprocess.run(create_cmd, cwd=str(im_skill_dir), capture_output=True, text=True)
    create_parsed = _parse_send_stdout(create_proc.stdout)
    if create_proc.returncode != 0 or not create_parsed or not create_parsed.get("card_id"):
        return {
            "enabled": True,
            "status": "failed_create_card",
            "receiver_id": receiver_id,
            "id_type": id_type,
            "card_payload": str(card_path),
            "stdout": create_proc.stdout,
            "stderr": create_proc.stderr,
        }

    card_id = str(create_parsed.get("card_id"))
    send_cmd = [sys.executable, "scripts/im_send.py", "send", receiver_id, "interactive", card_id, f"--id-type={id_type}"]
    send_proc = subprocess.run(send_cmd, cwd=str(im_skill_dir), capture_output=True, text=True)
    send_parsed = _parse_send_stdout(send_proc.stdout)
    if send_proc.returncode != 0:
        return {
            "enabled": True,
            "status": "failed_send_card",
            "receiver_id": receiver_id,
            "id_type": id_type,
            "card_payload": str(card_path),
            "card_id": card_id,
            "stdout": send_proc.stdout,
            "stderr": send_proc.stderr,
        }

    return {
        "enabled": True,
        "status": "sent",
        "receiver_id": receiver_id,
        "id_type": id_type,
        "card_payload": str(card_path),
        "card_id": card_id,
        "send_result": send_parsed,
        "live_url": live_url,
    }


def _run_travel_dashboard_refresh(*, workspace_root: Path) -> Dict[str, Any]:
    local_tz = timezone(timedelta(hours=8))
    now_local = datetime.datetime.now(local_tz)
    lookback_hours = 30
    day_start = (now_local - datetime.timedelta(hours=lookback_hours)).replace(minute=0, second=0, microsecond=0)
    day_end = now_local.replace(second=0, microsecond=0)

    skill_root = workspace_root / "user_skills" / "team-travel-dashboard-generator"
    script_path = skill_root / "scripts" / "build_travel_dashboard.py"
    backfill_script = workspace_root / "tools" / "travel_backfill_write_sheet.py"
    output_dir = skill_root / "output"
    collect_json = output_dir / "travel_dashboard.daily_increment.json"
    audit_json = workspace_root / "output" / "travel_backfill_sheet_audit.json"
    production_json = output_dir / "travel_dashboard.prod.json"
    production_html = output_dir / "travel_dashboard.prod.html"
    dynamic_ui_rel = "../../.aime/dynamic-ui/react-card/team_travel_dashboard_daily.html"
    dynamic_ui_abs = workspace_root / ".aime" / "dynamic-ui" / "react-card" / "team_travel_dashboard_daily.html"

    required_paths = {
        "travel_dashboard_script": script_path,
        "travel_backfill_script": backfill_script,
    }
    missing = [name for name, path in required_paths.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"差旅刷新依赖缺失：{missing}")

    commands = [
        {
            "step": "collect_incremental_travel_mails",
            "cmd": [
                sys.executable,
                str(script_path),
                "collect-mails",
                "--mode",
                "auto",
                "--start-time",
                day_start.strftime("%Y-%m-%d %H:%M"),
                "--end-time",
                day_end.strftime("%Y-%m-%d %H:%M"),
                "--output-json",
                str(collect_json.relative_to(skill_root)),
                "--geo-cache",
                "output/geo_cache.json",
                "--footprint-library",
                "output/travel_footprint_library.json",
            ],
            "cwd": skill_root,
        },
        {
            "step": "append_travel_sheet2",
            "cmd": [
                sys.executable,
                str(backfill_script),
                str(collect_json),
                str(audit_json),
            ],
            "cwd": workspace_root,
        },
        {
            "step": "refresh_travel_dashboard_assets",
            "cmd": [
                sys.executable,
                str(skill_root / "scripts" / "build_and_publish_daily.py"),
                "--days",
                "30",
                "--mode",
                "auto",
            ],
            "cwd": skill_root,
        },
    ]

    steps = []
    for item in commands:
        rc = _run(item["cmd"], cwd=item["cwd"])
        steps.append({
            "step": item["step"],
            "rc": rc,
            "cwd": str(item["cwd"]),
            "command": item["cmd"],
        })
        if rc != 0:
            raise RuntimeError(f"差旅大屏刷新步骤失败：{item['step']} (rc={rc})")

    row_count = None
    if audit_json.exists():
        try:
            audit_payload = json.loads(audit_json.read_text(encoding="utf-8"))
            row_count = audit_payload.get("row_count")
        except Exception:
            row_count = None

    publish_info = _materialize_travel_dashboard_publish_dir(
        workspace_root=workspace_root,
        production_html=production_html,
        production_json=production_json,
    )

    return {
        "enabled": True,
        "window": {
            "start_time": day_start.isoformat(),
            "end_time": day_end.isoformat(),
            "timezone": "Asia/Shanghai",
            "lookback_hours": lookback_hours,
        },
        "collect_json": str(collect_json),
        "audit_output": str(audit_json),
        "production_json": str(production_json),
        "production_html": str(production_html),
        "publish_dir": publish_info["publish_dir"],
        "stable_alias": publish_info["stable_alias"],
        "deploy_meta_path": publish_info["deploy_meta_path"],
        "dynamic_ui_html": str(dynamic_ui_abs),
        "sheet_append_row_count": row_count,
        "steps": steps,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--task-spreadsheet",
        required=True,
        help="任务库所在飞书表格 URL 或 token（包含 sheet=任务库 / 团队名单 / Aime日志）",
    )
    ap.add_argument(
        "--log-spreadsheet",
        required=True,
        help="通知日志落盘的主底表 URL 或 token（包含 sheet=Task_Notify_Logs）",
    )
    ap.add_argument("--task-sheet-title", default="任务库")
    ap.add_argument("--roster-sheet-title", default="团队名单")
    ap.add_argument(
        "--target-chat",
        default=None,
        help="兼容旧参数：仅用于断言等于 Chat Registry 对应用途的 chat_id；不再作为 chat_id 来源。",
    )
    ap.add_argument(
        "--chat-registry",
        default=None,
        help="Chat Registry JSON 路径（相对路径默认相对于 task-flow-engine 根目录）。",
    )
    ap.add_argument(
        "--broadcast-usage",
        default=DEFAULT_BROADCAST_USAGE,
        help="Chat Registry 中的群用途 key（默认：task_patrol_broadcast）。",
    )
    ap.add_argument("--admin-email", default="yuqinan@bytedance.com")
    ap.add_argument("--due-soon-days", type=int, default=2)
    ap.add_argument("--anti-restart-checkpoint", default=".runtime/qa_patrol_daily_pipeline.checkpoint.json")
    ap.add_argument("--checkpoint-root", default=".runtime/checkpoints")
    ap.add_argument("--zombie-stale-seconds", type=int, default=2 * 60 * 60)
    ap.add_argument("--disable-zombie-sweeper", action="store_true")
    ap.add_argument("--send-to-admin-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--commit-group-broadcast", action="store_true")
    ap.add_argument("--confirm-group-broadcast", default=None)

    args = ap.parse_args()

    repo_root = _repo_root()
    if args.zombie_stale_seconds <= 0:
        raise ValueError("zombie-stale-seconds 必须为正整数")

    checkpoint_path = _resolve_path_under_repo(repo_root, args.anti_restart_checkpoint)
    checkpoint_root = _resolve_path_under_repo(repo_root, args.checkpoint_root)
    checkpoint = CheckpointStore(checkpoint_path, task_name="qa_patrol_daily_pipeline", task_id="qa_patrol_daily_pipeline")
    if _checkpoint_has_active_owner(checkpoint):
        current = checkpoint.load()
        current_pid = current.get("pid")
        current_step = current.get("step") or "unknown"
        note = (
            f"检测到已有运行中的 qa_patrol_daily_pipeline 进程(pid={current_pid}, step={current_step})，"
            "本次重复触发已在发送前熔断退出。"
        )
        print(f"[WARN] {note}", file=sys.stderr)
        return 0

    runtime_state: Dict[str, Any] = {"current_step": "bootstrap"}
    sigterm_guard = SigtermGuard(
        checkpoint,
        snapshot_provider=lambda: {
            **runtime_state,
            "safety_report": str(runtime_state.get("safety_report") or ""),
        },
    )
    sigterm_guard.install()

    try:
        utc_now = datetime.datetime.now(timezone.utc)
        utc_day = utc_now.strftime("%Y-%m-%d")
        weekday = datetime.datetime.today().weekday()
        notify_window_open = weekday in (1, 3)
        mode = "full_dispatch" if notify_window_open else "patrol_and_persist_only"

        safety_report = repo_root / "qa_patrol_reports" / f"safety_report_{utc_day}.json"
        alerts_file = repo_root / f"alerts_{utc_day}.json"
        notify_log_file = repo_root / "notification_logs" / f"notify_{utc_day}.jsonl"
        skipped_steps = [] if notify_window_open else ["task_patrol_notify"]

        runtime_state.update({
            "current_step": "bootstrap",
            "safety_report": str(safety_report),
            "weekday": weekday,
            "notify_window_open": notify_window_open,
            "notify_window_closed": not notify_window_open,
            "business_dispatch_enabled": notify_window_open,
            "business_dispatch_disabled": not notify_window_open,
            "mode": mode,
            "alerts_file": str(alerts_file),
            "notify_log_file": str(notify_log_file),
            "skipped_steps": skipped_steps,
            "patrol_ran": False,
            "notify_attempted": False,
            "daily_log_persisted": False,
            "travel_refresh": {"enabled": True, "status": "pending"},
        })
        checkpoint.save(
            status="running",
            step="bootstrap",
            progress={"phase": "init", "mode": mode},
            payload=runtime_state,
            note=(
                "QA Patrol 每日管线启动：当前为 full_dispatch 模式，将执行任务巡检、催办分发与通知日志回写。"
                if notify_window_open
                else "QA Patrol 每日管线启动：当前为 patrol_and_persist_only 模式，将执行任务巡检与通知日志落库，群聊发信仅周二/周四开放。"
            ),
        )

        # Step 0: bytedcli-auth（执行人身份穿透）
        auth_sh = _workspace_root() / "inner_skills" / "bytedcli-auth" / "scripts" / "bytedcli_auth.sh"
        runtime_state["current_step"] = "auth"
        checkpoint.heartbeat(step="auth", progress={"phase": "auth", "mode": mode}, payload=runtime_state)
        if auth_sh.exists():
            rc = _run(["bash", str(auth_sh)], cwd=auth_sh.parent)
            if rc != 0:
                checkpoint.mark_failed(step="auth", note=f"bytedcli-auth failed with rc={rc}", payload=runtime_state)
                return rc
        else:
            print(f"[WARN] bytedcli-auth not found, skip: {auth_sh}", file=sys.stderr)

        # Step 1: sync Chat Registry from Feishu SSOT
        runtime_state["current_step"] = "sync_chat_registry"
        checkpoint.heartbeat(step="sync_chat_registry", progress={"phase": "registry_sync", "mode": mode}, payload=runtime_state)
        rc = _sync_chat_registry_from_feishu(
            repo_root=repo_root,
            chat_registry_output=args.chat_registry,
        )
        runtime_state["chat_registry_sync_rc"] = rc
        if rc != 0:
            checkpoint.mark_failed(step="sync_chat_registry", note=f"sync registry failed with rc={rc}", payload=runtime_state)
            return rc

        # Step 2: base safety checks (Zombie Sweeper 等)
        runtime_state["current_step"] = "zombie_sweeper"
        zombie_report: Dict[str, Any] = {"ok": False, "skipped": True, "reason": "disabled by flag"}
        if not args.disable_zombie_sweeper:
            checkpoint.heartbeat(step="zombie_sweeper", progress={"phase": "zombie_sweeper", "mode": mode}, payload=runtime_state)
            zombie_report = _run_zombie_sweeper(
                checkpoint_root=checkpoint_root,
                stale_after_seconds=args.zombie_stale_seconds,
            )
            runtime_state["zombie_sweeper"] = zombie_report
            checkpoint.heartbeat(
                step="zombie_sweeper",
                progress={"phase": "zombie_sweeper", "mode": mode, "detected_count": zombie_report.get("detected_count", 0)},
                payload=runtime_state,
            )

        business_results: Dict[str, Any] = {
            "enabled": True,
            "notify_window_open": notify_window_open,
            "steps": [],
        }

        runtime_state["current_step"] = "travel_dashboard_refresh"
        checkpoint.heartbeat(step="travel_dashboard_refresh", progress={"phase": "travel_refresh", "mode": mode}, payload=runtime_state)
        try:
            travel_refresh_result = _run_travel_dashboard_refresh(workspace_root=_workspace_root())
        except Exception as exc:
            runtime_state["travel_refresh"] = {"enabled": True, "status": "failed", "error": str(exc)}
            checkpoint.mark_failed(step="travel_dashboard_refresh", note=f"travel dashboard refresh failed: {exc}", payload=runtime_state)
            return 1
        runtime_state["travel_refresh"] = {**travel_refresh_result, "status": "completed"}
        checkpoint.heartbeat(
            step="travel_dashboard_refresh",
            progress={
                "phase": "travel_refresh",
                "mode": mode,
                "sheet_append_row_count": travel_refresh_result.get("sheet_append_row_count"),
            },
            payload=runtime_state,
        )

        runtime_state["current_step"] = "travel_dashboard_card_push"
        dashboard_push_result = _maybe_push_travel_dashboard_card(
            workspace_root=_workspace_root(),
            repo_root=repo_root,
            weekday=weekday,
            args=args,
            travel_refresh_result=travel_refresh_result,
        )
        runtime_state["travel_dashboard_card_push"] = dashboard_push_result
        checkpoint.heartbeat(
            step="travel_dashboard_card_push",
            progress={
                "phase": "travel_dashboard_card_push",
                "mode": mode,
                "status": dashboard_push_result.get("status"),
            },
            payload=runtime_state,
        )

        runtime_state["current_step"] = "run_task_patrol_save"
        checkpoint.heartbeat(step="run_task_patrol_save", progress={"phase": "task_patrol", "mode": mode}, payload=runtime_state)
        patrol_cmd = [
            sys.executable,
            "scripts/run_task_patrol_save.py",
            "--spreadsheet",
            args.task_spreadsheet,
            "--task-sheet-title",
            args.task_sheet_title,
            "--roster-sheet-title",
            args.roster_sheet_title,
            "--due-soon-days",
            str(args.due_soon_days),
            "--broadcast-usage",
            args.broadcast_usage,
            "--output",
            str(alerts_file),
        ]
        if args.chat_registry:
            patrol_cmd.extend(["--chat-registry", args.chat_registry])
        if args.target_chat:
            patrol_cmd.extend(["--target-chat", args.target_chat])
        rc = _run(patrol_cmd, cwd=repo_root)
        business_results["steps"].append({"step": "run_task_patrol_save", "rc": rc, "output": str(alerts_file)})
        runtime_state["task_patrol_rc"] = rc
        runtime_state["patrol_ran"] = rc == 0
        if rc != 0:
            checkpoint.mark_failed(step="run_task_patrol_save", note=f"run_task_patrol_save failed with rc={rc}", payload=runtime_state)
            return rc

        if notify_window_open:
            runtime_state["current_step"] = "task_patrol_notify"
            runtime_state["notify_attempted"] = True
            checkpoint.heartbeat(step="task_patrol_notify", progress={"phase": "notify", "mode": mode}, payload=runtime_state)
            notify_cmd = [
                sys.executable,
                "scripts/task_patrol_notify.py",
                "--alerts-file",
                str(alerts_file),
                "--broadcast-usage",
                args.broadcast_usage,
                "--admin-email",
                args.admin_email,
                "--log-file",
                str(notify_log_file),
            ]
            if args.chat_registry:
                notify_cmd.extend(["--chat-registry", args.chat_registry])
            if args.target_chat:
                notify_cmd.extend(["--target-chat-id", args.target_chat])
            if args.send_to_admin_only:
                notify_cmd.append("--send-to-admin-only")
            if args.dry_run:
                notify_cmd.append("--dry-run")
            if args.commit_group_broadcast:
                notify_cmd.append("--commit-group-broadcast")
            if args.confirm_group_broadcast:
                notify_cmd.extend(["--confirm-group-broadcast", args.confirm_group_broadcast])
            restore_notify_entry = os.environ.get("TASK_FLOW_NOTIFY_ALLOW_COMMITTED_SEND")
            if args.commit_group_broadcast:
                os.environ["TASK_FLOW_NOTIFY_ALLOW_COMMITTED_SEND"] = "run_daily_pipeline"
            try:
                rc = _run(notify_cmd, cwd=repo_root)
            finally:
                if args.commit_group_broadcast:
                    if restore_notify_entry is None:
                        os.environ.pop("TASK_FLOW_NOTIFY_ALLOW_COMMITTED_SEND", None)
                    else:
                        os.environ["TASK_FLOW_NOTIFY_ALLOW_COMMITTED_SEND"] = restore_notify_entry
            business_results["steps"].append({"step": "task_patrol_notify", "rc": rc, "log_file": str(notify_log_file)})
            runtime_state["task_patrol_notify_rc"] = rc
            if rc != 0:
                checkpoint.mark_failed(step="task_patrol_notify", note=f"task_patrol_notify failed with rc={rc}", payload=runtime_state)
                return rc
        else:
            _append_notification_log(
                notify_log_file,
                {
                    "run_id": f"{utc_day.replace('-', '')}_weekday_gate_closed",
                    "created_at": datetime.datetime.now(timezone.utc).isoformat(),
                    "mode": "group",
                    "alerts_file": str(alerts_file.name),
                    "msg_type": "interactive",
                    "count": 0,
                    "message_preview": f"任务巡检已执行；今日 weekday={weekday} 非周二/周四，未触发 task_patrol_notify。",
                    "logical_topic_key": f"task-flow-engine|group|{utc_day}",
                    "payload_path": "",
                    "receiver": {},
                    "result": "skipped_weekday_gate",
                    "error": "",
                },
            )
            business_results["steps"].append({"step": "task_patrol_notify", "skipped": True, "reason": "weekday_gate_closed"})

        runtime_state["current_step"] = "upload_notify_logs_to_sheet"
        checkpoint.heartbeat(step="upload_notify_logs_to_sheet", progress={"phase": "upload_notify_logs", "mode": mode}, payload=runtime_state)
        upload_cmd = [
            sys.executable,
            "scripts/upload_notify_logs_to_sheet.py",
            "--spreadsheet",
            args.log_spreadsheet,
            "--log-file",
            str(notify_log_file),
            "--skip-auth",
        ]
        rc = _run(upload_cmd, cwd=repo_root)
        business_results["steps"].append({"step": "upload_notify_logs_to_sheet", "rc": rc, "spreadsheet": args.log_spreadsheet})
        runtime_state["upload_notify_logs_rc"] = rc
        runtime_state["daily_log_persisted"] = rc == 0
        if rc != 0:
            checkpoint.mark_failed(step="upload_notify_logs_to_sheet", note=f"upload_notify_logs_to_sheet failed with rc={rc}", payload=runtime_state)
            return rc

        runtime_state["current_step"] = "write_safety_report"
        checkpoint.heartbeat(step="write_safety_report", progress={"phase": "write_safety_report", "mode": mode}, payload=runtime_state)
        safety_payload = {
            "generated_at": datetime.datetime.now(timezone.utc).isoformat(),
            "pipeline": "qa_patrol_daily_pipeline",
            "mode": mode,
            "weekday": weekday,
            "notify_window_open": notify_window_open,
            "notify_window_closed": not notify_window_open,
            "business_dispatch_enabled": notify_window_open,
            "business_dispatch_disabled": not notify_window_open,
            "patrol_ran": runtime_state.get("patrol_ran", False),
            "notify_attempted": runtime_state.get("notify_attempted", False),
            "daily_log_persisted": runtime_state.get("daily_log_persisted", False),
            "skipped_steps": runtime_state["skipped_steps"],
            "chat_registry_sync": {
                "ok": runtime_state.get("chat_registry_sync_rc") == 0,
                "output": args.chat_registry,
                "source_spreadsheet": DEFAULT_CHAT_REGISTRY_SPREADSHEET_URL,
            },
            "zombie_sweeper": zombie_report,
            "travel_refresh": runtime_state.get("travel_refresh", {}),
            "travel_dashboard_card_push": runtime_state.get("travel_dashboard_card_push", {}),
            "business_pipeline": business_results,
            "notes": [
                "脚本已硬编码：差旅大屏增量刷新链路每天执行一次（增量邮件抓取 → Sheet 2 追加 → 大屏 HTML / Dynamic UI 刷新）。",
                "脚本已硬编码：发布目录固定为 published/travel-dashboard-live，供稳定别名部署复用。",
                "脚本已硬编码：任务巡检与通知日志回写每天执行；群聊发信仅周二(1)/周四(3)开放。",
                "脚本已硬编码：周六(5)若 deploy_meta.json 已登记 live_url，则主动推送差旅大屏卡片链接。",
                "非周二/周四会跳过 task_patrol_notify，但仍保留 alerts 产出与日志落库。",
            ],
        }
        _write_safety_report(safety_report, safety_payload)
        runtime_state["safety_report_written"] = True

        checkpoint.mark_completed(
            step="completed",
            progress={"phase": "completed", "mode": mode},
            payload=runtime_state,
            note=(
                "QA Patrol 每日管线完成：已执行任务巡检、催办分发与通知日志回写。"
                if notify_window_open
                else "QA Patrol 每日管线完成：已执行任务巡检与通知日志回写；今日非周二/周四，未触发群聊发信。"
            ),
        )
        return 0
    finally:
        sigterm_guard.uninstall()


if __name__ == "__main__":
    raise SystemExit(main())
