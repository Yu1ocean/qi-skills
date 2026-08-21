#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
created_at_resolver —— 创建时间（created_at）字段解析器（技能自包含版）。

# [FIELD-CREATED_AT-v1] 创建时间字段，来源平台 publish_time，禁止删除
# 来源：ledger_year_audit_20260821 / DEC-20260821（热门剧本沉淀 P0 治理）

设计意图
--------
本轮 P0 治理审计发现全链路零处 pub_date 时效过滤，入库样本中位年龄 436 天、
74.4% 超 90 天。项目层与 hot-radar 已加固，但下游归档 / 拆解技能被单独调用时
仍会漏掉时效元数据 —— 本模块把「创建时间 + 时效状态」从 Prompt 约定升级为
**进程内断言**。

NULL 契约（底线，禁止放宽）
--------------------------
解析不到发布时间时：
  * 归档场景（script-archive）：填 `⚠️[数据断链_待自愈]`
  * 拆解场景（video-script）：填 `NULL`
**严禁**填空串 / None / 0 / 今天 —— 那会让断链行伪装成正常数据，永久失去自愈机会。

对外入口
--------
    resolve_created_at(record, ...)   -> (created_at:str, source:str)
    classify_freshness(created_at)    -> "✅ 时效内" | "⚠️ 历史存量" | "❓ 待核实"
    extract_video_id(url)             -> Optional[str]
    decode_snowflake_date(video_id)   -> Optional[date]
    assert_created_at_fields(row)     -> None（L3 运行时断言，失败即 raise）

snowflake 反解口径与 hot-radar/pub_date_guard.py 保持同源：TikTok / 抖音
video_id 高 32 位即 unix 秒。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, Tuple

# --------------------------------------------------------------------------- #
# Defaults（合规默认值：只严不宽）
# --------------------------------------------------------------------------- #
DEFAULT_DATE_FORMAT = "%Y-%m-%d"
DEFAULT_FRESH_CUTOFF_DAYS = 90

# NULL 哨兵：归档链路用「待自愈」，拆解链路用 NULL
SENTINEL_BROKEN_LINK = "⚠️[数据断链_待自愈]"
SENTINEL_NULL = "NULL"

# 时效状态三态标签
LABEL_FRESH = "✅ 时效内"
LABEL_STALE = "⚠️ 历史存量"
LABEL_UNKNOWN = "❓ 待核实"

# snowflake sanity 区间：2011-03-13 ~ 2030-03-18（与 hot-radar 同值）
SNOWFLAKE_MIN_UNIX_TS = 1300000000
SNOWFLAKE_MAX_UNIX_TS = 1900000000

# 显式 NULL 契约：以下取值一律视为「没有发布时间」，而不是 0 或空串
_NULL_TOKENS = {
    "",
    "null",
    "none",
    "nan",
    "n/a",
    "na",
    "unknown",
    "-",
    "0",
    SENTINEL_BROKEN_LINK.lower(),
}

_VIDEO_ID_PATTERNS = [
    re.compile(r"/video/(\d{6,25})"),
    re.compile(r"/note/(\d{6,25})"),
    re.compile(r"[?&]video_id=(\d{6,25})"),
    re.compile(r"[?&]modal_id=(\d{6,25})"),
]

# publish_time 的候选字段名（按优先级；命中即停）
_PUBLISH_TIME_KEYS = (
    "publish_time",
    "publish_date",
    "pub_date",
    "created_at",
    "timestamp",
    "upload_date",
)

_URL_KEYS = ("video_url", "source_url", "url")


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def _is_null_token(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in _NULL_TOKENS


def extract_video_id(url: Any) -> Optional[str]:
    """从 URL 中抽取 video_id；抽不到返回 None（不猜、不造）。"""
    text = str(url or "")
    for pattern in _VIDEO_ID_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1)
    return None


def decode_snowflake_date(video_id: Any) -> Optional[date]:
    """TikTok / 抖音 video_id 高 32 位反解 unix 秒 -> UTC 日期。不可解析返回 None。"""
    try:
        n = int(str(video_id).strip())
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    ts = n >> 32
    if not (SNOWFLAKE_MIN_UNIX_TS < ts < SNOWFLAKE_MAX_UNIX_TS):
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).date()


