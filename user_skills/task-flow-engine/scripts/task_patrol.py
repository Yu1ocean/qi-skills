#!/usr/bin/env python3
"""每日对账巡查入口脚本。

读取【任务库】表格 → 计算 DDL 风险 → 输出“告警词典”（包含两阶段路由：私聊催办 vs 群聊公开提醒）。

变更（2026-05）：
- 取消“通过 --target-chat 实时查群成员/搜群”的逻辑（不再调用群聊搜索/拉群成员接口）。
- 改为从同一 Spreadsheet 内的【团队名单】Sheet 动态读取花名册：使用 `中文名称` → (Open ID / 邮箱) 做负责人映射。

输出为 JSON（便于上层：发送飞书消息 / 写入日志 / 入库）。
"""

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from task_flow_engine.chat_registry import (
    DEFAULT_BROADCAST_USAGE,
    default_broadcast_target_chat,
    get_chat_registry_entry,
)
from task_flow_engine.lark_sheets_cli import LarkSheetsCLI
from task_flow_engine.patrol import (
    OwnerIdentity,
    PatrolCardSnapshotStore,
    PatrolStateStore,
    TaskPatrol,
    _normalize_person_key,
    build_owner_directory_from_roster_rows,
)
from task_flow_engine.vacation import (
    FeishuVacationClient,
    apply_vacation_guard,
    is_legal_rest_day,
)


def _values_to_rows(values: List[List[Any]]) -> List[Dict[str, Any]]:
    if not values:
        return []

    header = values[0]
    # header 可能包含 None，这类列不参与映射
    header_keys: List[Optional[str]] = []
    for h in header:
        if h is None:
            header_keys.append(None)
        else:
            s = str(h).strip()
            header_keys.append(s or None)

    rows: List[Dict[str, Any]] = []
    for i, row in enumerate(values[1:], start=2):
        d: Dict[str, Any] = {"__row_number": i}
        for j, key in enumerate(header_keys):
            if not key:
                continue
            d[key] = row[j] if j < len(row) else None
        rows.append(d)
    return rows


def _repo_root() -> Path:
    # user_skills/task-flow-engine/scripts/task_patrol.py
    return Path(__file__).resolve().parents[1]


# -----------------------------
# L3 断言层：副作用前的输入校验（避免误写/误读/路径穿透）
# -----------------------------


def validate_sheet_title(title: str, *, arg_name: str) -> str:
    t = (title or "").strip()
    if not t:
        raise ValueError(f"{arg_name} 不能为空")
    return t


def validate_spreadsheet(value: str) -> str:
    v = (value or "").strip()
    if not v:
        raise ValueError("spreadsheet 不能为空")
    return v


def validate_safe_path_under_repo(path: Path, *, repo_root: Path, arg_name: str) -> Path:
    """限制本地写入路径必须在 repo_root 下（防止误写到工作区其他位置）。"""

    repo_root = repo_root.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        raise ValueError(f"{arg_name} 必须位于任务目录内：{resolved} (repo_root={repo_root})")
    return resolved


