#!/usr/bin/env python3
"""时间段推荐与抢占候选计算脚本。

本脚本提供两层能力：

1. `suggest_timeslots`：
   - 兼容旧版逻辑，仅基于忙碌区间计算冲突最少的若干候选时段。
   - 适用于 Stage 2 兜底策略中，给出若干"冲突最少"的推荐。

2. `classify_timeslots`：
   - 新增的抢占模式支持能力，用于在给定候选时间窗口内：
     - 先识别**绝对空闲**时段（所有人无任何冲突）；
     - 若无绝对空闲，再识别仅与 Tentative/未接受日程冲突、且满足
       `preemption_sensitivity` 约束的**可抢占候选时段**。
   - 返回结构化结果，方便在上层生成候选列表、冲突权重以及用户话术。

所有时间均使用 `datetime.datetime` 对象表示。
"""

import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Iterable, List, Tuple, Optional, Any


def format_slot_range(
    start_dt: datetime.datetime,
    end_dt: datetime.datetime,
    *,
    tz_name: Optional[str] = None,
) -> str:
    """将时间段格式化为 `HH:MM - HH:MM`，必要时先转换到指定时区。"""

    target_start = start_dt
    target_end = end_dt
    if tz_name:
        zone = ZoneInfo(tz_name)
        if start_dt.tzinfo is not None and start_dt.utcoffset() is not None:
            target_start = start_dt.astimezone(zone)
        if end_dt.tzinfo is not None and end_dt.utcoffset() is not None:
            target_end = end_dt.astimezone(zone)
    return f"{target_start.strftime('%H:%M')} - {target_end.strftime('%H:%M')}"


def build_timeslot_display_row(
    start_dt: datetime.datetime,
    end_dt: datetime.datetime,
    *,
    primary_tz_name: Optional[str] = None,
    secondary_tz_name: Optional[str] = None,
) -> Dict[str, str]:
    """生成用于表格渲染的时间槽展示行。"""

    primary_start = start_dt
    if primary_tz_name:
        zone = ZoneInfo(primary_tz_name)
        if start_dt.tzinfo is not None and start_dt.utcoffset() is not None:
            primary_start = start_dt.astimezone(zone)
    return {
        "date": primary_start.strftime("%Y-%m-%d"),
        "primary_slot": format_slot_range(start_dt, end_dt, tz_name=primary_tz_name),
        "secondary_slot": format_slot_range(start_dt, end_dt, tz_name=secondary_tz_name) if secondary_tz_name else "",
    }


def build_option_string(
    index: int,
    start_dt: datetime.datetime,
    end_dt: datetime.datetime,
    *,
    primary_tz_name: Optional[str] = "Asia/Shanghai",
    secondary_tz_name: Optional[str] = None,
    coverage: Any = "",
    note: str = "",
) -> str:
    """构造 render_confirmation_prompt.py 接受的 --option 结构化字符串。

    格式: <index>|<date>|<primary_slot>|<secondary_slot>|<coverage>|<note>
    """

    display = build_timeslot_display_row(
        start_dt,
        end_dt,
        primary_tz_name=primary_tz_name,
        secondary_tz_name=secondary_tz_name,
    )

    # 处理 coverage 格式化
    coverage_str = str(coverage)
    if isinstance(coverage, (int, float)):
        coverage_str = f"{coverage * 100:.0f}%"

    return f"{index}|{display['date']}|{display['primary_slot']}|{display['secondary_slot']}|{coverage_str}|{note}"


def _intersect(
    start1: datetime.datetime,
    end1: datetime.datetime,
    start2: datetime.datetime,
    end2: datetime.datetime,
) -> Optional[Tuple[datetime.datetime, datetime.datetime]]:
    """求两个区间的交集。无交集返回 None。"""

    start = max(start1, start2)
    end = min(end1, end2)
    if end <= start:
        return None
    return (start, end)


