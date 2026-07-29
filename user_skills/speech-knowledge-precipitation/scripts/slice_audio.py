#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slice_audio.py — 把任意音频切成 ≤ DEFAULT_SLICE_SECONDS 的片段。

输出：segments_manifest.json（每段含 index / start_seconds / end_seconds / path）。

L3 物理熔断：
- validate_input_audio: 输入文件不存在 / 非可读音频 → raise FileNotFoundError / ValueError
- validate_segment_seconds: 切片长度必须 60 ~ 1200 秒之间 → raise ValueError
- validate_total_duration_match: 切完后所有片段总时长应与原音频一致（差 ≤ 5s）→ raise RuntimeError
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Dict

DEFAULT_SLICE_SECONDS = 1080  # 18 minutes
MIN_SLICE_SECONDS = 60
MAX_SLICE_SECONDS = 1200  # 20 minutes


def validate_input_audio(input_path: Path) -> None:
    if not input_path.exists():
        raise FileNotFoundError(f"input audio not found: {input_path}")
    if not input_path.is_file():
        raise ValueError(f"input is not a file: {input_path}")
    if input_path.stat().st_size <= 0:
        raise ValueError(f"input audio is empty: {input_path}")


def validate_segment_seconds(seconds: int) -> None:
    if seconds < MIN_SLICE_SECONDS or seconds > MAX_SLICE_SECONDS:
        raise ValueError(
            f"segment seconds out of range [{MIN_SLICE_SECONDS}, {MAX_SLICE_SECONDS}]: {seconds}"
        )


def validate_total_duration_match(original: float, segments: List[Dict]) -> None:
    total = sum(s["end_seconds"] - s["start_seconds"] for s in segments)
    if abs(total - original) > 5.0:
        raise RuntimeError(
            f"segment total duration {total:.2f}s mismatches original {original:.2f}s"
        )


def get_audio_duration(input_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(input_path),
    ]
    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    return float(out.decode("utf-8").strip())


def slice_audio(input_path: Path, workdir: Path, segment_seconds: int) -> Dict:
    validate_input_audio(input_path)
    validate_segment_seconds(segment_seconds)
    workdir.mkdir(parents=True, exist_ok=True)

    duration = get_audio_duration(input_path)
    n = max(1, math.ceil(duration / segment_seconds))

    segments: List[Dict] = []
    for i in range(n):
        start = i * segment_seconds
        end = min(duration, start + segment_seconds)
        seg_path = workdir / f"seg_{i:03d}.wav"
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-ss",
            str(start),
            "-t",
            str(end - start),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-acodec",
            "pcm_s16le",
            str(seg_path),
        ]
        subprocess.check_call(cmd)
        if not seg_path.exists() or seg_path.stat().st_size <= 0:
            raise RuntimeError(f"failed to produce segment: {seg_path}")
        segments.append(
            {
                "index": i,
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "path": str(seg_path),
            }
        )

    validate_total_duration_match(duration, segments)

    manifest = {
        "input": str(input_path),
        "duration_seconds": round(duration, 3),
        "segment_seconds": segment_seconds,
        "segments": segments,
    }
    manifest_path = workdir / "segments_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="原始音频路径")
    parser.add_argument("--workdir", required=True, help="切片输出目录")
    parser.add_argument(
        "--segment-seconds",
        type=int,
        default=DEFAULT_SLICE_SECONDS,
        help=f"单段时长（秒），默认 {DEFAULT_SLICE_SECONDS}",
    )
    args = parser.parse_args()

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("ffmpeg / ffprobe not found in PATH; please install ffmpeg.")

    manifest = slice_audio(Path(args.input).resolve(), Path(args.workdir).resolve(), args.segment_seconds)
    print(json.dumps({"status": "OK", "n_segments": len(manifest["segments"]), "manifest_path": str(Path(args.workdir).resolve() / "segments_manifest.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
