#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L3 运行时护栏：直播材质造假 / 品牌授权审核链路的物理熔断闸门。

设计原则：所有闸门在**副作用发生之前**调用，校验不通过一律 raise，
禁止返回 False 让调用方自行决定要不要继续——那等于把护栏变成建议。

可直接 import 使用，也可通过 CLI 单点校验：

    python3 scripts/audit_guard.py --self-test
    python3 scripts/audit_guard.py --check segment --seconds 75
    python3 scripts/audit_guard.py --check coverage --coverage-file coverage.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
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

    print("SELF-TEST PASSED")
    return 0


# ---------------------------------------------------------------------- CLI ---


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="live audit runtime guards (L3)")
    parser.add_argument("--self-test", action="store_true", help="run built-in guard assertions")
    parser.add_argument(
        "--check",
        choices=["segment", "timestamps", "coverage", "hits", "checkpoint"],
        help="run a single gate",
    )
    parser.add_argument("--seconds", type=float, help="segment duration for --check segment")
    parser.add_argument("--timestamps", help="comma separated HH:MM:SS list for --check timestamps")
    parser.add_argument("--coverage-file", help="coverage report file for --check coverage")
    parser.add_argument("--hits-json", help="hit rows JSON file for --check hits")
    parser.add_argument("--checkpoint-json", help="checkpoint JSON file for --check checkpoint")
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
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AuditGuardError as exc:
        print(f"GUARD BLOCKED: {exc}", file=sys.stderr)
        sys.exit(2)