def _validate_target_chat_id(target_chat: str, *, registry_path: Optional[Path], usage: str) -> Dict[str, Any]:
    """把 CLI 传入的 chat_id 仅作为断言；真实 chat_id 必须来自 Chat Registry。"""

    entry = get_chat_registry_entry(usage=usage, path=registry_path)
    entry.assert_requested_chat_id(target_chat)
    return entry.to_target_chat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--spreadsheet",
        required=True,
        help="电子表格 URL 或 token（支持 wiki URL / sheets URL / spreadsheet_token）",
    )
    ap.add_argument("--task-sheet-title", default="任务库")
    ap.add_argument(
        "--roster-sheet-title",
        default="团队名单",
        help="花名册所在工作表标题（默认：团队名单）",
    )
    ap.add_argument("--due-soon-days", type=int, default=2, help="DDL 距离今天多少天算临近到期（包含 0）")
    ap.add_argument(
        "--today",
        default=None,
        help="可选：指定 today（YYYY-MM-DD），用于回放；不传则使用系统日期",
    )

    # 阶段二公开提醒：chat_id 只能来自 Chat Registry；--target-chat 仅作为兼容断言
    ap.add_argument(
        "--target-chat",
        default=None,
        help="兼容旧参数：仅用于断言传入值等于 Chat Registry 对应用途的 chat_id；不再作为 chat_id 来源。",
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

    ap.add_argument(
        "--group-card-max-items-per-group",
        type=int,
        default=3,
        help="广播卡片采用先人后事聚合时，每位负责人在每个类别下最多展开的任务数（默认 3）",
    )
    ap.add_argument(
        "--group-card-only-changed",
        action="store_true",
        help="仅在广播卡片中展示相对昨日新增/变化的异常（默认关闭，展示结构仍为先人后事）",
    )
    ap.add_argument(
        "--group-card-snapshot-file",
        default=".patrol_card_snapshot.json",
        help="广播卡片快照文件路径（相对路径默认相对于 task-flow-engine 根目录）",
    )

    # 新增：状态文件
    ap.add_argument(
        "--state-file",
        default=".patrol_state.json",
        help="本地状态缓存文件路径（相对路径默认相对于 task-flow-engine 根目录）",
    )
    ap.add_argument("--no-state", action="store_true", help="禁用状态缓存（不做连续天数升级）")
    ap.add_argument(
        "--disable-legal-holiday-guard",
        action="store_true",
        help="禁用法定休息日静默顺延（默认开启）",
    )
    ap.add_argument(
        "--disable-personal-leave-guard",
        action="store_true",
        help="禁用个人休假静默顺延（默认开启，fail-open）",
    )
    ap.add_argument(
        "--leave-check-min-busy-hours",
        type=float,
        default=4.0,
        help="freebusy 命中个人请假的最小忙碌时长阈值（小时，默认 4.0）",
    )

    args = ap.parse_args()

    repo_root = _repo_root()

    # L3：副作用前的输入校验
    args.spreadsheet = validate_spreadsheet(args.spreadsheet)
    args.task_sheet_title = validate_sheet_title(args.task_sheet_title, arg_name="task-sheet-title")
    args.roster_sheet_title = validate_sheet_title(args.roster_sheet_title, arg_name="roster-sheet-title")
    if args.due_soon_days < 0:
        raise ValueError("due-soon-days 不能为负数")
    if args.leave_check_min_busy_hours < 0:
        raise ValueError("leave-check-min-busy-hours 不能为负数")
    if args.group_card_max_items_per_group <= 0:
        raise ValueError("group-card-max-items-per-group 必须为正整数")

    # 状态文件路径（若启用 state，强制限制在 repo_root 下）
    registry_path: Optional[Path] = None
    if args.chat_registry:
        p_registry = Path(args.chat_registry)
        if not p_registry.is_absolute():
            p_registry = repo_root / p_registry
        registry_path = validate_safe_path_under_repo(p_registry, repo_root=repo_root, arg_name="chat-registry")

    state_path: Optional[Path] = None
    if not args.no_state:
        p = Path(args.state_file)
        if not p.is_absolute():
            p = repo_root / p
        state_path = validate_safe_path_under_repo(p, repo_root=repo_root, arg_name="state-file")

    snapshot_path = Path(args.group_card_snapshot_file)
    if not snapshot_path.is_absolute():
        snapshot_path = repo_root / snapshot_path
    snapshot_path = validate_safe_path_under_repo(snapshot_path, repo_root=repo_root, arg_name="group-card-snapshot-file")

    today = date.today()
    if args.today:
        today = date.fromisoformat(args.today)

    # 1) 解析表格 token
    cli = LarkSheetsCLI()
    spreadsheet_token = cli.resolve_spreadsheet_token(args.spreadsheet)

    # 2) 读取【任务库】
    task_sheet = cli.get_sheet_id(spreadsheet_token, args.task_sheet_title)
    task_values = cli.read_range(spreadsheet_token, task_sheet.sheet_id)
    task_rows = _values_to_rows(task_values)

    # 3) 读取【团队名单】并构建映射
    roster_sheet = cli.get_sheet_id(spreadsheet_token, args.roster_sheet_title)
    roster_values = cli.read_range(spreadsheet_token, roster_sheet.sheet_id)
    roster_rows = _values_to_rows(roster_values)
    owner_directory, roster_duplicates = build_owner_directory_from_roster_rows(roster_rows)

    def resolve_owner(raw: str) -> OwnerIdentity:
        k = _normalize_person_key(raw)
        hit = owner_directory.get(k)
        if hit is None:
            return OwnerIdentity(raw=raw, display_name=raw, source="sheet")
        return OwnerIdentity(
            raw=raw,
            display_name=hit.display_name,
            open_id=hit.open_id,
            email=hit.email,
            source=hit.source,
        )

    # 4) 广播群信息：从 Chat Registry 读取；旧 --target-chat 只做一致性断言
    target_chat = default_broadcast_target_chat(registry_path=registry_path, usage=args.broadcast_usage)
    if args.target_chat:
        target_chat = _validate_target_chat_id(
            args.target_chat,
            registry_path=registry_path,
            usage=args.broadcast_usage,
        )

    # 5) 状态缓存（连续异常天数）
    state: Optional[PatrolStateStore] = None
    if state_path is not None:
        state = PatrolStateStore(state_path)
        state.load()

    snapshot_store = PatrolCardSnapshotStore(snapshot_path)
    snapshot_store.load()

    # 6) 巡检
    patrol = TaskPatrol(
        due_soon_days=args.due_soon_days,
        owner_resolver=resolve_owner,
        group_card_max_items_per_group=args.group_card_max_items_per_group,
        group_card_only_changed=args.group_card_only_changed,
        group_card_previous_snapshot=snapshot_store.snapshot(),
    )
    output = patrol.run(task_rows, today=today, state=state, target_chat=target_chat)

    # 6.1) 休假免打扰与顺延拦截器（法定节假日 + 个人休假）
    holiday_hit = False if args.disable_legal_holiday_guard else is_legal_rest_day(today)
    if args.disable_personal_leave_guard:
        owner_on_leave_checker = None
    else:
        vacation_client = FeishuVacationClient()

        def owner_on_leave_checker(owner: OwnerIdentity) -> bool:
            return vacation_client.is_user_on_leave_by_freebusy(
                owner=owner,
                today=today,
                min_busy_hours=args.leave_check_min_busy_hours,
            )

    output = apply_vacation_guard(
        output,
        today=today,
        is_holiday=holiday_hit,
        owner_on_leave_checker=owner_on_leave_checker,
    )

    # 7) 写回 state
    if state is not None:
        state.save()
        output["state"] = {"path": str(state.path), "enabled": True}
    else:
        output["state"] = {"enabled": False}

    snapshot_store.save((output.get("card_state") or {}).get("snapshot", {}), today=today)
    output["card_state"] = {
        **(output.get("card_state") or {}),
        "path": str(snapshot_path),
        "target_chat": target_chat,
    }

    # 8) 补充来源信息，便于上层串联
    output["source"] = {
        "spreadsheet_token": spreadsheet_token,
        "task_sheet": {
            "title": task_sheet.title,
            "sheet_id": task_sheet.sheet_id,
            "total_rows_read": len(task_rows),
        },
        "roster_sheet": {
            "title": roster_sheet.title,
            "sheet_id": roster_sheet.sheet_id,
            "total_rows_read": len(roster_rows),
        },
    }
    output["directory"] = {
        "target_chat": target_chat,
        "mapped_members": len(owner_directory),
        "roster_duplicates": roster_duplicates,
    }

    try:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
