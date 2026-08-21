#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pub_date_guard —— hot-radar 技能本体的发布时间硬过滤守门员（技能自包含版）。

# [GUARD-PUB_DATE-v1] 此处为发布时间硬过滤断言，禁止删除或绕过
# 规则：pub_date 为 NULL 或超 90 天的候选物理拦截
# 来源：ledger_year_audit_20260821，DEC-20260821（热门剧本沉淀 P0 治理）

设计意图（把规则烧进代码而非 Prompt）
--------------------------------------
审计结论：全链路 67 个脚本零处 pub_date 过滤，`--time-window` 是只写元数据的
装饰参数，导致入库样本中位年龄 436 天、74.4% 超 90 天。项目层已加固，但技能
本体被单独调用时仍无任何时效保护 —— 本模块补上这个洞。

本模块把「时效」从 Prompt 约定升级为**进程内断言**：任何候选想进入下游，必须
先通过 `gate_candidates()`；拿不到发布时间就 reject，不允许静默放行。

对外三个主入口（与项目层实现保持同名同签名，便于互换）：
    gate_candidates(...)            -> 物理拦截 + 统计
    log_freshness_distribution(...) -> 链路入口可观测断言日志
    load_blacklist(...)             -> 伪造 ID 拉黑表

配置真相源：references/hot_radar_config.yaml（缺失时回退内置默认值，只严不宽）
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - pyyaml 缺失时降级为内置默认值
    yaml = None


# 技能自包含：以本文件所在的 scripts/ 的父目录（技能根）为基准解析配置
SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = SKILL_ROOT / "references" / "hot_radar_config.yaml"

# 与 references/hot_radar_config.yaml 保持一致的兜底默认值。
# 注意：这里的兜底只在配置文件缺失/损坏时生效，且**只会更严格不会更宽松**。
_FALLBACK_CONFIG: Dict[str, Any] = {
    "pub_date_filter": {
        "hard_cutoff_days": 90,
        "soft_prefer_days": 30,
        "null_action": "reject",
    },
    "pub_date_resolve": {
        "order": [
            "metadata_timestamp",
            "metadata_upload_date",
            "explicit_publish_time",
            "snowflake",
        ],
        "snowflake": {
            "enabled": True,
            "min_unix_ts": 1300000000,
            "max_unix_ts": 1900000000,
        },
    },
    "synthetic_id_filter": {
        "enabled": True,
        "reject_sequential_fingerprint": True,
        "reject_future_publish": True,
        "blacklist_file": "references/blacklist_video_ids.txt",
    },
    "observability": {
        "log_freshness_distribution": True,
        "age_buckets_days": [7, 14, 30, 90, 180, 365],
        "log_dir": "output/guard_logs",
    },
}

# 合规默认值：即使调用方什么都不传，也必须落在这两个值上
DEFAULT_HARD_CUTOFF_DAYS = 90
DEFAULT_NULL_ACTION = "reject"

# 顺序数字指纹：伪造 ID 的典型特征
_SEQ_FINGERPRINT = re.compile(
    r"(0123456789|1234567890|2345678901|3456789012|4567890123"
    r"|5678901234|6789012345|7890123456|8901234567|9012345678)"
)

_VIDEO_ID_PATTERNS = [
    re.compile(r"/video/(\d{6,25})"),
    re.compile(r"/note/(\d{6,25})"),
    re.compile(r"[?&]video_id=(\d{6,25})"),
    re.compile(r"[?&]modal_id=(\d{6,25})"),
]

# 显式 NULL 契约：以下取值一律视为「没有发布时间」，而不是 0 或空串
_NULL_TOKENS = {"", "null", "none", "nan", "n/a", "na", "unknown", "-", "0"}

_config_cache: Dict[str, Dict[str, Any]] = {}
_blacklist_cache: Dict[str, set] = {}


