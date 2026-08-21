#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L3 运行时护栏：直播违规语义审核链路（v2.0）的物理熔断闸门。

设计原则：所有闸门在**副作用发生之前**调用，校验不通过一律 raise，
禁止返回 False 让调用方自行决定要不要继续——那等于把护栏变成建议。

v2.0 在 v1.x 六个 gate 之上新增五个语义链路 gate（配置合法性、语义命中契约、
证据逐字可回溯、启用类型声明、判定覆盖如实），全部旧 gate 原样保留。

可直接 import 使用，也可通过 CLI 单点校验：

    python3 scripts/audit_guard.py --self-test
    python3 scripts/audit_guard.py --check segment --seconds 75
    python3 scripts/audit_guard.py --check coverage --coverage-file coverage.md
    python3 scripts/audit_guard.py --check config --config-file references/audit_config.yaml
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# ---------------------------------------------------------------- Defaults ----

DEFAULT_SEGMENT_SECONDS = 60
DEFAULT_TIMESTAMP_FORMAT = "HH:MM:SS"
DEFAULT_NEIGHBOR_WINDOW = 3
DEFAULT_BATCH_SEGMENTS = 8
DEFAULT_RAW_SLEEP_SECONDS = 2

TIMESTAMP_RE = re.compile(r"^(\d{2,3}):([0-5]\d):([0-5]\d)$")

REQUIRED_HIT_FIELDS = ("timestamp", "text", "category", "risk_level")
ALLOWED_RISK_LEVELS = ("🔴 高", "🟡 中-高", "🟢 低")

# 覆盖说明必须自证的三件事：真实区间、总时长、尾段空 WAV 处置
COVERAGE_REQUIRED_MARKERS = ("实际有效覆盖", "总时长", "空 WAV")

# ---- v2.0 语义链路常量 ----

DEFAULT_AUDIT_CONFIG = Path(__file__).resolve().parent.parent / "references" / "audit_config.yaml"
DEFAULT_WINDOW_LINES = 24
DEFAULT_OVERLAP_LINES = 3
DEFAULT_JUDGE_PROGRESS = "temp_data/judge_progress.json"

# 注册总类数 / 默认禁用集合（v2.1：拍卖类按用户 2026-08-21 指令关闭）
REGISTERED_VIOLATION_TYPE_COUNT = 27
EXPECTED_DISABLED_TYPE_IDS = frozenset({"static_content", "auction_violation"})
EXPECTED_ENABLED_TYPE_COUNT = REGISTERED_VIOLATION_TYPE_COUNT - len(EXPECTED_DISABLED_TYPE_IDS)

CONFIG_REQUIRED_SECTIONS = ("meta", "judge_policy", "violation_types")
CONFIG_REQUIRED_TYPE_FIELDS = ("id", "name", "enabled", "modality", "judge_prompt", "risk_rubric")
SEMANTIC_RISK_LEVELS = ("高", "中", "低")
REQUIRED_SEMANTIC_HIT_FIELDS = (
    "violation_type",
    "timestamp",
    "evidence_text",
    "risk_level",
    "need_human_review",
    "judge_reason",
)


class AuditGuardError(RuntimeError):
    """任一护栏失败都抛这个异常，调用方不得吞掉。"""


# ------------------------------------------------------------------ Gates -----


def validate_segment_duration(seconds: float, max_seconds: int = DEFAULT_SEGMENT_SECONDS) -> float:
    """单段音频时长闸门：> 60 秒会同时引入 ASR 超时与时间戳漂移。"""
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        raise AuditGuardError(f"segment duration must be a number, got {type(seconds).__name__}")
    if seconds <= 0:
        raise AuditGuardError(f"segment duration must be positive, got {seconds}")
    if seconds > max_seconds:
        raise AuditGuardError(
            f"segment duration {seconds}s exceeds hard limit {max_seconds}s; "
            "split the audio before sending to ASR"
        )
    return float(seconds)