def _parse_date_like(value: Any) -> Optional[date]:
    """解析常见发布时间写法，失败返回 None。绝不返回猜测值。"""
    if _is_null_token(value):
        return None
    text = str(value).strip()

    # unix 秒 / 毫秒
    if re.fullmatch(r"\d{9,13}", text):
        num = int(text)
        if num > 10_000_000_000:  # 毫秒
            num //= 1000
        if SNOWFLAKE_MIN_UNIX_TS < num < SNOWFLAKE_MAX_UNIX_TS:
            return datetime.fromtimestamp(num, tz=timezone.utc).date()
        return None

    # YYYYMMDD（yt-dlp upload_date）
    if re.fullmatch(r"\d{8}", text):
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return None

    normalized = text.replace("/", "-").replace("T", " ").replace("Z", "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(normalized[: len(fmt) + 6].strip(), fmt).date()
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
# [FIELD-CREATED_AT-v1] 创建时间字段，来源平台 publish_time，禁止删除
def resolve_created_at(
    record: Dict[str, Any],
    null_sentinel: str = SENTINEL_BROKEN_LINK,
) -> Tuple[str, str]:
    """
    解析记录的创建时间（视频原始发布时间）。

    优先级：显式 publish_time 家族字段 -> metadata 内同名字段 -> video_id snowflake 反解。

    返回 (created_at, source)：
      * created_at：`YYYY-MM-DD`，或解析失败时的 `null_sentinel`
      * source ∈ {publish_time, metadata, snowflake, NULL}

    绝不返回空串 / None / 0 / 今天 —— 见模块头 NULL 契约。
    """
    meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}

    # 1) 记录自带的 publish_time 家族
    for key in _PUBLISH_TIME_KEYS:
        got = _parse_date_like(record.get(key))
        if got is not None:
            return got.strftime(DEFAULT_DATE_FORMAT), "publish_time"

    # 2) metadata 内的同名字段
    for key in _PUBLISH_TIME_KEYS:
        got = _parse_date_like(meta.get(key))
        if got is not None:
            return got.strftime(DEFAULT_DATE_FORMAT), "metadata"

    # 3) snowflake 反解兜底
    vid = record.get("video_id") or meta.get("video_id")
    if _is_null_token(vid):
        vid = None
        for key in _URL_KEYS:
            vid = extract_video_id(record.get(key))
            if vid:
                break
    if vid:
        got = decode_snowflake_date(vid)
        if got is not None:
            return got.strftime(DEFAULT_DATE_FORMAT), "snowflake"

    # 4) 断链：显式哨兵，禁止空串 / None / 0
    return null_sentinel, "NULL"


def classify_freshness(
    created_at: Any,
    today: Optional[date] = None,
    cutoff_days: int = DEFAULT_FRESH_CUTOFF_DAYS,
) -> str:
    """
    时效状态三态分类：
      距今 <= cutoff_days -> ✅ 时效内
      距今 >  cutoff_days -> ⚠️ 历史存量
      无法判断（断链 / 未来日期 / 非法格式）-> ❓ 待核实
    """
    parsed = _parse_date_like(created_at)
    if parsed is None:
        return LABEL_UNKNOWN
    ref = today or datetime.now(tz=timezone.utc).date()
    age = (ref - parsed).days
    if age < 0:
        # 未来发布日 = 数据可疑，不允许伪装成「时效内」
        return LABEL_UNKNOWN
    return LABEL_FRESH if age <= cutoff_days else LABEL_STALE


# --------------------------------------------------------------------------- #
# L3 运行时断言层
# --------------------------------------------------------------------------- #
def assert_created_at_fields(
    row: Dict[str, Any],
    created_at_key: str = "created_at",
    freshness_key: str = "freshness_status",
) -> None:
    """
    归档 / 输出前的物理熔断：created_at 与时效状态必须完整合法。

    任一不满足即 raise —— 严禁「先归档，创建时间以后补」。
    """
    if created_at_key not in row:
        raise ValueError(
            f"[FIELD-CREATED_AT-v1] 缺少 {created_at_key} 字段，禁止归档（来源 DEC-20260821）"
        )
    value = row.get(created_at_key)
    if value is None or str(value).strip() == "" or str(value).strip() in {"0", "None"}:
        raise ValueError(
            f"[FIELD-CREATED_AT-v1] {created_at_key} 为空串/None/0，必须写 {SENTINEL_BROKEN_LINK}"
        )
    text = str(value).strip()
    if text not in (SENTINEL_BROKEN_LINK, SENTINEL_NULL) and not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", text
    ):
        raise ValueError(
            f"[FIELD-CREATED_AT-v1] {created_at_key}={text!r} 格式非法，必须为 YYYY-MM-DD"
        )
    if freshness_key not in row:
        raise ValueError(
            f"[FIELD-CREATED_AT-v1] 缺少 {freshness_key} 字段，禁止归档"
        )
    if str(row.get(freshness_key)).strip() not in {
        LABEL_FRESH,
        LABEL_STALE,
        LABEL_UNKNOWN,
    }:
        raise ValueError(
            f"[FIELD-CREATED_AT-v1] {freshness_key}={row.get(freshness_key)!r} 非三态合法标签"
        )


__all__ = [
    "resolve_created_at",
    "classify_freshness",
    "extract_video_id",
    "decode_snowflake_date",
    "assert_created_at_fields",
    "SENTINEL_BROKEN_LINK",
    "SENTINEL_NULL",
    "LABEL_FRESH",
    "LABEL_STALE",
    "LABEL_UNKNOWN",
    "DEFAULT_FRESH_CUTOFF_DAYS",
]
