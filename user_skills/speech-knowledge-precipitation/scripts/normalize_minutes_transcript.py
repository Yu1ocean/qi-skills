#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""normalize_minutes_transcript.py — 将飞书妙记 transcript 规范化为本技能可消费的 transcript_full.md。

输入：妙记导出的 transcript 文本文件 + minute 元数据
输出：transcript_full.md + source_manifest.json

L3 物理熔断：
- validate_transcript_file: transcript 文件必须存在且非空
- validate_minutes_contract: input_source 必须为 minutes_transcript，minute_token/minute_url/source_audio_name 不得缺失
- validate_timestamp_presence: transcript 中必须存在可解析时间戳；若缺失则熔断，避免后续 L1-L4 失去秒级锚点
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

TIMESTAMP_RE = re.compile(r"\[?(?P<h>\d{1,2}):(?P<m>\d{2})(?::(?P<s>\d{2}))?\]?\s*[:：]?\s*")


def hhmmss_to_seconds(ts: str) -> int:
    parts = [int(x) for x in ts.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"invalid timestamp: {ts}")


def seconds_to_hhmmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def validate_transcript_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"minutes transcript not found: {path}")
    text = path.read_text(encoding="utf-8", errors="ignore")
    if len(text.strip()) < 50:
        raise ValueError(f"minutes transcript too short: {len(text.strip())} chars")
    return text


def validate_minutes_contract(args: argparse.Namespace) -> None:
    if args.input_source != "minutes_transcript":
        raise ValueError("input_source must be 'minutes_transcript'")
    required = {
        "minute_token": args.minute_token,
        "minute_url": args.minute_url,
        "source_audio_name": args.source_audio_name,
    }
    missing = [k for k, v in required.items() if not str(v or "").strip()]
    if missing:
        raise ValueError("missing required minutes metadata: " + ", ".join(missing))


def normalize_lines(raw: str) -> Tuple[List[str], List[int]]:
    lines: List[str] = []
    timestamps: List[int] = []
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = TIMESTAMP_RE.search(line)
        if not m:
            lines.append(line)
            continue
        h = int(m.group("h"))
        minute = int(m.group("m"))
        sec = int(m.group("s") or 0)
        total = h * 3600 + minute * 60 + sec if m.group("s") else h * 60 + minute
        normalized_ts = seconds_to_hhmmss(total)
        body = TIMESTAMP_RE.sub("", line, count=1).strip()
        lines.append(f"[{normalized_ts}] {body}" if body else f"[{normalized_ts}]")
        timestamps.append(total)
    return lines, timestamps


def validate_timestamp_presence(timestamps: List[int]) -> None:
    if not timestamps:
        raise RuntimeError("minutes transcript has no parseable timestamp; cannot preserve second-level anchors")


def build_transcript(normalized_lines: List[str], metadata: Dict) -> str:
    header = [
        "# 高精逐字稿（飞书妙记导入）",
        "",
        f"来源类型：`minutes_transcript` ｜ 源音频：`{metadata['source_audio_name']}`",
        f"妙记入口：[{metadata['minute_token']}]({metadata['minute_url']})",
    ]
    if metadata.get("note_id"):
        header.append(f"关联纪要 note_id：`{metadata['note_id']}`")
    header.extend(["", "## 片段 000 [00:00:00 → UNKNOWN]", ""])
    return "\n".join(header + normalized_lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-source", default="minutes_transcript")
    parser.add_argument("--transcript-path", required=True)
    parser.add_argument("--minute-token", required=True)
    parser.add_argument("--minute-url", required=True)
    parser.add_argument("--note-id", default="")
    parser.add_argument("--source-audio-name", required=True)
    parser.add_argument("--raw-summary", default="")
    parser.add_argument("--raw-todos", default="[]")
    parser.add_argument("--raw-chapters", default="[]")
    parser.add_argument("--output", required=True, help="规范化 transcript_full.md 输出路径")
    parser.add_argument("--manifest-output", required=True, help="source_manifest.json 输出路径")
    args = parser.parse_args()

    validate_minutes_contract(args)
    raw = validate_transcript_file(Path(args.transcript_path).resolve())
    normalized_lines, timestamps = normalize_lines(raw)
    validate_timestamp_presence(timestamps)

    metadata = {
        "source_type": "minutes_transcript",
        "transcript_path": str(Path(args.transcript_path).resolve()),
        "minute_token": args.minute_token,
        "minute_url": args.minute_url,
        "note_id": args.note_id or None,
        "source_audio_name": args.source_audio_name,
        "raw_summary_present": bool(args.raw_summary.strip()),
        "raw_todos_present": args.raw_todos.strip() not in ("", "[]"),
        "raw_chapters_present": args.raw_chapters.strip() not in ("", "[]"),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "n_lines": len(normalized_lines),
        "n_timestamps": len(timestamps),
        "first_timestamp": seconds_to_hhmmss(min(timestamps)),
        "last_timestamp": seconds_to_hhmmss(max(timestamps)),
    }

    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_transcript(normalized_lines, metadata), encoding="utf-8")

    manifest_out = Path(args.manifest_output).resolve()
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"status": "OK", "transcript_path": str(out), "manifest_path": str(manifest_out), "n_timestamps": len(timestamps)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