def parse_absolute_timestamp(value: str) -> int:
    """把 HH:MM:SS 绝对偏移解析成秒；格式不合法直接熔断。"""
    if not isinstance(value, str):
        raise AuditGuardError(f"timestamp must be str in {DEFAULT_TIMESTAMP_FORMAT}, got {value!r}")
    matched = TIMESTAMP_RE.match(value.strip())
    if not matched:
        raise AuditGuardError(
            f"timestamp {value!r} is not absolute {DEFAULT_TIMESTAMP_FORMAT} offset "
            "(relative in-segment offsets make hits untraceable)"
        )
    hours, minutes, seconds = (int(part) for part in matched.groups())
    return hours * 3600 + minutes * 60 + seconds


def validate_timestamp_absolute(timestamps: Sequence[str]) -> list[int]:
    """时间戳序列闸门：必须全部为绝对偏移且单调不倒退。"""
    if not timestamps:
        raise AuditGuardError("timestamp list is empty; nothing was transcribed")
    seconds_list: list[int] = []
    previous = -1
    for raw in timestamps:
        current = parse_absolute_timestamp(raw)
        if current < previous:
            raise AuditGuardError(
                f"timestamp {raw!r} goes backwards (previous={previous}s); "
                "likely per-segment relative offsets leaked into the transcript"
            )
        previous = current
        seconds_list.append(current)
    return seconds_list


def assert_raw_readback(expected: str, actual: str, *, where: str = "lark doc") -> None:
    """写后回读闸门：写入飞书后必须回读比对，退出码 0 不等于写成功。"""
    if actual is None:
        raise AuditGuardError(f"RAW readback from {where} returned None; write is NOT verified")
    expected_norm = "".join(str(expected).split())
    actual_norm = "".join(str(actual).split())
    if not expected_norm:
        raise AuditGuardError("expected payload is empty; refuse to claim a verified write")
    if expected_norm not in actual_norm:
        raise AuditGuardError(
            f"RAW readback mismatch at {where}: expected payload not found in readback "
            f"(expected {len(expected_norm)} chars, got {len(actual_norm)} chars)"
        )


def validate_coverage_report(text: str) -> str:
    """覆盖说明闸门：必须显式写出真实区间、总时长与尾段空 WAV 处置。"""
    if not isinstance(text, str) or not text.strip():
        raise AuditGuardError("coverage report is empty; coverage gaps must be stated explicitly")
    missing = [marker for marker in COVERAGE_REQUIRED_MARKERS if marker not in text]
    if missing:
        raise AuditGuardError(
            f"coverage report missing required statements: {missing}; "
            "silent coverage gaps are treated as fabricated full coverage"
        )
    return text


def validate_hit_row(row: Mapping[str, Any]) -> Mapping[str, Any]:
    """命中行闸门：四要素缺一即不可取证。"""
    if not isinstance(row, Mapping):
        raise AuditGuardError(f"hit row must be a mapping, got {type(row).__name__}")
    missing = [field for field in REQUIRED_HIT_FIELDS if not str(row.get(field, "")).strip()]
    if missing:
        raise AuditGuardError(f"hit row missing required fields {missing}: {dict(row)!r}")
    parse_absolute_timestamp(str(row["timestamp"]))
    if str(row["risk_level"]) not in ALLOWED_RISK_LEVELS:
        raise AuditGuardError(
            f"risk_level {row['risk_level']!r} not in {ALLOWED_RISK_LEVELS}"
        )
    return row


