#!/usr/bin/env python3
"""
weekly-top3-patrol 真实数据巡检入口。

目标：
- 使用真实飞书表格数据做 Mode B 巡检
- 通过 CHAT_REGISTRY.json 获取 chat_id，并做群名关键字断言
- 调用真实 FreeBusy 计算 pending 用户与 yuqinan 的 contiguous 15-minute 建议插空
- dry-run 下仅落盘 payload 到 .ephemeral_pool，不真实发送/不真实写日历
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from chat_registry_loader import load_chat  # noqa: E402
from exemption_filter import assert_exemption_invariant, is_exempt  # noqa: E402
from interval_intersect import find_common_slot  # noqa: E402


CST = timezone(timedelta(hours=8))
YUQINAN_EMAIL = "yuqinan@bytedance.com"
YUQINAN_OPEN_ID = "ou_900ddd9ff611254a74ac32adafc016b4"
PLACEHOLDERS = {"", "tbd", "待填", "n/a", "—", "/", "待定"}
ROSTER_MIN_COUNT = int(os.environ.get("WEEKLY_TOP3_ROSTER_MIN_COUNT", "2"))
ROOT = Path(__file__).resolve().parents[3]
EPHEMERAL_DIR = ROOT / ".ephemeral_pool"
LOGS_DIR = ROOT / "user_skills" / "weekly-top3-patrol" / "logs"
LARK_SKILL_DIR = ROOT / "inner_skills" / "lark"
CALENDAR_SKILL_DIR = ROOT / "inner_skills" / "feishu-calendar"
CENTRAL_TRANSMITTER_DIR = ROOT / "user_skills" / "centralized-transmitter"
COMMON_TOOLSET_DIR = ROOT / "inner_skills" / "lark_common_toolset"

# 防呆铁律：非 dry-run 模式下，目标 bitable URL 必须严格等于以下生产源表 URL。
# 任何变体（不同 wiki token / 不同 sheet 参数）都会触发熔断，强制回退 dry-run。
PRODUCTION_BITABLE_URLS = [
    "https://bytedance.sg.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV?sheet=uJkm4f",
    "https://bytedance.sg.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV"
]


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout.strip()


def _extract_file_path(output: str) -> Path:
    m = re.search(r'file_path:\s*"([^"]+)"', output)
    if not m:
        raise RuntimeError(f"无法从下载输出解析 file_path:\n{output}")
    return Path(m.group(1))


def _parse_json_from_mixed_output(output: str) -> Any:
    output = output.strip()
    if not output:
        raise RuntimeError("命令未返回任何输出，无法解析 JSON")
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        pass

    m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])\s*$", output)
    if not m:
        raise RuntimeError(f"无法从混合输出中提取 JSON:\n{output}")
    return json.loads(m.group(1))


def _normalize_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    s = str(v).replace("\xa0", " ").strip()
    return s


def _normalize_name(raw: str) -> str:
    s = _normalize_text(raw)
    s = s.replace("@", "")
    s = s.replace("、", " ")
    return s.strip()


def _is_empty_plan(v: Any) -> bool:
    s = _normalize_text(v)
    if not s:
        return True
    return s.lower() in PLACEHOLDERS


def _next_quarter(dt: datetime) -> datetime:
    minute = ((dt.minute // 15) + 1) * 15
    if minute >= 60:
        return dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return dt.replace(minute=minute, second=0, microsecond=0)


def download_sheet(url: str) -> Path:
    output = _run([
        "python3",
        str(LARK_SKILL_DIR / "mcp_lark_lark_download.py"),
        json.dumps({"document_url": url}, ensure_ascii=False),
    ])
    return _extract_file_path(output)


def load_roster_from_chat_registry() -> dict[str, dict[str, str]]:
    """当源表不再内嵌「团队名单」sheet 时，回退到群成员通讯录构建 roster。"""
    chat = load_chat("task_patrol_broadcast")
    output = _run([
        "python3",
        str(COMMON_TOOLSET_DIR / "lark_user_info.py"),
        json.dumps({"chat_id": chat["chat_id"]}, ensure_ascii=False),
    ])
    m = re.search(r"users:\s*(\[.*\])", output, re.S)
    if not m:
        raise RuntimeError(f"无法从 lark_user_info 输出解析 users 列表:\n{output}")
    users = json.loads(m.group(1))

    roster: dict[str, dict[str, str]] = {}
    for user in users:
        zh_name = _normalize_name(user.get("zh_name"))
        if not zh_name:
            continue
        roster[zh_name] = {
            "name": zh_name,
            "email": _normalize_text(user.get("email")),
            "open_id": _normalize_text(user.get("open_id")),
        }
    return roster


class RosterEmptyError(RuntimeError):
    def __init__(self, message: str, raw_evidence: dict[str, Any]):
        super().__init__(message)
        self.status = "ERROR_ROSTER_EMPTY"
        self.raw_evidence = raw_evidence


def _normalize_roster_columns(df: pd.DataFrame) -> pd.DataFrame:
    """兼容团队名单列名：姓名 -> 中文名称，open_id -> Open ID。"""
    column_aliases = {
        "姓名": "中文名称",
        "open_id": "Open ID",
    }
    rename_map = {
        col: column_aliases[_normalize_text(col)]
        for col in df.columns
        if _normalize_text(col) in column_aliases
    }
    return df.rename(columns=rename_map)


def load_team_roster(xlsx_path: Path) -> dict[str, dict[str, str]]:
    xls = pd.ExcelFile(xlsx_path)
    if "团队名单" not in xls.sheet_names:
        return load_roster_from_chat_registry()

    df = pd.read_excel(xlsx_path, sheet_name="团队名单")
    df = _normalize_roster_columns(df)
    roster = {}
    for _, row in df.iterrows():
        name = _normalize_name(row.get("中文名称"))
        email = _normalize_text(row.get("邮箱"))
        open_id = _normalize_text(row.get("Open ID"))
        if not name:
            continue
        roster[name] = {"name": name, "email": email, "open_id": open_id}
    return roster


def _current_week_date_tokens(now: datetime) -> list[str]:
    week_start = now.date() - timedelta(days=now.weekday())
    tokens: list[str] = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        tokens.extend([
            f"{day.month}/{day.day}",
            f"{day.month:02d}/{day.day:02d}",
            f"{day.month}.{day.day}",
            f"{day.month:02d}.{day.day:02d}",
            f"{day.month}月{day.day}",
            f"{day.month}月{day.day}号",
        ])
    return list(dict.fromkeys(tokens))



def extract_pending_users(xlsx_path: Path, now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    df = pd.read_excel(xlsx_path, sheet_name="重要三件事")
    df["周日期"] = df["周日期"].ffill()
    df["负责人"] = df["负责人"].ffill()
    df["序号"] = df["序号"].ffill()

    week_num = now.isocalendar().week
    week_marker = f"Week {week_num}"
    week_series = df["周日期"].astype(str)
    week_df = df[week_series.str.contains(week_marker, na=False)].copy()
    resolved_week_marker = week_marker
    if week_df.empty:
        token_pattern = "|".join(re.escape(token) for token in _current_week_date_tokens(now))
        if token_pattern:
            week_df = df[week_series.str.contains(token_pattern, na=False, regex=True)].copy()
        if week_df.empty:
            raise RuntimeError(f"真实表中未找到当前周数据：{week_marker}")
        resolved_week_marker = f"{week_marker} (fallback_by_date_token)"

    roster = load_team_roster(xlsx_path)
    roster_count = len(roster)
    owner_blocks_count = int(week_df["负责人"].map(_normalize_name).replace("", pd.NA).dropna().nunique())
    fallback_reason = "fallback_by_date_token" if "fallback_by_date_token" in resolved_week_marker else None
    if roster_count < ROSTER_MIN_COUNT:
        raw_evidence = {
            "roster_count": roster_count,
            "owner_blocks_count": owner_blocks_count,
            "complete_users": [],
            "absent_users": [],
            "week_marker": resolved_week_marker,
            "fallback_reason": fallback_reason,
        }
        try:
            _append_error_log(
                f"{now.isocalendar().year}-W{now.isocalendar().week:02d}",
                "ERROR_ROSTER_EMPTY",
                raw_evidence,
                f"团队名单人数低于阈值：{roster_count} < {ROSTER_MIN_COUNT}",
            )
        except Exception:
            pass
        raise RosterEmptyError(
            f"ERROR_ROSTER_EMPTY: 团队名单人数低于阈值：{roster_count} < {ROSTER_MIN_COUNT}",
            raw_evidence,
        )

    owner_blocks: dict[str, list[dict[str, Any]]] = {}
    owner_order: list[str] = []

    for _, row in week_df.iterrows():
        owner = _normalize_name(row.get("负责人"))
        if not owner:
            continue
        if owner not in owner_blocks:
            owner_blocks[owner] = []
            owner_order.append(owner)
        owner_blocks[owner].append({
            "seq": _normalize_text(row.get("序号")),
            "tag": _normalize_text(row.get("标签")),
            "plan": _normalize_text(row.get("计划")),
            "progress": _normalize_text(row.get("完成进度")),
            "remark": _normalize_text(row.get("Remark")),
        })

    pending: list[dict[str, Any]] = []
    debug_owner_blocks: list[dict[str, Any]] = []
    exempted_hits: list[dict[str, Any]] = []
    seen_pending_emails: set[str] = set()

    for owner in owner_order:
        rows = owner_blocks[owner]
        top3_rows = []
        for r in rows:
            seq = r["seq"]
            if seq == "业绩":
                continue
            if not (r["tag"] or r["plan"] or r["progress"] or r["remark"] or seq):
                continue
            top3_rows.append(r)
            if len(top3_rows) == 3:
                break

        identity = roster.get(owner, {"name": owner, "email": "", "open_id": ""})
        block_debug = {
            "owner": owner,
            "email": identity.get("email", ""),
            "open_id": identity.get("open_id", ""),
            "top3_rows": top3_rows,
        }

        if is_exempt(identity.get("email")):
            exempted_hits.append({
                "name": owner,
                "email": identity.get("email", ""),
                "reason": "hard-coded exemption",
            })
            debug_owner_blocks.append({**block_debug, "status": "exempt_filtered"})
            continue

        missing_rows = []
        for idx, r in enumerate(top3_rows, start=1):
            if _is_empty_plan(r["plan"]):
                missing_rows.append({"slot": idx, **r})

        if len(top3_rows) < 3:
            missing_rows.append({"slot": len(top3_rows) + 1, "reason": "top3 rows < 3"})

        status = "complete"
        if missing_rows:
            status = "pending"
            pending.append({
                "name": owner,
                "email": identity.get("email", ""),
                "open_id": identity.get("open_id", ""),
                "missing_rows": missing_rows,
                "top3_rows": top3_rows,
            })
            email = identity.get("email", "")
            if email:
                seen_pending_emails.add(email)

        debug_owner_blocks.append({**block_debug, "status": status})

    for owner, identity in roster.items():
        if owner in owner_blocks:
            continue

        email = identity.get("email", "")
        block_debug = {
            "owner": owner,
            "email": email,
            "open_id": identity.get("open_id", ""),
            "top3_rows": [],
        }

        if is_exempt(email):
            exempted_hits.append({
                "name": owner,
                "email": email,
                "reason": "hard-coded exemption (absent from current week sheet)",
            })
            debug_owner_blocks.append({**block_debug, "status": "exempt_filtered_absent"})
            continue

        missing_rows = [{"slot": 1, "reason": "owner absent from current week sheet"}]
        if email not in seen_pending_emails:
            pending.append({
                "name": owner,
                "email": email,
                "open_id": identity.get("open_id", ""),
                "missing_rows": missing_rows,
                "top3_rows": [],
            })
            if email:
                seen_pending_emails.add(email)
        debug_owner_blocks.append({**block_debug, "status": "pending_absent_from_sheet"})

    focus_user = roster.get("焦彦晨", {"name": "焦彦晨", "email": "jiaoyanchen@bytedance.com", "open_id": ""})
    safety_filter = {
        "name": focus_user["name"],
        "email": focus_user["email"],
        "open_id": focus_user.get("open_id", ""),
        "is_exempt": is_exempt(focus_user.get("email")),
        "present_in_team_roster": "焦彦晨" in roster,
        "appears_in_pending_after_filter": any(u["email"] == focus_user.get("email") for u in pending),
        "safely_filtered": is_exempt(focus_user.get("email")) and not any(
            u["email"] == focus_user.get("email") for u in pending
        ),
    }

    complete_users = [
        {
            "name": item.get("owner", ""),
            "email": item.get("email", ""),
        }
        for item in debug_owner_blocks
        if item.get("status") == "complete"
    ]
    absent_users = [
        {
            "name": item.get("owner", ""),
            "email": item.get("email", ""),
        }
        for item in debug_owner_blocks
        if item.get("status") == "pending_absent_from_sheet"
    ]
    raw_evidence = {
        "roster_count": roster_count,
        "owner_blocks_count": owner_blocks_count,
        "complete_users": complete_users,
        "absent_users": absent_users,
        "week_marker": resolved_week_marker,
        "fallback_reason": fallback_reason,
    }

    return pending, {
        "week_marker": resolved_week_marker,
        "owner_blocks": debug_owner_blocks,
        "exempted_hits": exempted_hits,
        "safety_filter": safety_filter,
        "raw_evidence": raw_evidence,
    }


def fetch_freebusy(user_ids: list[str], time_min: str, time_max: str) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for user_id in user_ids:
        output = _run([
            "lark-cli",
            "calendar",
            "+freebusy",
            "--user-id",
            user_id,
            "--start",
            time_min,
            "--end",
            time_max,
            "--json",
        ])
        data = _parse_json_from_mixed_output(output)
        result[user_id] = data.get("data", []) or []
    return result


def create_calendar_event(event_plan: dict[str, Any]) -> dict[str, Any]:
    """真实调用 feishu_calendar_event.js 创建日程。

    返回 SDK 响应中的 data 字段（含 event_id / event 等）。
    任何调用失败都会向上抛出 RuntimeError，由调用方决定是否兜底。
    """
    payload = {
        "action": "create",
        "summary": event_plan["summary"],
        "description": event_plan.get("description", ""),
        "start_time": event_plan["start_time"],
        "end_time": event_plan["end_time"],
        "user_open_id": YUQINAN_OPEN_ID,
        "attendees": event_plan.get("attendees", []),
    }
    output = _run([
        "node",
        str(CALENDAR_SKILL_DIR / "scripts" / "feishu_calendar_event.js"),
        "--input",
        json.dumps(payload, ensure_ascii=False),
    ])
    try:
        data = json.loads(output)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"日程创建返回非 JSON：{output}") from e
    return data


def _extract_event_link(event_result: dict[str, Any]) -> str:
    event = event_result.get("event") or {}
    for key in ("app_link", "web_link", "open_link", "event_link"):
        value = event.get(key) or event_result.get(key)
        if value:
            return str(value)
    return ""


def _format_slot_link(slot: dict[str, str], event_link: str, now: datetime) -> str:
    start_dt = datetime.fromisoformat(slot["start_time"])
    end_dt = datetime.fromisoformat(slot["end_time"])
    day_label = "今晚" if start_dt.date() == now.date() else start_dt.strftime("%m-%d")
    label = f"{day_label} {start_dt.strftime('%H:%M')} ~ {end_dt.strftime('%H:%M')}（点击直达会议日程）"
    if event_link:
        safe_link = event_link.replace("(", "%28").replace(")", "%29")
        return f"[{label}]({safe_link})"
    return f"{day_label} {start_dt.strftime('%H:%M')} ~ {end_dt.strftime('%H:%M')}（待补链）"


def _format_pending_line(user: dict[str, Any]) -> str:
    items = []
    for mr in user.get("missing_rows", []):
        slot = mr.get("slot")
        if slot:
            items.append(f"Top{slot}：重要三件事暂空")
        else:
            items.append("重要三件事暂空")
    desc = "；".join(items) if items else "重要三件事暂空"
    return f"- {user['name']}：{desc}"


def _format_pending_user_mention(user: dict[str, Any]) -> str:
    open_id = _normalize_text(user.get("open_id"))
    name = _normalize_text(user.get("name")) or "同学"
    if open_id:
        return f'<at id="{open_id}">{name}</at>'
    return name


def build_mode_a_card(plan: dict[str, Any]) -> dict[str, Any]:
    """构造 Mode A 软性催办卡片（schema 2.0）。"""
    week = plan["week"]
    pending = plan["pending_users"]
    count = len(pending)
    mention_line = " ".join(_format_pending_user_mention(user) for user in pending)
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"{week} 待补齐：{count} 人",
            },
        }
    ]

    if mention_line:
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": mention_line,
            },
        })

    elements.extend([
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "请于今晚 23:59 前补齐本周重要三件事。",
            },
        },
        {
            "tag": "markdown",
            "content": f"[{plan['workspace_link_text']}]({plan['workspace_url']})",
            "text_size": "normal_v2",
        },
    ])

    return {
        "name": "WeeklyTop3PatrolCard",
        "dsl": {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": "重要三件事"},
                "template": "yellow",
            },
            "body": {"elements": elements},
        },
    }


def build_l0_card(plan: dict[str, Any]) -> dict[str, Any]:
    """构造 L0 催办卡片（schema 2.0）。"""
    week = plan["week"]
    pending = plan["pending_users"]
    scheduled = plan["scheduled"]
    unresolvable = plan.get("unresolvable", [])
    now = datetime.now(CST)
    elements: list[dict[str, Any]] = []

    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"{week} 待补齐：{len(pending)} 人",
        },
    })

    if pending:
        pending_lines = [_format_pending_line(u) for u in pending]
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "\n".join(pending_lines),
            },
        })

    if scheduled:
        slot_lines = []
        for s in scheduled:
            event_link = _extract_event_link(s.get("event_result", {}) or {})
            user_name = _normalize_text((s.get("user") or {}).get("name")) or "待同步同学"
            slot_lines.append(f"- {user_name}：{_format_slot_link(s['reserved_slot'], event_link, now)}")
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "\n".join(slot_lines),
            },
        })

    if unresolvable:
        lines = [f"- {u['user']['name']}：{u['reason']}" for u in unresolvable]
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "\n".join(lines),
            },
        })

    return {
        "name": "WeeklyTop3PatrolCard",
        "dsl": {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": "重要三件事"},
                "template": "blue",
            },
            "body": {"elements": elements},
        },
    }


def send_l0_card_to_chat(card: dict[str, Any], chat_id: str, run_id: str, mode: str) -> dict[str, Any]:
    """通过 centralized-transmitter 统一发射 L0 卡片到目标群。"""
    EPHEMERAL_DIR.mkdir(parents=True, exist_ok=True)
    card_path = EPHEMERAL_DIR / f"[{run_id}]_weekly_top3_patrol_mode{mode}.card.json"
    card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")

    topic = "重要三件事"
    create_out = _run([
        "python3",
        str(CENTRAL_TRANSMITTER_DIR / "scripts" / "centralized_transmitter.py"),
        "create_card",
        str(card_path),
        f"--task-id={run_id}",
        f"--topic={topic}",
        "--caller-role=comm-agent",
    ])
    card_id: str | None = None
    m = re.search(r'"card_id"\s*:\s*"?(\d+)"?', create_out)
    if m:
        card_id = m.group(1)
    if not card_id:
        m = re.search(r"'card_id'\s*:\s*'?(\d+)'?", create_out)
        if m:
            card_id = m.group(1)
    if not card_id:
        raise RuntimeError(f"create_card 输出未包含 card_id：\n{create_out}")

    send_out = _run([
        "python3",
        str(CENTRAL_TRANSMITTER_DIR / "scripts" / "centralized_transmitter.py"),
        "send",
        chat_id,
        "interactive",
        card_id,
        "--id-type=chat_id",
        f"--task-id={run_id}",
        f"--topic={topic}",
        "--caller-role=comm-agent",
    ])
    return {
        "card_id": card_id,
        "card_path": str(card_path),
        "create_output": create_out,
        "send_output": send_out,
    }


def build_post_payload(plan: dict[str, Any]) -> dict[str, Any]:
    lines = [_format_pending_line(item) for item in plan["pending_users"]]

    slot_lines = []
    for s in plan["scheduled"]:
        slot = s["reserved_slot"]
        start_dt = datetime.fromisoformat(slot["start_time"])
        end_dt = datetime.fromisoformat(slot["end_time"])
        day_label = "今晚" if start_dt.date() == datetime.now(CST).date() else start_dt.strftime("%m-%d")
        slot_lines.append(f"- {day_label} {start_dt.strftime('%H:%M')} ~ {end_dt.strftime('%H:%M')}（点击直达会议日程）")

    content = [
        [{"tag": "text", "text": "重要三件事"}],
        [{"tag": "text", "text": f"{plan['week']} 待补齐：{len(plan['pending_users'])} 人"}],
    ]
    if lines:
        content.append([{"tag": "text", "text": "\n".join(lines)}])
    if slot_lines:
        content.append([{"tag": "text", "text": "\n".join(slot_lines)}])
    return {"zh_cn": {"title": "", "content": content}}


def _week_log_path(week: str) -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR / f"patrol_{week.replace('-', '_')}.json"


def _load_week_log(week: str) -> dict[str, Any]:
    path = _week_log_path(week)
    if not path.exists():
        return {"week": week, "mode_a_runs": [], "mode_b_bookings": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"幂等锁日志损坏：{path}") from exc


def _write_week_log(week: str, payload: dict[str, Any]) -> str:
    path = _week_log_path(week)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _append_error_log(week: str, status: str, raw_evidence: dict[str, Any], error: str) -> str:
    week_log = _load_week_log(week)
    week_log.setdefault("error_runs", []).append({
        "timestamp": datetime.now(CST).isoformat(),
        "status": status,
        "error": error,
        "raw_evidence": raw_evidence,
    })
    return _write_week_log(week, week_log)


def _already_booked_this_week(week_log: dict[str, Any], user: dict[str, Any]) -> dict[str, Any] | None:
    user_email = _normalize_text(user.get("email")).lower()
    user_name = _normalize_text(user.get("name"))
    for record in week_log.get("mode_b_bookings", []):
        record_email = _normalize_text(record.get("email")).lower()
        record_name = _normalize_text(record.get("name"))
        if user_email and record_email and user_email == record_email:
            return record
        if user_name and record_name and user_name == record_name:
            return record
    return None


def _append_mode_a_log(week: str, run_id: str, pending_users: list[dict[str, Any]]) -> str:
    week_log = _load_week_log(week)
    week_log.setdefault("mode_a_runs", []).append({
        "run_id": run_id,
        "timestamp": datetime.now(CST).isoformat(),
        "pending_users": [
            {"name": item.get("name", ""), "email": item.get("email", "")}
            for item in pending_users
        ],
    })
    return _write_week_log(week, week_log)


def _append_mode_b_booking_log(
    week: str,
    run_id: str,
    booked_items: list[dict[str, Any]],
    unresolvable: list[dict[str, Any]],
) -> str:
    week_log = _load_week_log(week)
    existing = week_log.setdefault("mode_b_bookings", [])
    for item in booked_items:
        existing.append({
            "run_id": run_id,
            "timestamp": datetime.now(CST).isoformat(),
            "name": item["user"].get("name", ""),
            "email": item["user"].get("email", ""),
            "event_id": item.get("event_id", ""),
            "start_time": item["reserved_slot"].get("start_time", ""),
            "end_time": item["reserved_slot"].get("end_time", ""),
        })
    week_log["last_unresolvable"] = [
        {
            "name": item["user"].get("name", ""),
            "email": item["user"].get("email", ""),
            "reason": item.get("reason", ""),
        }
        for item in unresolvable
    ]
    return _write_week_log(week, week_log)


def _require_real_send_confirmation(confirm_real_send: bool, mode: str) -> None:
    if confirm_real_send:
        return
    raise RuntimeError(
        f"[SAFETY] Mode {mode} 涉及真实群发/日历写入，必须显式追加 --confirm-real-send 才允许执行。"
    )


def run_mode_a(url: str, dry_run: bool, confirm_real_send: bool = False) -> dict[str, Any]:
    # 防爆破铁律：非 dry-run 模式必须严格校验生产源 URL，任何变体一律熔断。
    if not dry_run:
        if url.strip() not in PRODUCTION_BITABLE_URLS:
            raise RuntimeError(
                "[SAFETY] 非 dry-run 模式必须使用受信任的生产源表 URL。\n"
                f"  expected one of: {PRODUCTION_BITABLE_URLS}\n"
                f"  received: {url}\n"
                "若需扩展白名单，请同步更新 PRODUCTION_BITABLE_URLS 常量并提交 review。"
            )

    assert_exemption_invariant()
    now = datetime.now(CST)
    chat = load_chat("task_patrol_broadcast")
    xlsx_path = download_sheet(url)
    pending_users, meta = extract_pending_users(xlsx_path, now)

    week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    run_id = f"weekly-top3-patrol-{week}-{now.strftime('%Y%m%dT%H%M%S%z')}"
    workspace_url = url
    workspace_link_text = "点击前往工作站填写"

    plan = {
        "mode": "A",
        "dry_run": dry_run,
        "data_source": {
            "requested_url": url,
            "resolved_local_file": str(xlsx_path),
            "resolved_type": "lark_sheet",
            "note": "传入链接经真实下载后解析为飞书 Sheets；本次按真实源表巡检。",
        },
        "week": week,
        "run_id": run_id,
        "workspace_url": workspace_url,
        "workspace_link_text": workspace_link_text,
        "chat": {
            "chat_key": "task_patrol_broadcast",
            "chat_id": chat["chat_id"],
            "chat_name": chat["name"],
            "group_name_assertion": "passed",
            "expected_keywords": chat.get("expected_name_keywords", []),
        },
        "pending_users": pending_users,
        "pending_count": len(pending_users),
        "safety_filter": meta["safety_filter"],
        "debug": {
            "week_marker": meta["week_marker"],
            "owner_blocks": meta["owner_blocks"],
            "exempted_hits": meta["exempted_hits"],
            "raw_evidence": meta["raw_evidence"],
        },
        "route": "L0_FLAT (planned only; not sent in dry-run)" if dry_run else "L0_FLAT (real send)",
    }

    EPHEMERAL_DIR.mkdir(parents=True, exist_ok=True)
    card = build_mode_a_card(plan)
    card_path = EPHEMERAL_DIR / f"[{run_id}]_weekly_top3_patrol_modeA.card.json"
    card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    plan["ephemeral_payload_path"] = str(card_path)
    plan["card_preview"] = card

    if dry_run:
        plan["log_path"] = _week_log_path(week).as_posix()
        return plan

    _require_real_send_confirmation(confirm_real_send, "A")
    plan["log_path"] = _append_mode_a_log(week, run_id, pending_users)
    try:
        send_result = send_l0_card_to_chat(card, chat["chat_id"], run_id, "A")
        plan["send_result"] = {
            "status": "ok",
            "chat_id": chat["chat_id"],
            "chat_name": chat["name"],
            **send_result,
        }
    except Exception as e:
        plan["send_result"] = {
            "status": "failed",
            "chat_id": chat["chat_id"],
            "error": str(e),
        }

    return plan


def run_mode_b(url: str, dry_run: bool, confirm_real_send: bool = False) -> dict[str, Any]:
    # 防爆破铁律：非 dry-run 模式必须严格校验生产源 URL，任何变体一律熔断。
    if not dry_run:
        if url.strip() not in PRODUCTION_BITABLE_URLS:
            raise RuntimeError(
                "[SAFETY] 非 dry-run 模式必须使用受信任的生产源表 URL。\n"
                f"  expected one of: {PRODUCTION_BITABLE_URLS}\n"
                f"  received: {url}\n"
                "若需扩展白名单，请同步更新 PRODUCTION_BITABLE_URLS 常量并提交 review。"
            )

    assert_exemption_invariant()
    now = datetime.now(CST)
    chat = load_chat("task_patrol_broadcast")
    xlsx_path = download_sheet(url)
    pending_users, meta = extract_pending_users(xlsx_path, now)

    window_start = max(now, now.replace(hour=16, minute=0, second=0, microsecond=0))
    window_start = _next_quarter(window_start)
    window_end = now.replace(hour=22, minute=0, second=0, microsecond=0)
    if window_start >= window_end:
        raise RuntimeError("当前已超过 Mode B 工作窗口（22:00），无法做今日插空预演。")

    week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    run_id = f"weekly-top3-patrol-{week}-{now.strftime('%Y%m%dT%H%M%S%z')}"
    week_log = _load_week_log(week)

    scheduled = []
    unresolvable = []
    reserved_slots: list[tuple[datetime, datetime]] = []

    for user in pending_users:
        existing_booking = _already_booked_this_week(week_log, user)
        if existing_booking:
            unresolvable.append({
                "user": user,
                "reason": "weekly idempotency lock: already booked this ISO week",
                "existing_booking": existing_booking,
            })
            continue
        if not user.get("open_id"):
            unresolvable.append({"user": user, "reason": "missing open_id in 团队名单"})
            continue
        freebusy_map = fetch_freebusy(
            [user["open_id"], YUQINAN_OPEN_ID],
            window_start.isoformat(),
            window_end.isoformat(),
        )
        busy_user = freebusy_map.get(user["open_id"], [])
        busy_yuqinan = freebusy_map.get(YUQINAN_OPEN_ID, [])
        effective_busy_yuqinan = list(busy_yuqinan) + [
            {"start_time": s.isoformat(), "end_time": e.isoformat()} for s, e in reserved_slots
        ]
        slot = find_common_slot(
            busy_user,
            effective_busy_yuqinan,
            window_start,
            window_end,
            15,
        )
        if slot is None:
            unresolvable.append({
                "user": user,
                "reason": "工作窗口内无 contiguous 15min 共同空闲",
                "freebusy_preview": {
                    "user_busy": busy_user,
                    "yuqinan_busy": busy_yuqinan,
                },
            })
            continue

        reserved_slots.append(slot)
        scheduled.append({
            "user": user,
            "reserved_slot": {
                "start_time": slot[0].isoformat(),
                "end_time": slot[1].isoformat(),
            },
            "event_plan": {
                "summary": f"[重要三件事同步] {user['name']} × yuqinan",
                "start_time": slot[0].isoformat(),
                "end_time": slot[1].isoformat(),
                "attendees": [
                    {"type": "user", "id": user["open_id"]},
                    {"type": "user", "id": YUQINAN_OPEN_ID},
                ],
                "description": (
                    f"自动化强插 1on1：本周（{week}）Top3 未填写。\n"
                    f"Sheet: {url}\n"
                    f"Trigger: weekly-top3-patrol Mode B\n"
                    f"Run ID: {run_id}"
                ),
            },
            "freebusy_preview": {
                "user_busy": busy_user,
                "yuqinan_busy": busy_yuqinan,
            },
        })

    plan = {
        "mode": "B",
        "dry_run": dry_run,
        "data_source": {
            "requested_url": url,
            "resolved_local_file": str(xlsx_path),
            "resolved_type": "lark_sheet",
            "note": "传入链接经真实下载后解析为飞书 Sheets；本次按真实源表巡检。",
        },
        "week": week,
        "run_id": run_id,
        "chat": {
            "chat_key": "task_patrol_broadcast",
            "chat_id": chat["chat_id"],
            "chat_name": chat["name"],
            "group_name_assertion": "passed",
            "expected_keywords": chat.get("expected_name_keywords", []),
        },
        "window": {
            "start_time": window_start.isoformat(),
            "end_time": window_end.isoformat(),
            "slot_minutes": 15,
        },
        "pending_users": pending_users,
        "pending_count": len(pending_users),
        "scheduled": scheduled,
        "scheduled_count": len(scheduled),
        "unresolvable": unresolvable,
        "safety_filter": meta["safety_filter"],
        "debug": {
            "week_marker": meta["week_marker"],
            "owner_blocks": meta["owner_blocks"],
            "exempted_hits": meta["exempted_hits"],
            "raw_evidence": meta["raw_evidence"],
        },
        "route": "L0_FLAT (planned only; not sent in dry-run)" if dry_run else "L0_FLAT (real send)",
    }

    EPHEMERAL_DIR.mkdir(parents=True, exist_ok=True)
    payload_path = EPHEMERAL_DIR / f"[{run_id}]_weekly_top3_patrol_modeB.post.json"
    payload = build_post_payload(plan)
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    plan["ephemeral_payload_path"] = str(payload_path)
    plan["log_path"] = _week_log_path(week).as_posix()

    if dry_run:
        return plan

    _require_real_send_confirmation(confirm_real_send, "B")

    # 真实下发分支：创建日历 + 发送 L0 卡片到目标群
    # 1) 真实创建日程
    calendar_results: list[dict[str, Any]] = []
    booked_items: list[dict[str, Any]] = []
    for s in scheduled:
        try:
            event_data = create_calendar_event(s["event_plan"])
            s["event_result"] = event_data
            event_id = event_data.get("event_id") or (event_data.get("event") or {}).get("event_id") or ""
            booked_items.append({
                "user": s["user"],
                "reserved_slot": s["reserved_slot"],
                "event_id": event_id,
            })
            calendar_results.append({
                "user": s["user"]["name"],
                "status": "ok",
                "event_id": event_id,
                "calendar_id": event_data.get("calendar_id"),
                "slot": s["reserved_slot"],
            })
        except Exception as e:
            s["event_result"] = {"error": str(e)}
            unresolvable.append({
                "user": s["user"],
                "reason": f"calendar create failed: {e}",
                "reserved_slot": s["reserved_slot"],
            })
            calendar_results.append({
                "user": s["user"]["name"],
                "status": "failed",
                "error": str(e),
                "slot": s["reserved_slot"],
            })
    plan["calendar_results"] = calendar_results
    plan["log_path"] = _append_mode_b_booking_log(week, run_id, booked_items, unresolvable)

    # 2) 真实发送 L0 卡片
    card = build_l0_card(plan)
    try:
        send_result = send_l0_card_to_chat(card, chat["chat_id"], run_id, "B")
        plan["send_result"] = {
            "status": "ok",
            "chat_id": chat["chat_id"],
            "chat_name": chat["name"],
            **send_result,
        }
    except Exception as e:
        plan["send_result"] = {
            "status": "failed",
            "chat_id": chat["chat_id"],
            "error": str(e),
        }

    return plan


def send_private_diagnostic(admin_email: str, *, run_id: str, stage: str, exc: Exception) -> dict[str, Any] | None:
    if not admin_email:
        return None
    EPHEMERAL_DIR.mkdir(parents=True, exist_ok=True)
    payload_path = EPHEMERAL_DIR / f"[{run_id}]_weekly_top3_patrol_error_boundary.post.json"
    trace_text = traceback.format_exc()
    payload = {
        "task_id": run_id,
        "title": "weekly-top3-patrol 诊断",
        "zh_cn": {
            "title": "weekly-top3-patrol 诊断",
            "content": [
                [{"tag": "text", "text": "⚠️ weekly-top3-patrol 执行异常（已走私聊兜底）"}],
                [{"tag": "text", "text": f"阶段：{stage}"}],
                [{"tag": "text", "text": f"Run ID：{run_id}"}],
                [{"tag": "text", "text": f"错误摘要：{exc}"}],
                [{"tag": "text", "text": f"Traceback：\n{trace_text}"}],
            ],
        },
    }
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    send_out = _run([
        "python3",
        str(CENTRAL_TRANSMITTER_DIR / "scripts" / "centralized_transmitter.py"),
        "send",
        admin_email,
        "post",
        str(payload_path),
        "--id-type=email",
        f"--task-id={run_id}",
        "--topic=weekly-top3-patrol 诊断",
        "--caller-role=main",
    ])
    return {
        "admin_email": admin_email,
        "payload_path": str(payload_path),
        "send_output": send_out,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Weekly Top3 Patrol (real-data dry-run)")
    parser.add_argument("--mode", choices=["A", "B"], required=True)
    parser.add_argument("--bitable", required=True, help="Wiki/Sheet/Bitable URL")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--confirm-real-send",
        action="store_true",
        help="确认执行真实群发/日历写入；未显式传入时仅允许 dry-run",
    )
    args = parser.parse_args()

    run_id = f"weekly-top3-patrol-error-{datetime.now(CST).strftime('%Y%m%dT%H%M%S%z')}"
    try:
        if args.mode == "A":
            plan = run_mode_a(args.bitable, args.dry_run, args.confirm_real_send)
        else:
            plan = run_mode_b(args.bitable, args.dry_run, args.confirm_real_send)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    except RosterEmptyError as exc:
        safe_summary = {
            "status": exc.status,
            "error_boundary_routing": "blocked_before_card_send",
            "run_id": run_id,
            "error": str(exc),
            "raw_evidence": exc.raw_evidence,
        }
        print(json.dumps(safe_summary, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    except Exception as exc:
        admin_email = ""
        try:
            admin_email = load_chat("task_patrol_broadcast").get("admin_email", "")
        except Exception:
            admin_email = ""

        diagnostic_result = None
        if admin_email:
            try:
                diagnostic_result = send_private_diagnostic(
                    admin_email,
                    run_id=run_id,
                    stage=f"mode={args.mode}",
                    exc=exc,
                )
            except Exception:
                diagnostic_result = None

        safe_summary = {
            "status": "failed",
            "error_boundary_routing": "private_dm" if diagnostic_result else "unavailable",
            "admin_email": admin_email or None,
            "run_id": run_id,
            "error": str(exc),
        }
        print(json.dumps(safe_summary, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