# --------------------------------------------------------------------------- #
# 配置与拉黑表加载
# --------------------------------------------------------------------------- #
def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(config_path: Optional[os.PathLike | str] = None) -> Dict[str, Any]:
    """加载治理配置。配置缺失或损坏时回退到内置默认值（只严不宽）。"""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    key = str(path)
    if key in _config_cache:
        return _config_cache[key]

    cfg = dict(_FALLBACK_CONFIG)
    if path.exists() and yaml is not None:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                cfg = _deep_merge(_FALLBACK_CONFIG, loaded)
        except Exception as exc:  # 配置损坏时不静默放行，走最严默认值并告警
            print(
                f"[GUARD-PUB_DATE-v1][WARN] 配置解析失败，回退内置默认值: {path} ({exc})",
                file=sys.stderr,
            )
    elif not path.exists():
        print(
            f"[GUARD-PUB_DATE-v1][WARN] 配置缺失，回退内置默认值"
            f"（hard_cutoff_days={DEFAULT_HARD_CUTOFF_DAYS}, null_action={DEFAULT_NULL_ACTION}）: {path}",
            file=sys.stderr,
        )

    # 合规默认值断言：配置不得把闸门放宽到失效
    pdf = cfg.setdefault("pub_date_filter", {})
    if not isinstance(pdf.get("hard_cutoff_days"), int) or int(pdf["hard_cutoff_days"]) <= 0:
        pdf["hard_cutoff_days"] = DEFAULT_HARD_CUTOFF_DAYS
    if str(pdf.get("null_action", "")).lower() not in {"reject", "keep"}:
        pdf["null_action"] = DEFAULT_NULL_ACTION

    _config_cache[key] = cfg
    return cfg