def validate_hit_rows(rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    for row in rows:
        validate_hit_row(row)
        count += 1
    if count == 0:
        raise AuditGuardError("hit table is empty; scanner produced no evidence rows")
    return count


def validate_progress_checkpoint(checkpoint: Mapping[str, Any]) -> Mapping[str, Any]:
    """断点闸门：缺 revision_id 或已覆盖区间时续跑必然重跑/漏跑。"""
    if not isinstance(checkpoint, Mapping):
        raise AuditGuardError(f"checkpoint must be a mapping, got {type(checkpoint).__name__}")
    revision = str(checkpoint.get("revision_id", "")).strip()
    if not revision:
        raise AuditGuardError("checkpoint missing revision_id; resume position is unverifiable")
    covered = checkpoint.get("covered_range")
    if not isinstance(covered, (list, tuple)) or len(covered) != 2:
        raise AuditGuardError(
            "checkpoint.covered_range must be a [start, end] pair of HH:MM:SS offsets"
        )
    start = parse_absolute_timestamp(str(covered[0]))
    end = parse_absolute_timestamp(str(covered[1]))
    if end < start:
        raise AuditGuardError(f"checkpoint covered_range end {covered[1]} precedes start {covered[0]}")
    if not checkpoint.get("raw_verified", False):
        raise AuditGuardError(
            "checkpoint.raw_verified is false; only RAW-verified batches may advance the resume point"
        )
    return checkpoint


# ------------------------------------------------- v2.0 语义链路 gate（新增） ---


def _normalize_for_trace(value: Any) -> str:
    """归一化：NFKC 统一全半角 + 去全部空白 + 小写。与判定器保持同一口径。"""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return "".join(text.split()).lower()


def validate_audit_config(config: Any) -> Mapping[str, Any]:
    """配置闸门：审核口径是全链路的合同，配置烂了后面全是幻觉。

    熔断条件：缺 meta/judge_policy/violation_types；类型缺必填字段；id 重复；
    risk_rubric 键不在 高/中/低。
    """
    if isinstance(config, (str, Path)):
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover
            raise AuditGuardError("PyYAML required to validate audit config") from exc
        config_path = Path(config)
        if not config_path.exists():
            raise AuditGuardError(f"audit config not found: {config_path}")
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, Mapping):
        raise AuditGuardError(f"audit config must be a mapping, got {type(config).__name__}")

    missing = [section for section in CONFIG_REQUIRED_SECTIONS if section not in config]
    if missing:
        raise AuditGuardError(f"audit config missing sections {missing}")

    types = config["violation_types"]
    if not isinstance(types, list) or not types:
        raise AuditGuardError("audit config violation_types must be a non-empty list")

    seen: set[str] = set()
    for item in types:
        if not isinstance(item, Mapping):
            raise AuditGuardError(f"violation type must be a mapping, got {type(item).__name__}")
        lacking = [field for field in CONFIG_REQUIRED_TYPE_FIELDS if field not in item]
        if lacking:
            raise AuditGuardError(
                f"violation type {item.get('id', '<no-id>')!r} missing fields {lacking}"
            )
        type_id = str(item["id"]).strip()
        if not type_id:
            raise AuditGuardError("violation type has empty id")
        if type_id in seen:
            raise AuditGuardError(f"duplicated violation type id: {type_id}")
        seen.add(type_id)
        rubric = item["risk_rubric"]
        if not isinstance(rubric, Mapping) or not rubric:
            raise AuditGuardError(f"{type_id}.risk_rubric must be a non-empty mapping")
        illegal = [str(key) for key in rubric if str(key) not in SEMANTIC_RISK_LEVELS]
        if illegal:
            raise AuditGuardError(
                f"{type_id}.risk_rubric has illegal level keys {illegal}, allowed {SEMANTIC_RISK_LEVELS}"
            )
    return config


def validate_semantic_hit_row(row: Mapping[str, Any]) -> Mapping[str, Any]:
    """语义命中行闸门：六要素缺一即无法取证（少了 judge_reason 就无法复核判定依据）。"""
    if not isinstance(row, Mapping):
        raise AuditGuardError(f"semantic hit row must be a mapping, got {type(row).__name__}")
    missing = [
        field
        for field in REQUIRED_SEMANTIC_HIT_FIELDS
        if field not in row or (field != "need_human_review" and not str(row.get(field, "")).strip())
    ]
    if missing:
        raise AuditGuardError(f"semantic hit row missing required fields {missing}: {dict(row)!r}")
    parse_absolute_timestamp(str(row["timestamp"]))
    if str(row["risk_level"]) not in SEMANTIC_RISK_LEVELS:
        raise AuditGuardError(
            f"risk_level {row['risk_level']!r} not in {SEMANTIC_RISK_LEVELS}"
        )
    if not isinstance(row["need_human_review"], bool):
        raise AuditGuardError(
            f"need_human_review must be a bool, got {row['need_human_review']!r}"
        )
    return row