def build_default_candidate_windows(
    dates: List[datetime.date],
    user_tz: Optional[str] = "Asia/Shanghai",
    counterpart_tz: Optional[str] = None,
    work_start_hour: int = 10,
    work_end_hour: int = 19,
    fallback_user_start_hour: int = 19,
    fallback_user_end_hour_next_day: int = 1,
) -> List[Tuple[datetime.datetime, datetime.datetime]]:
    """按【绝对红线】生成跨时区候选查询窗口。

    规则（必须与 SKILL.md 保持一致）：

    1) 默认工作时间段：双方各自时区 `10:00-19:00`。
    2) 优先求交集：在统一时间线求交集后，作为候选窗口。
    3) 跨时区降级窗口：若默认工作时间段完全无交集，则仅将用户（奇楠）窗口
       单向延长为 `19:00-次日 01:00`（用户时区），并在该窗口内再次与对方
       `10:00-19:00` 求交集。

    返回：
        List[(start_dt, end_dt)]，均为 **用户时区的 tz-aware datetime**，用于直接
        传入 `suggest_timeslots` / `classify_timeslots`。

    注意：
        - `dates` 以用户时区的“日期”理解；对方工作日日期会自动在相邻日期内
          探测（跨日时差场景）。
        - 若未能权威获取 `counterpart_tz`，必须直接熔断报错，禁止默认 fallback。
    """

    if not user_tz:
        raise ValueError("未能权威获取用户时区，请用户确认")
    if not counterpart_tz:
        raise ValueError("未能权威获取对方时区，请用户确认")

    user_zone = ZoneInfo(user_tz)
    cp_zone = ZoneInfo(counterpart_tz)

    def _user_work_window(day: datetime.date) -> Tuple[datetime.datetime, datetime.datetime]:
        start = datetime.datetime.combine(day, datetime.time(hour=work_start_hour, minute=0), tzinfo=user_zone)
        end = datetime.datetime.combine(day, datetime.time(hour=work_end_hour, minute=0), tzinfo=user_zone)
        return start, end

    def _user_fallback_window(day: datetime.date) -> Tuple[datetime.datetime, datetime.datetime]:
        start = datetime.datetime.combine(day, datetime.time(hour=fallback_user_start_hour, minute=0), tzinfo=user_zone)
        end = datetime.datetime.combine(
            day + datetime.timedelta(days=1),
            datetime.time(hour=fallback_user_end_hour_next_day, minute=0),
            tzinfo=user_zone,
        )
        return start, end

    def _cp_work_window(cp_day: datetime.date) -> Tuple[datetime.datetime, datetime.datetime]:
        start = datetime.datetime.combine(cp_day, datetime.time(hour=work_start_hour, minute=0), tzinfo=cp_zone)
        end = datetime.datetime.combine(cp_day, datetime.time(hour=work_end_hour, minute=0), tzinfo=cp_zone)
        return start, end

    def _intersections_for_user_window(
        user_start: datetime.datetime,
        user_end: datetime.datetime,
    ) -> List[Tuple[datetime.datetime, datetime.datetime]]:
        # 将用户窗口投影到对方时区，推断可能产生交集的对方日期（含相邻日兜底）
        cp_start = user_start.astimezone(cp_zone)
        cp_end = user_end.astimezone(cp_zone)
        cp_dates = {
            cp_start.date(),
            cp_end.date(),
            cp_start.date() - datetime.timedelta(days=1),
            cp_end.date() + datetime.timedelta(days=1),
        }

        intersections: List[Tuple[datetime.datetime, datetime.datetime]] = []
        for cp_day in sorted(cp_dates):
            cp_w_start, cp_w_end = _cp_work_window(cp_day)
            # 对方工作窗口转换到用户时区，与用户窗口求交
            cp_w_start_u = cp_w_start.astimezone(user_zone)
            cp_w_end_u = cp_w_end.astimezone(user_zone)
            inter = _intersect(user_start, user_end, cp_w_start_u, cp_w_end_u)
            if inter is not None:
                intersections.append(inter)
        return intersections

    # 1) 优先：双方 10:00-19:00 工作时间求交
    windows: List[Tuple[datetime.datetime, datetime.datetime]] = []
    for day in dates:
        u_start, u_end = _user_work_window(day)
        windows.extend(_intersections_for_user_window(u_start, u_end))

    if windows:
        return windows

    # 2) 降级：仅用户晚间窗口 19:00-次日01:00，再与对方 10:00-19:00 求交
    fallback: List[Tuple[datetime.datetime, datetime.datetime]] = []
    for day in dates:
        u_start, u_end = _user_fallback_window(day)
        fallback.extend(_intersections_for_user_window(u_start, u_end))

    return fallback


def _validate_datetime_pair(
    dt1: datetime.datetime,
    dt2: datetime.datetime,
    context: str,
) -> None:
    """校验两个 datetime 的 tz-aware/naive 状态一致，禁止静默混用。"""

    dt1_aware = dt1.tzinfo is not None and dt1.utcoffset() is not None
    dt2_aware = dt2.tzinfo is not None and dt2.utcoffset() is not None
    if dt1_aware != dt2_aware:
        raise ValueError(f"检测到 naive/tz-aware datetime 混用（{context}），请统一输入时间格式")


def parse_time(timestr: str) -> datetime.datetime:
    """根据字符串解析时间。

    参数示例: "YYYY-MM-DD HH:MM"
    """

    return datetime.datetime.strptime(timestr, "%Y-%m-%d %H:%M")