def load_blacklist(
    blacklist_path: Optional[os.PathLike | str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> set:
    """加载伪造 video_id 拉黑表，返回 video_id 字符串集合。文件缺失返回空集合。"""
    cfg = config or load_config()
    if blacklist_path is None:
        rel = (
            cfg.get("synthetic_id_filter", {}).get("blacklist_file")
            or "references/blacklist_video_ids.txt"
        )
        path = SKILL_ROOT / rel
    else:
        path = Path(blacklist_path)

    key = str(path)
    if key in _blacklist_cache:
        return _blacklist_cache[key]

    ids: set = set()
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if line:
                ids.add(line)
    _blacklist_cache[key] = ids
    return ids


# --------------------------------------------------------------------------- #
# 发布时间解析
# --------------------------------------------------------------------------- #
def extract_video_id(url: str) -> Optional[str]:
    """从候选 URL 中抽取 video_id；抽不到返回 None（不猜、不造）。"""
    text = str(url or "")
    for pattern in _VIDEO_ID_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1)
    return None


def _is_null_token(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in _NULL_TOKENS


def decode_snowflake_date(
    video_id: str, config: Optional[Dict[str, Any]] = None
) -> Optional[date]:
    """TikTok / 抖音 ID 高 32 位反解 unix 秒 -> UTC 日期。不可解析返回 None。"""
    cfg = (config or load_config()).get("pub_date_resolve", {}).get("snowflake", {})
    if not cfg.get("enabled", True):
        return None
    try:
        n = int(str(video_id).strip())
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    ts = n >> 32
    if not (
        int(cfg.get("min_unix_ts", 1300000000))
        < ts
        < int(cfg.get("max_unix_ts", 1900000000))
    ):
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
        if 1_300_000_000 < num < 1_900_000_000:
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


def resolve_publish_date(
    candidate: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[date], str]:
    """
    按配置优先级解析候选的发布日期。

    返回 (date | None, source)。source ∈ {metadata_timestamp, metadata_upload_date,
    explicit_publish_time, snowflake, NULL}。解析不到时返回 (None, "NULL")，
    绝不返回估算值 —— 这是 NULL 契约的底线。
    """
    cfg = config or load_config()
    order: Sequence[str] = cfg.get("pub_date_resolve", {}).get("order") or [
        "metadata_timestamp",
        "metadata_upload_date",
        "explicit_publish_time",
        "snowflake",
    ]

    meta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}

    for source in order:
        got: Optional[date] = None
        if source == "metadata_timestamp":
            got = _parse_date_like(candidate.get("timestamp") or meta.get("timestamp"))
        elif source == "metadata_upload_date":
            got = _parse_date_like(candidate.get("upload_date") or meta.get("upload_date"))
        elif source == "explicit_publish_time":
            got = _parse_date_like(
                candidate.get("publish_time")
                or candidate.get("publish_date")
                or candidate.get("pub_date")
            )
            if got is not None:
                # 上游若已标注真实来源（如 snowflake 反解），保留其溯源标签
                hint = candidate.get("pub_date_source")
                if hint and not _is_null_token(hint):
                    return got, str(hint)
        elif source == "snowflake":
            vid = candidate.get("video_id") or extract_video_id(
                candidate.get("video_url") or candidate.get("url") or ""
            )
            if vid:
                got = decode_snowflake_date(vid, cfg)
        if got is not None:
            return got, source

    return None, "NULL"


# --------------------------------------------------------------------------- #
# time-window 解析（让 --time-window 真实参与过滤，而非只写元数据）
# --------------------------------------------------------------------------- #
_TIME_WINDOW_PATTERNS = [
    re.compile(r"近\s*(\d+)\s*天"),
    re.compile(r"最近\s*(\d+)\s*天"),
    re.compile(r"过去\s*(\d+)\s*天"),
    re.compile(r"last\s*(\d+)\s*days?", re.I),
    re.compile(r"past\s*(\d+)\s*days?", re.I),
    re.compile(r"^\s*(\d+)\s*d\s*$", re.I),
    re.compile(r"^\s*(\d+)\s*$"),
]
_TIME_WINDOW_ALIASES = {
    "近一周": 7, "近1周": 7, "最近一周": 7, "本周": 7, "一周内": 7,
    "近两周": 14, "近2周": 14, "近半月": 15,
    "近一月": 30, "近1月": 30, "近一个月": 30, "最近一个月": 30, "本月": 30,
    "近两月": 60, "近2月": 60, "近三月": 90, "近3月": 90, "近一季度": 90,
}


def parse_time_window_days(time_window: Any) -> Optional[int]:
    """把 '近7天' / 'last 7 days' / '7d' / '30' 解析为天数。无法解析返回 None。"""
    if _is_null_token(time_window):
        return None
    text = str(time_window).strip()
    if text in _TIME_WINDOW_ALIASES:
        return _TIME_WINDOW_ALIASES[text]
    for pattern in _TIME_WINDOW_PATTERNS:
        m = pattern.search(text)
        if m:
            days = int(m.group(1))
            return days if days > 0 else None
    return None


def resolve_cutoff_days(
    time_window: Any = None,
    config: Optional[Dict[str, Any]] = None,
    strict: bool = True,
    hard_cutoff_days: Optional[int] = None,
) -> int:
    """
    计算本次运行的**有效硬过滤天数**。

    口径：effective = min(time_window_days, hard_cutoff_days)
      - 未传 time_window        -> 直接用 hard_cutoff_days（默认 90）
      - 传了且可解析            -> 取更严格的一侧，让 --time-window 真实生效
      - 传了但无法解析且 strict -> 抛错熔断（禁止「解析失败=不过滤」的静默放行）
    """
    cfg = config or load_config()
    hard = int(
        hard_cutoff_days
        if hard_cutoff_days is not None
        else cfg.get("pub_date_filter", {}).get("hard_cutoff_days", DEFAULT_HARD_CUTOFF_DAYS)
    )
    if hard <= 0:
        hard = DEFAULT_HARD_CUTOFF_DAYS
    if _is_null_token(time_window):
        return hard
    days = parse_time_window_days(time_window)
    if days is None:
        if strict:
            raise ValueError(
                f"[GUARD-PUB_DATE-v1] --time-window 无法解析: {time_window!r}；"
                f"禁止静默放行，请使用『近7天』/『last 7 days』/『7d』/『30』等格式"
            )
        return hard
    return min(days, hard)


# --------------------------------------------------------------------------- #
# 守门员主体
# --------------------------------------------------------------------------- #
class GateResult(dict):
    """单条候选的过闸结果（dict 子类，便于直接 json 序列化）。"""

    @property
    def ok(self) -> bool:
        return bool(self.get("ok"))


def gate_candidate(
    candidate: Dict[str, Any],
    ref_date: Optional[date] = None,
    cutoff_days: Optional[int] = None,
    config: Optional[Dict[str, Any]] = None,
    blacklist: Optional[set] = None,
    null_action: Optional[str] = None,
) -> GateResult:
    """
    # [GUARD-PUB_DATE-v1] 此处为发布时间硬过滤断言，禁止删除或绕过
    # 规则：pub_date 为 NULL 或超 90 天的候选物理拦截
    # 来源：ledger_year_audit_20260821，DEC-20260821（热门剧本沉淀 P0 治理）

    拦截顺序（命中即拒，reason 唯一）：
      1. blacklist_hit   —— 命中伪造 ID 拉黑表
      2. synthetic_id    —— 顺序数字指纹（编造 ID 指纹）
      3. null_pub_date   —— 发布时间解析不到（NULL 契约，默认一律 reject）
      4. future_pub_date —— 反解发布日晚于批次日（不可能的未来视频）
      5. stale_pub_date  —— 年龄 > 有效硬过滤天数
    """
    cfg = config or load_config()
    bl = blacklist if blacklist is not None else load_blacklist(config=cfg)
    ref = ref_date or datetime.now(tz=timezone.utc).date()
    cutoff = int(cutoff_days if cutoff_days is not None else resolve_cutoff_days(config=cfg))
    syn_cfg = cfg.get("synthetic_id_filter", {})
    soft_days = int(cfg.get("pub_date_filter", {}).get("soft_prefer_days", 30))
    action = str(
        null_action
        if null_action is not None
        else cfg.get("pub_date_filter", {}).get("null_action", DEFAULT_NULL_ACTION)
    ).lower()

    url = candidate.get("video_url") or candidate.get("url") or ""
    video_id = candidate.get("video_id") or extract_video_id(url)

    def _res(ok: bool, reason: str, **extra) -> GateResult:
        return GateResult(
            ok=ok,
            reason=reason,
            video_id=video_id,
            video_url=url,
            cutoff_days=cutoff,
            **extra,
        )

    # 1) 拉黑表
    if video_id and str(video_id) in bl:
        return _res(False, "blacklist_hit", publish_date=None, pub_date_source="NULL", age_days=None)

    # 2) 伪造 ID 指纹
    if (
        syn_cfg.get("enabled", True)
        and syn_cfg.get("reject_sequential_fingerprint", True)
        and video_id
        and _SEQ_FINGERPRINT.search(str(video_id))
    ):
        return _res(False, "synthetic_id", publish_date=None, pub_date_source="NULL", age_days=None)

    # 3) NULL 契约
    pub_date, pub_source = resolve_publish_date(candidate, cfg)
    if pub_date is None:
        if action == "reject":
            return _res(False, "null_pub_date", publish_date=None, pub_date_source="NULL", age_days=None)
        return _res(
            True, "null_pub_date_allowed",
            publish_date=None, pub_date_source="NULL", age_days=None, soft_preferred=False,
        )

    age_days = (ref - pub_date).days
    iso = pub_date.isoformat()

    # 4) 未来日期
    if syn_cfg.get("enabled", True) and syn_cfg.get("reject_future_publish", True) and age_days < 0:
        return _res(False, "future_pub_date", publish_date=iso, pub_date_source=pub_source, age_days=age_days)

    # 5) 硬过滤
    if age_days > cutoff:
        return _res(False, "stale_pub_date", publish_date=iso, pub_date_source=pub_source, age_days=age_days)

    return _res(
        True,
        "pass",
        publish_date=iso,
        pub_date_source=pub_source,
        age_days=age_days,
        soft_preferred=age_days <= soft_days,
    )


def gate_candidates(
    candidates: Iterable[Dict[str, Any]],
    ref_date: Optional[date] = None,
    time_window: Any = None,
    cutoff_days: Optional[int] = None,
    config: Optional[Dict[str, Any]] = None,
    blacklist: Optional[set] = None,
    annotate: bool = True,
    null_action: Optional[str] = None,
    hard_cutoff_days: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    # [GUARD-PUB_DATE-v1] 此处为发布时间硬过滤断言，禁止删除或绕过
    # 规则：pub_date 为 NULL 或超 90 天的候选物理拦截
    # 来源：ledger_year_audit_20260821，DEC-20260821（热门剧本沉淀 P0 治理）

    批量物理拦截入口，必须在 dedupe / top-n 截断**之前**调用。

    返回 (passed, rejected, stats)。
      - passed   : 通过闸门的候选（annotate=True 时回填 publish_time / age_days /
                   pub_date_source / soft_preferred；并按 soft_preferred → age 排序，
                   让近 30 天候选优先占据 top-n 名额）
      - rejected : 被拦截的候选，每条带 _gate 结果，可直接写 DLQ
      - stats    : 供 log_freshness_distribution 消费的统计
    """
    cfg = config or load_config()
    bl = blacklist if blacklist is not None else load_blacklist(config=cfg)
    ref = ref_date or datetime.now(tz=timezone.utc).date()
    cutoff = int(
        cutoff_days
        if cutoff_days is not None
        else resolve_cutoff_days(
            time_window=time_window, config=cfg, hard_cutoff_days=hard_cutoff_days
        )
    )
    soft_days = int(cfg.get("pub_date_filter", {}).get("soft_prefer_days", 30))
    action = str(
        null_action
        if null_action is not None
        else cfg.get("pub_date_filter", {}).get("null_action", DEFAULT_NULL_ACTION)
    ).lower()

    passed: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    reason_counts: Dict[str, int] = {}
    source_counts: Dict[str, int] = {}
    ages: List[int] = []

    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        result = gate_candidate(
            cand, ref_date=ref, cutoff_days=cutoff, config=cfg, blacklist=bl, null_action=action
        )
        reason_counts[result["reason"]] = reason_counts.get(result["reason"], 0) + 1
        src = result.get("pub_date_source") or "NULL"
        source_counts[src] = source_counts.get(src, 0) + 1
        if result.ok:
            row = dict(cand)
            if annotate:
                # NULL 契约：解析不到就写字符串 "NULL"，不写空串、不写 0
                row["publish_time"] = result.get("publish_date") or "NULL"
                row["pub_date_source"] = result.get("pub_date_source") or "NULL"
                row["age_days"] = result.get("age_days")
                row["soft_preferred"] = bool(result.get("soft_preferred"))
            if result.get("age_days") is not None:
                ages.append(int(result["age_days"]))
            passed.append(row)
        else:
            row = dict(cand)
            row["_gate"] = dict(result)
            rejected.append(row)

    # 软优选：近 30 天靠前，其次按年龄升序（越新越靠前），NULL 年龄垫底
    passed.sort(
        key=lambda r: (
            0 if r.get("soft_preferred") else 1,
            r.get("age_days") if isinstance(r.get("age_days"), int) else 10**9,
        )
    )

    buckets = cfg.get("observability", {}).get("age_buckets_days") or [7, 14, 30, 90, 180, 365]
    dist: Dict[str, int] = {f"<={b}d": 0 for b in buckets}
    dist[f">{buckets[-1]}d"] = 0
    for age in ages:
        placed = False
        for b in buckets:
            if age <= b:
                dist[f"<={b}d"] += 1
                placed = True
                break
        if not placed:
            dist[f">{buckets[-1]}d"] += 1

    total_in = len(passed) + len(rejected)
    ages_sorted = sorted(ages)
    stats: Dict[str, Any] = {
        "guard": "GUARD-PUB_DATE-v1",
        "ref_date": ref.isoformat(),
        "cutoff_days": cutoff,
        "soft_prefer_days": soft_days,
        "null_action": action,
        "time_window_arg": time_window if time_window is not None else "NULL",
        "total_in": total_in,
        "passed": len(passed),
        "rejected": len(rejected),
        "pass_rate": round(len(passed) / total_in, 4) if total_in else 0.0,
        "soft_preferred": sum(1 for r in passed if r.get("soft_preferred")),
        "reject_reasons": reason_counts,
        "pub_date_source": source_counts,
        "age_distribution": dist,
        "age_median_days": ages_sorted[len(ages_sorted) // 2] if ages_sorted else None,
        "age_max_days": max(ages) if ages else None,
        "blacklist_size": len(bl),
    }
    return passed, rejected, stats


# --------------------------------------------------------------------------- #
# 可观测性：链路入口断言日志
# --------------------------------------------------------------------------- #
def log_freshness_distribution(
    stats: Dict[str, Any],
    stage: str = "hot-radar",
    config: Optional[Dict[str, Any]] = None,
    write_file: bool = False,
    log_dir: Optional[os.PathLike | str] = None,
) -> Optional[Path]:
    """
    打印「本次候选池时效分布」断言日志到 stderr；write_file=True 时另落 JSONL。

    技能本体默认不落盘（避免污染调用方目录），项目链路可显式打开。
    """
    cfg = config or load_config()
    obs = cfg.get("observability", {})
    if not obs.get("log_freshness_distribution", True):
        return None

    lines = [
        "",
        "=" * 72,
        f"[GUARD-PUB_DATE-v1] 本次候选池时效分布 | stage={stage}",
        "=" * 72,
        f"  基准日 ref_date        : {stats.get('ref_date')}",
        f"  有效硬过滤 cutoff      : {stats.get('cutoff_days')} 天"
        f"（time-window 入参={stats.get('time_window_arg')}，硬顶=90）",
        f"  软优选阈值             : {stats.get('soft_prefer_days')} 天",
        f"  NULL 策略              : {stats.get('null_action')}",
        f"  入闸 / 通过 / 拦截     : {stats.get('total_in')} / {stats.get('passed')} / {stats.get('rejected')}"
        f"（通过率 {stats.get('pass_rate')}）",
        f"  其中命中软优选(≤30d)   : {stats.get('soft_preferred')}",
        f"  通过样本年龄 中位/最大 : {stats.get('age_median_days')} / {stats.get('age_max_days')} 天",
        "  ---- 年龄分布（仅通过样本）----",
    ]
    for bucket, count in (stats.get("age_distribution") or {}).items():
        lines.append(f"    {bucket:<10}: {count}")
    lines.append("  ---- 拦截原因 ----")
    if stats.get("reject_reasons"):
        for reason, count in sorted(
            (stats.get("reject_reasons") or {}).items(), key=lambda kv: -kv[1]
        ):
            lines.append(f"    {reason:<22}: {count}")
    else:
        lines.append("    （无）")
    lines.append("  ---- 发布时间来源 ----")
    for source, count in sorted((stats.get("pub_date_source") or {}).items(), key=lambda kv: -kv[1]):
        lines.append(f"    {source:<22}: {count}")
    lines.append(f"  拉黑表规模             : {stats.get('blacklist_size')} 条")
    lines.append("=" * 72)
    print("\n".join(lines), file=sys.stderr)

    if not write_file:
        return None
    out_dir = Path(log_dir) if log_dir else Path(obs.get("log_dir") or "output/guard_logs")
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"freshness_{datetime.now().strftime('%Y%m%d')}.jsonl"
    record = dict(stats)
    record["stage"] = stage
    record["logged_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return log_path


def assert_no_stale_in_output(
    candidates: Iterable[Dict[str, Any]],
    cutoff_days: int = DEFAULT_HARD_CUTOFF_DAYS,
) -> None:
    """
    # [GUARD-PUB_DATE-v1] 出口断言，禁止删除或绕过
    # 规则：产出清单中不得存在 pub_date 为 NULL 或超 cutoff 天的候选

    L3 运行时熔断：在写盘前对最终候选再断言一次，防止过闸后被其他步骤重新注入。
    """
    bad: List[str] = []
    for row in candidates:
        pub = row.get("publish_time")
        age = row.get("age_days")
        if _is_null_token(pub):
            bad.append(f"NULL pub_date: {row.get('video_url')}")
        elif isinstance(age, int) and age > cutoff_days:
            bad.append(f"stale {age}d > {cutoff_days}d: {row.get('video_url')}")
    if bad:
        raise AssertionError(
            "[GUARD-PUB_DATE-v1] 出口断言失败，产出中存在 NULL / 超期候选：\n  - "
            + "\n  - ".join(bad[:20])
        )


__all__ = [
    "GateResult",
    "DEFAULT_HARD_CUTOFF_DAYS",
    "DEFAULT_NULL_ACTION",
    "load_config",
    "load_blacklist",
    "extract_video_id",
    "decode_snowflake_date",
    "resolve_publish_date",
    "parse_time_window_days",
    "resolve_cutoff_days",
    "gate_candidate",
    "gate_candidates",
    "log_freshness_distribution",
    "assert_no_stale_in_output",
]