def validate_evidence_traceable(evidence_text: str, transcript: str) -> str:
    """反幻觉闸门：证据原文必须能在逐字稿中逐字定位。

    「大意对得上」正是幻觉的典型形态——模型把没说过的话总结成像是说过的。
    归一化只抹掉空白与全半角差异，不允许任何语义改写通过。
    """
    if not isinstance(evidence_text, str) or not evidence_text.strip():
        raise AuditGuardError("evidence_text is empty; a hit without evidence is not evidence")
    if not isinstance(transcript, str) or not transcript.strip():
        raise AuditGuardError("transcript is empty; cannot verify evidence traceability")
    needle = _normalize_for_trace(evidence_text)
    haystack = _normalize_for_trace(transcript)
    if needle not in haystack:
        raise AuditGuardError(
            f"evidence not verbatim in transcript (hallucination suspected): {evidence_text[:80]!r}"
        )
    return evidence_text


def validate_enabled_types_declared(
    reported_types: Iterable[str], enabled_types: Iterable[str]
) -> set[str]:
    """启用类型闸门：报告里出现没开的类型 = 审了个不存在的口径。"""
    enabled = {str(item).strip() for item in enabled_types if str(item).strip()}
    if not enabled:
        raise AuditGuardError("enabled type set is empty; nothing was configured for this run")
    reported = {str(item).strip() for item in reported_types if str(item).strip()}
    undeclared = sorted(reported - enabled)
    if undeclared:
        raise AuditGuardError(
            f"report contains violation types not enabled in this run: {undeclared}; "
            f"enabled={sorted(enabled)}"
        )
    return reported


def validate_judge_coverage(summary: Mapping[str, Any], *, claim_complete: bool = True) -> Mapping[str, Any]:
    """判定覆盖闸门：有未判定窗口却宣称全量完成，等于伪造覆盖范围。"""
    if not isinstance(summary, Mapping):
        raise AuditGuardError(f"summary must be a mapping, got {type(summary).__name__}")
    if "total_windows" not in summary:
        raise AuditGuardError("summary missing total_windows; coverage is unverifiable")
    unjudged = summary.get("unjudged_windows") or []
    if not isinstance(unjudged, (list, tuple)):
        raise AuditGuardError("summary.unjudged_windows must be a list")
    if unjudged and claim_complete:
        raise AuditGuardError(
            f"{len(unjudged)} window(s) unjudged {list(unjudged)[:10]} but full coverage was claimed; "
            "state them explicitly in the coverage section instead"
        )
    judged = int(summary.get("judged_windows", 0) or 0)
    total = int(summary["total_windows"])
    if judged + len(unjudged) < total:
        raise AuditGuardError(
            f"window accounting mismatch: judged={judged} + unjudged={len(unjudged)} < total={total}; "
            "some windows silently vanished"
        )
    return summary


# ---------------------------------------------------------------- Self test ---


def _expect_raise(label: str, func, *args, **kwargs) -> None:
    try:
        func(*args, **kwargs)
    except AuditGuardError:
        print(f"  [ok] {label} -> blocked as expected")
        return
    raise SystemExit(f"  [FAIL] {label} -> guard did NOT fire")


def _expect_pass(label: str, func, *args, **kwargs) -> None:
    func(*args, **kwargs)
    print(f"  [ok] {label} -> passed")