def _overlaps(start1: datetime.datetime, end1: datetime.datetime,
              start2: datetime.datetime, end2: datetime.datetime) -> bool:
    """判断两个时间段是否有交集。"""

    _validate_datetime_pair(start1, end1, "overlap/start_end_1")
    _validate_datetime_pair(start2, end2, "overlap/start_end_2")
    _validate_datetime_pair(start1, start2, "overlap/input_pair")
    return not (end1 <= start2 or start1 >= end2)


def suggest_timeslots(
    candidate_windows: Iterable[Tuple[datetime.datetime, datetime.datetime]],
    duration_minutes: int,
    busy_map: Dict[str, List[Tuple[datetime.datetime, datetime.datetime]]],
) -> List[Tuple[datetime.datetime, datetime.datetime, int, List[str]]]:
    """计算冲突最少的候选时段（向下兼容原有逻辑）。

    参数：
        candidate_windows: 候选查询窗口列表 [(start_dt, end_dt), ...]
        duration_minutes: 会议时长（分钟）
        busy_map: 每个参会人的"忙碌"区间

    返回：
        前 3 个冲突最少的时段列表：
        [(slot_start, slot_end, conflict_count, conflict_people)]
    """

    step = datetime.timedelta(minutes=15)
    duration = datetime.timedelta(minutes=duration_minutes)

    suggestions: List[Tuple[datetime.datetime, datetime.datetime, int, List[str]]] = []

    for win_start, win_end in candidate_windows:
        cur = win_start
        while cur + duration <= win_end:
            slot_start = cur
            slot_end = cur + duration
            conflicts: List[str] = []
            for person, intervals in busy_map.items():
                for b_start, b_end in intervals:
                    if _overlaps(slot_start, slot_end, b_start, b_end):
                        conflicts.append(person)
                        break
            suggestions.append((slot_start, slot_end, len(conflicts), sorted(conflicts)))
            cur += step

    # 优先冲突少；再按时间早
    suggestions.sort(key=lambda x: (x[2], x[0]))

    # 去重：同一 start/end 的重复
    seen = set()
    top: List[Tuple[datetime.datetime, datetime.datetime, int, List[str]]] = []
    for s in suggestions:
        k = (s[0], s[1])
        if k in seen:
            continue
        seen.add(k)
        top.append(s)
        if len(top) >= 3:
            break

    return top


