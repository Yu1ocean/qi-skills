"""
interval_intersect.py — 时间区间交集计算器

用于 Mode B：在 pending_user 与 yuqinan 的 freebusy 列表中，
找到第一个 ≥ min_minutes 的共同空闲交集。

输入约定（freebusy 数组）：
    [{"start_time": "ISO8601", "end_time": "ISO8601"}, ...]
    表示「忙碌区间」（与飞书 freebusy API 一致）

工作时间窗约定：
    默认 16:00 ~ 22:00（当地 Asia/Shanghai 时间），可由调用方覆盖
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional


CST = timezone(timedelta(hours=8))


def _parse_iso(s: str) -> datetime:
    """容错解析 ISO 8601 时间字符串（含 / 不含 timezone）。"""
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # 尝试 'YYYY-MM-DD HH:MM:SS' 格式
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)
    return dt


def _merge_busy(busy_list: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """合并重叠的忙碌区间。"""
    if not busy_list:
        return []
    sorted_busy = sorted(busy_list, key=lambda x: x[0])
    merged: list[tuple[datetime, datetime]] = [sorted_busy[0]]
    for start, end in sorted_busy[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def busy_to_free(
    busy_list: list[dict],
    window_start: datetime,
    window_end: datetime,
) -> list[tuple[datetime, datetime]]:
    """把忙碌列表反转为空闲列表（限定在 [window_start, window_end] 内）。"""
    busy = []
    for b in busy_list:
        s = _parse_iso(b["start_time"])
        e = _parse_iso(b["end_time"])
        # 裁剪到窗口内
        s = max(s, window_start)
        e = min(e, window_end)
        if s < e:
            busy.append((s, e))
    busy = _merge_busy(busy)

    free: list[tuple[datetime, datetime]] = []
    cursor = window_start
    for bs, be in busy:
        if bs > cursor:
            free.append((cursor, bs))
        cursor = max(cursor, be)
    if cursor < window_end:
        free.append((cursor, window_end))
    return free


def intersect_free(
    free_a: list[tuple[datetime, datetime]],
    free_b: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """两个空闲列表的交集。"""
    result: list[tuple[datetime, datetime]] = []
    i = j = 0
    while i < len(free_a) and j < len(free_b):
        s = max(free_a[i][0], free_b[j][0])
        e = min(free_a[i][1], free_b[j][1])
        if s < e:
            result.append((s, e))
        if free_a[i][1] < free_b[j][1]:
            i += 1
        else:
            j += 1
    return result


def find_common_slot(
    busy_a: list[dict],
    busy_b: list[dict],
    window_start: datetime,
    window_end: datetime,
    min_minutes: int = 15,
) -> Optional[tuple[datetime, datetime]]:
    """在两人 busy 列表 + 工作窗口下，找到首个 ≥ min_minutes 的共同空闲。

    Returns:
        (slot_start, slot_end) — 取交集的前 min_minutes
        或 None — 如未找到任何足够长的共同空闲
    """
    free_a = busy_to_free(busy_a, window_start, window_end)
    free_b = busy_to_free(busy_b, window_start, window_end)
    common = intersect_free(free_a, free_b)
    min_delta = timedelta(minutes=min_minutes)
    for s, e in common:
        if (e - s) >= min_delta:
            return (s, s + min_delta)
    return None


if __name__ == "__main__":
    # 自检 demo
    ws = datetime(2026, 5, 25, 16, 0, tzinfo=CST)
    we = datetime(2026, 5, 25, 22, 0, tzinfo=CST)
    busy_a = [
        {"start_time": "2026-05-25T16:00:00+08:00", "end_time": "2026-05-25T17:00:00+08:00"},
        {"start_time": "2026-05-25T19:00:00+08:00", "end_time": "2026-05-25T20:00:00+08:00"},
    ]
    busy_b = [
        {"start_time": "2026-05-25T18:00:00+08:00", "end_time": "2026-05-25T18:30:00+08:00"},
    ]
    slot = find_common_slot(busy_a, busy_b, ws, we, 15)
    print(f"[OK] 共同空闲首个 15min slot: {slot}")
    assert slot is not None
    assert slot[0] == datetime(2026, 5, 25, 17, 0, tzinfo=CST), f"unexpected: {slot}"
    print("[OK] 区间交集自检通过")