def self_test() -> int:
    print("audit_guard self-test")

    print(" segment duration")
    _expect_pass("60s segment", validate_segment_duration, 60)
    _expect_raise("75s segment", validate_segment_duration, 75)
    _expect_raise("zero segment", validate_segment_duration, 0)

    print(" absolute timestamp")
    _expect_pass("monotonic absolute", validate_timestamp_absolute, ["00:00:00", "00:01:00", "20:16:10"])
    _expect_raise("relative mm:ss", validate_timestamp_absolute, ["01:00"])
    _expect_raise("backwards", validate_timestamp_absolute, ["00:05:00", "00:01:00"])

    print(" raw readback")
    _expect_pass("payload present", assert_raw_readback, "14K stamp", "…原文 14K stamp 命中…")
    _expect_raise("payload absent", assert_raw_readback, "14K stamp", "文档里什么都没有")
    _expect_raise("readback None", assert_raw_readback, "14K stamp", None)

    print(" coverage report")
    good_coverage = "实际有效覆盖 00:00:00–20:16:10，总时长 20:19:52，尾段 3 分钟抽出空 WAV，判定为回放无有效音频。"
    _expect_pass("full statement", validate_coverage_report, good_coverage)
    _expect_raise("missing markers", validate_coverage_report, "已全部覆盖完成")

    print(" hit rows")
    good_row = {
        "timestamp": "01:23:45",
        "text": "this is real gold plated with 14K stamp",
        "category": "材质造假",
        "risk_level": "🔴 高",
    }
    _expect_pass("四要素齐备", validate_hit_row, good_row)
    _expect_raise("缺原文", validate_hit_row, {**good_row, "text": ""})
    _expect_raise("非法等级", validate_hit_row, {**good_row, "risk_level": "严重"})
    _expect_raise("空命中表", validate_hit_rows, [])

    print(" progress checkpoint")
    good_ckpt = {
        "revision_id": "rev-1024",
        "covered_range": ["00:00:00", "02:40:00"],
        "raw_verified": True,
    }
    _expect_pass("完整断点", validate_progress_checkpoint, good_ckpt)
    _expect_raise("缺 revision_id", validate_progress_checkpoint, {**good_ckpt, "revision_id": ""})
    _expect_raise("未 RAW 校验", validate_progress_checkpoint, {**good_ckpt, "raw_verified": False})

    # ------------------------------------------------ v2.0 语义链路 gate ----

    print(" audit config (v2.0)")
    _expect_pass("真实 audit_config.yaml", validate_audit_config, DEFAULT_AUDIT_CONFIG)
    real_config = validate_audit_config(DEFAULT_AUDIT_CONFIG)
    if len(real_config["violation_types"]) != REGISTERED_VIOLATION_TYPE_COUNT:
        raise SystemExit(
            f"  [FAIL] audit_config.yaml should register {REGISTERED_VIOLATION_TYPE_COUNT} types, "
            f"got {len(real_config['violation_types'])}"
        )
    print(f"  [ok] audit_config.yaml registers {REGISTERED_VIOLATION_TYPE_COUNT} violation types")
    disabled_ids = {
        item["id"] for item in real_config["violation_types"] if not item.get("enabled")
    }
    if disabled_ids != set(EXPECTED_DISABLED_TYPE_IDS):
        raise SystemExit(
            f"  [FAIL] disabled type set drifted: expected {sorted(EXPECTED_DISABLED_TYPE_IDS)}, "
            f"got {sorted(disabled_ids)}"
        )
    enabled_count = len(real_config["violation_types"]) - len(disabled_ids)
    if enabled_count != EXPECTED_ENABLED_TYPE_COUNT:
        raise SystemExit(
            f"  [FAIL] enabled type count drifted: expected {EXPECTED_ENABLED_TYPE_COUNT}, "
            f"got {enabled_count}"
        )
    print(
        f"  [ok] enabled={enabled_count}/{REGISTERED_VIOLATION_TYPE_COUNT}, "
        f"disabled={sorted(disabled_ids)}"
    )
    good_type = {
        "id": "material_fraud",
        "name": "材质造假宣称",
        "enabled": True,
        "modality": "audio",
        "judge_prompt": "判断材质宣称是否成立",
        "risk_rubric": {"高": "h", "中": "m", "低": "l"},
    }
    good_config = {"meta": {}, "judge_policy": {}, "violation_types": [good_type]}
    _expect_pass("最小合法配置", validate_audit_config, good_config)
    _expect_raise("缺 judge_policy", validate_audit_config, {"meta": {}, "violation_types": [good_type]})
    _expect_raise(
        "类型缺 judge_prompt",
        validate_audit_config,
        {**good_config, "violation_types": [{k: v for k, v in good_type.items() if k != "judge_prompt"}]},
    )
    _expect_raise(
        "id 重复",
        validate_audit_config,
        {**good_config, "violation_types": [good_type, dict(good_type)]},
    )
    _expect_raise(
        "risk_rubric 键非法",
        validate_audit_config,
        {**good_config, "violation_types": [{**good_type, "risk_rubric": {"严重": "x"}}]},
    )

    print(" semantic hit rows")
    good_semantic = {
        "violation_type": "counterfeit",
        "timestamp": "00:12:34",
        "evidence_text": "same quality as the authentic one, 1:1 replica",
        "risk_level": "高",
        "need_human_review": True,
        "judge_reason": "明确的 1:1 仿冒表述",
    }
    _expect_pass("六要素齐备", validate_semantic_hit_row, good_semantic)
    _expect_raise("缺 judge_reason", validate_semantic_hit_row, {**good_semantic, "judge_reason": ""})
    _expect_raise("缺证据原文", validate_semantic_hit_row, {**good_semantic, "evidence_text": "  "})
    _expect_raise("非法等级", validate_semantic_hit_row, {**good_semantic, "risk_level": "🔴 高"})
    _expect_raise(
        "need_human_review 非 bool",
        validate_semantic_hit_row,
        {**good_semantic, "need_human_review": "true"},
    )

    print(" evidence traceability (anti-hallucination)")
    transcript = "[00:12:34] same quality as the authentic one, 1:1 replica\n[00:12:40] link in bio"
    _expect_pass(
        "逐字证据",
        validate_evidence_traceable,
        "same quality as the authentic one, 1:1 replica",
        transcript,
    )
    _expect_pass(
        "仅空白/全角差异",
        validate_evidence_traceable,
        "  same  quality as the authentic one，1:1 replica ".replace("，", ", "),
        transcript,
    )
    _expect_raise(
        "改写过的证据",
        validate_evidence_traceable,
        "主播说这个和正品一模一样，是 1:1 的",
        transcript,
    )
    _expect_raise("空证据", validate_evidence_traceable, "", transcript)

    print(" enabled types declared")
    _expect_pass(
        "全部已启用",
        validate_enabled_types_declared,
        ["material_fraud", "counterfeit"],
        ["material_fraud", "counterfeit", "misleading_pricing"],
    )
    _expect_raise(
        "报告出现未启用类型",
        validate_enabled_types_declared,
        ["material_fraud", "static_content"],
        ["material_fraud", "counterfeit"],
    )

    print(" judge coverage")
    _expect_pass(
        "全量判定完成",
        validate_judge_coverage,
        {"total_windows": 10, "judged_windows": 10, "unjudged_windows": []},
    )
    _expect_raise(
        "有未判定窗口却宣称完成",
        validate_judge_coverage,
        {"total_windows": 10, "judged_windows": 8, "unjudged_windows": [3, 7]},
    )
    _expect_pass(
        "未判定窗口已显式列出",
        validate_judge_coverage,
        {"total_windows": 10, "judged_windows": 8, "unjudged_windows": [3, 7]},
        claim_complete=False,
    )
    _expect_raise(
        "窗口账目对不上",
        validate_judge_coverage,
        {"total_windows": 10, "judged_windows": 5, "unjudged_windows": []},
    )

    print("SELF-TEST PASSED")
    return 0