def classify_timeslots(
    candidate_windows: Iterable[Tuple[datetime.datetime, datetime.datetime]],
    duration_minutes: int,
    busy_map: Dict[str, List[Tuple[datetime.datetime, datetime.datetime]]],
    tentative_map: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    preemption_enabled: bool = True,
    preemption_sensitivity: float = 1.0,
) -> Dict[str, List[Dict[str, Any]]]:
    """基于忙碌 + Tentative 日程，对候选时段进行分类。

    参数：
        candidate_windows: 候选查询窗口列表 [(start_dt, end_dt), ...]
        duration_minutes: 会议时长（分钟），如 30 或 90
        busy_map: 每个参会人的"硬冲突"区间
            - 结构: { person: [(start_dt, end_dt), ...], ... }
            - 这些区间视为不可抢占，任何命中即直接排除该时段。
        tentative_map: 每个参会人的 Tentative/未接受日程列表（可选）
            - 结构: { person: [{"start": dt, "end": dt, "title": str, "weight": float?}, ...], ... }
            - `weight` 用于冲突权重计算，缺省为 1.0。
        preemption_enabled: 是否允许在无绝对空闲时考虑抢占候选。
        preemption_sensitivity: [0, 1] 之间的小数，控制可被 Tentative
            影响的参会人占比阈值。比如：
            - 1.0: 所有人都是 Tentative 也可作为候选；
            - 0.5: 至多一半参会人落在 Tentative 事件上才会被视为候选。

    返回：
        一个 dict，包含：
        {
          "absolute_free": [
              {"start": dt, "end": dt, "attendees": [..]}
          ],
          "preemptable": [
              {
                "start": dt,
                "end": dt,
                "preemption_targets": [
                    {"person": str, "event_title": str, "conflict_weight": float},
                    ...
                ],
                "total_conflict_weight": float,
              }
          ],
        }

    用法建议：
      - Stage 1 中优先使用 `absolute_free` 列表；
      - 若列表为空且 `preemption_enabled=True`，再考虑 `preemptable` 列表中冲突权重
        最低的若干候选，结合用户话术进行二次确认。
    """

    step = datetime.timedelta(minutes=15)
    duration = datetime.timedelta(minutes=duration_minutes)

    # 合法化敏感度边界
    if preemption_sensitivity < 0:
        preemption_sensitivity = 0.0
    if preemption_sensitivity > 1:
        preemption_sensitivity = 1.0

    # 参与人集合：busy_map 与 tentative_map 的并集
    people = set(busy_map.keys())
    if tentative_map:
        people.update(tentative_map.keys())

    absolute_free: List[Dict[str, Any]] = []
    preemptable_slots: List[Dict[str, Any]] = []

    for win_start, win_end in candidate_windows:
        cur = win_start
        while cur + duration <= win_end:
            slot_start = cur
            slot_end = cur + duration

            hard_conflict = False
            preemption_targets: List[Dict[str, Any]] = []

            for person in sorted(people):
                # 1) 检查硬冲突（已接受/必须参加的事件）
                for b_start, b_end in busy_map.get(person, []):
                    if _overlaps(slot_start, slot_end, b_start, b_end):
                        hard_conflict = True
                        break
                if hard_conflict:
                    break

                # 2) 检查 Tentative 事件（可抢占）
                if tentative_map and preemption_enabled:
                    for event in tentative_map.get(person, []):
                        t_start = event.get("start")
                        t_end = event.get("end")
                        if t_start is None or t_end is None:
                            continue
                        if _overlaps(slot_start, slot_end, t_start, t_end):
                            title = str(event.get("title", ""))
                            weight = float(event.get("weight", 1.0))
                            preemption_targets.append(
                                {
                                    "person": person,
                                    "event_title": title,
                                    "conflict_weight": weight,
                                }
                            )
                            break

            if hard_conflict:
                # 有任何硬冲突则此时段直接作废
                cur += step
                continue

            if not preemption_targets:
                # 完全无冲突：绝对空闲时段
                absolute_free.append(
                    {
                        "start": slot_start,
                        "end": slot_end,
                        "attendees": sorted(people),
                    }
                )
            elif preemption_enabled:
                # 仅 Tentative 冲突，且允许抢占模式
                impacted_people = {t["person"] for t in preemption_targets}
                total_people = len(people) or 1
                ratio = len(impacted_people) / float(total_people)
                if ratio <= preemption_sensitivity:
                    total_weight = sum(t["conflict_weight"] for t in preemption_targets)
                    preemptable_slots.append(
                        {
                            "start": slot_start,
                            "end": slot_end,
                            "preemption_targets": preemption_targets,
                            "total_conflict_weight": total_weight,
                        }
                    )

            cur += step

    # 排序：绝对空闲按时间，抢占候选按冲突权重 + 时间
    absolute_free.sort(key=lambda s: s["start"])
    preemptable_slots.sort(key=lambda s: (s["total_conflict_weight"], s["start"]))

    return {"absolute_free": absolute_free, "preemptable": preemptable_slots}


if __name__ == "__main__":
    # 简单示例：1 天候选窗口 + 忙碌区间 + Tentative 事件
    w1 = (parse_time("2026-04-01 10:00"), parse_time("2026-04-01 12:00"))

    busy_map_demo = {
        "Alice": [(parse_time("2026-04-01 10:00"), parse_time("2026-04-01 10:30"))],
        "Bob": [(parse_time("2026-04-01 09:30"), parse_time("2026-04-01 11:00"))],
        "Carol": [],
    }

    tentative_map_demo = {
        "Carol": [
            {
                "start": parse_time("2026-04-01 11:00"),
                "end": parse_time("2026-04-01 11:30"),
                "title": "内容周会 (Tentative)",
                "weight": 1.0,
            }
        ]
    }

    print("Top suggestions (legacy API):")
    for i, (slot_start, slot_end, conflict_count, conflicts) in enumerate(suggest_timeslots([w1], 30, busy_map_demo), 1):
        opt = build_option_string(i, slot_start, slot_end, coverage=(1.0 - conflict_count/len(busy_map_demo)))
        print(f"Option: {opt}")

    print("\nClassified slots (with preemption):")
    result = classify_timeslots([w1], 30, busy_map_demo, tentative_map_demo, preemption_enabled=True, preemption_sensitivity=1.0)
    for i, slot in enumerate(result["absolute_free"], 1):
        opt = build_option_string(i, slot["start"], slot["end"], coverage=1.0)
        print(f"ABSOLUTE Option: {opt}")
    
    start_idx = len(result["absolute_free"]) + 1
    for i, slot in enumerate(result["preemptable"], start_idx):
        coverage = 1.0 - (len(slot["preemption_targets"]) / len(busy_map_demo))
        opt = build_option_string(i, slot["start"], slot["end"], coverage=coverage, note="可抢占")
        print(f"PREEMPT Option: {opt}")