# ---------------------------------------------------------------------- CLI ---


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="live audit runtime guards (L3)")
    parser.add_argument("--self-test", action="store_true", help="run built-in guard assertions")
    parser.add_argument(
        "--check",
        choices=[
            "segment",
            "timestamps",
            "coverage",
            "hits",
            "checkpoint",
            "config",
            "semantic-hits",
            "evidence",
            "enabled-types",
            "judge-coverage",
        ],
        help="run a single gate",
    )
    parser.add_argument("--seconds", type=float, help="segment duration for --check segment")
    parser.add_argument("--timestamps", help="comma separated HH:MM:SS list for --check timestamps")
    parser.add_argument("--coverage-file", help="coverage report file for --check coverage")
    parser.add_argument("--hits-json", help="hit rows JSON file for --check hits / semantic-hits")
    parser.add_argument("--checkpoint-json", help="checkpoint JSON file for --check checkpoint")
    parser.add_argument(
        "--config-file",
        default=str(DEFAULT_AUDIT_CONFIG),
        help="audit_config.yaml for --check config",
    )
    parser.add_argument("--evidence", help="evidence text for --check evidence")
    parser.add_argument("--transcript-file", help="transcript file for --check evidence")
    parser.add_argument("--reported-types", help="comma separated types for --check enabled-types")
    parser.add_argument("--enabled-types", help="comma separated enabled types")
    parser.add_argument("--summary-json", help="judge summary JSON for --check judge-coverage")
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="--check judge-coverage: 未判定窗口已在覆盖说明中显式列出时使用",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.check:
        parser.error("either --self-test or --check is required")

    if args.check == "segment":
        if args.seconds is None:
            parser.error("--check segment requires --seconds")
        validate_segment_duration(args.seconds)
        print(f"OK segment {args.seconds}s <= {DEFAULT_SEGMENT_SECONDS}s")
    elif args.check == "timestamps":
        if not args.timestamps:
            parser.error("--check timestamps requires --timestamps")
        stamps = [part.strip() for part in args.timestamps.split(",") if part.strip()]
        validate_timestamp_absolute(stamps)
        print(f"OK {len(stamps)} absolute timestamps")
    elif args.check == "coverage":
        if not args.coverage_file:
            parser.error("--check coverage requires --coverage-file")
        validate_coverage_report(Path(args.coverage_file).read_text(encoding="utf-8"))
        print("OK coverage report states real range / total duration / empty-WAV tail")
    elif args.check == "hits":
        if not args.hits_json:
            parser.error("--check hits requires --hits-json")
        rows = json.loads(Path(args.hits_json).read_text(encoding="utf-8"))
        if isinstance(rows, dict):
            rows = rows.get("hits", [])
        count = validate_hit_rows(rows)
        print(f"OK {count} evidence rows")
    elif args.check == "checkpoint":
        if not args.checkpoint_json:
            parser.error("--check checkpoint requires --checkpoint-json")
        validate_progress_checkpoint(
            json.loads(Path(args.checkpoint_json).read_text(encoding="utf-8"))
        )
        print("OK checkpoint has revision_id + RAW-verified covered range")
    elif args.check == "config":
        config = validate_audit_config(args.config_file)
        enabled = [item["id"] for item in config["violation_types"] if item.get("enabled")]
        print(
            f"OK audit config v{config['meta'].get('config_version')}: "
            f"{len(config['violation_types'])} types registered, {len(enabled)} enabled"
        )
    elif args.check == "semantic-hits":
        if not args.hits_json:
            parser.error("--check semantic-hits requires --hits-json")
        payload = json.loads(Path(args.hits_json).read_text(encoding="utf-8"))
        rows = payload.get("hits", []) if isinstance(payload, dict) else payload
        for row in rows:
            validate_semantic_hit_row(row)
        print(f"OK {len(rows)} semantic hit rows carry all six required fields")
    elif args.check == "evidence":
        if not args.evidence or not args.transcript_file:
            parser.error("--check evidence requires --evidence and --transcript-file")
        validate_evidence_traceable(
            args.evidence, Path(args.transcript_file).read_text(encoding="utf-8")
        )
        print("OK evidence is verbatim traceable in transcript")
    elif args.check == "enabled-types":
        if not args.reported_types or not args.enabled_types:
            parser.error("--check enabled-types requires --reported-types and --enabled-types")
        validate_enabled_types_declared(
            args.reported_types.split(","), args.enabled_types.split(",")
        )
        print("OK every reported violation type was enabled in this run")
    elif args.check == "judge-coverage":
        if not args.summary_json:
            parser.error("--check judge-coverage requires --summary-json")
        payload = json.loads(Path(args.summary_json).read_text(encoding="utf-8"))
        summary = payload.get("summary", payload)
        validate_judge_coverage(summary, claim_complete=not args.allow_incomplete)
        print("OK judge coverage accounting is consistent")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AuditGuardError as exc:
        print(f"GUARD BLOCKED: {exc}", file=sys.stderr)
        sys.exit(2)
