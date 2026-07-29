#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""transcribe_segments.py — 串行调用可配置的 analyze_audio 工具转写所有切片。

输入：segments_manifest.json
输出：transcript_full.md（带 HH:MM:SS 全局时间戳的合并稿）+ transcribe_report.json

L3 物理熔断：
- validate_manifest_shape: manifest 必须包含 segments 列表 → raise ValueError
- validate_segment_file: 每段音频文件必须存在 → raise FileNotFoundError
- validate_no_silent_drop: 失败片段必须以 [GAP: ...] 显式插入，函数返回前会断言 → raise RuntimeError
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_SECONDS = 2
DEFAULT_ASR_TASK_PROMPT = (
    "逐字转写音频内容，标注每个发言段落的开始时间（秒）。中文输出。"
    "保留完整原文，不要总结，不要二次润色。"
    "格式示例：[00:00:05] 这里是发言内容……"
)


def validate_manifest_shape(manifest: Dict) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a dict")
    if "segments" not in manifest or not isinstance(manifest["segments"], list):
        raise ValueError("manifest.segments must be a list")
    if not manifest["segments"]:
        raise ValueError("manifest.segments is empty")


def validate_segment_file(seg: Dict) -> None:
    p = Path(seg.get("path", ""))
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"segment file missing: {p}")
    if p.stat().st_size <= 0:
        raise FileNotFoundError(f"segment file empty: {p}")


def validate_no_silent_drop(report: Dict) -> None:
    failed = report.get("failed_segments", [])
    transcript_path = report.get("transcript_path")
    if failed and transcript_path:
        text = Path(transcript_path).read_text(encoding="utf-8", errors="ignore")
        for seg in failed:
            tag = f"GAP: {seg['start_hhmmss']} - {seg['end_hhmmss']}"
            if tag not in text:
                raise RuntimeError(
                    f"silent drop detected: failed segment {seg['index']} not marked in transcript ({tag})"
                )


def hhmmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


_AIME_RESULT_RE = re.compile(r"AimeToolResultText\(result=(['\"])(.*)\1\s*\)\s*$", re.DOTALL)


def _strip_aime_wrapper(stdout: str) -> str:
    """Strip the AimeToolResultText(result='...') wrapper if present, and unescape \\n.

    The byted_aime_sdk wraps results in AimeToolResultText(result='...') with python-style
    string escapes (e.g. \\n, \\u4f60). We must use ast.literal_eval to safely decode it,
    because plain `bytes.decode('unicode_escape')` interprets each byte as latin-1 first
    and corrupts UTF-8 multi-byte sequences (mojibake).
    """
    import ast as _ast

    text = stdout.strip()
    m = _AIME_RESULT_RE.match(text)
    if m:
        # Re-evaluate the quoted python string literal; ast.literal_eval handles \n/\uXXXX
        # without breaking UTF-8 characters.
        quoted = text[m.start(1):]  # 从开始引号开始
        # Trim trailing ')' and any whitespace after the closing quote
        quoted = quoted.rstrip().rstrip(")").rstrip()
        try:
            inner = _ast.literal_eval(quoted)
            if isinstance(inner, str):
                return inner.strip()
        except Exception:  # pragma: no cover — fallback
            pass
        # Fallback: take m.group(2) as-is and only normalize \n
        return m.group(2).replace("\\n", "\n").strip()
    return text


_RANGE_HEADER_RE = re.compile(
    r"^\s*\[?\s*\d{1,2}:\d{1,2}(?::\d{1,2})?\s*[-–~]\s*\d{1,2}:\d{1,2}(?::\d{1,2})?\s*\]?\s*[:：]?\s*"
)


def _strip_asr_preamble(text: str) -> str:
    """Remove redundant '[00:00:00-00:18:00]' style range markers and meta-prefaces from the ASR output."""
    lines = text.splitlines()
    cleaned: List[str] = []
    skipped_meta = False
    for ln in lines:
        if not skipped_meta and _RANGE_HEADER_RE.match(ln):
            # drop the '[00:00:00-00:18:00]' header line if present at top
            continue
        if not skipped_meta and re.match(r"^\s*这是一份完整的逐字转写内容", ln):
            # drop the model's own meta preface
            skipped_meta = True
            continue
        cleaned.append(ln)
    return "\n".join(cleaned).strip()


def call_analyze_audio(workspace_root: Path, audio_path: Path, task: str) -> str:
    payload = {"path": str(audio_path), "task": task}
    analyze_audio_script = os.environ.get("AIME_ANALYZE_AUDIO_SCRIPT", "analyze_audio.py")
    cmd = [
        "python3",
        analyze_audio_script,
        json.dumps(payload, ensure_ascii=False),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"analyze_audio failed (rc={proc.returncode}): {proc.stderr[:2000]}"
        )
    raw = _strip_aime_wrapper(proc.stdout)
    cleaned = _strip_asr_preamble(raw)
    if len(cleaned.strip()) < 20:
        raise RuntimeError(
            f"analyze_audio returned suspiciously short text (len={len(cleaned)}): {cleaned[:200]!r}"
        )
    return cleaned


def shift_local_timestamps(local_text: str, offset_seconds: float) -> str:
    """Convert any [MM:SS] / [HH:MM:SS] / [SS.xxx] markers in local segment to global offsets."""

    def repl(m: re.Match) -> str:
        ts = m.group(1)
        parts = [int(x) for x in ts.replace(".", ":").split(":") if x.strip().isdigit()]
        if len(parts) == 3:
            local_sec = parts[0] * 3600 + parts[1] * 60 + parts[2]
        elif len(parts) == 2:
            local_sec = parts[0] * 60 + parts[1]
        elif len(parts) == 1:
            local_sec = parts[0]
        else:
            return m.group(0)
        global_sec = local_sec + offset_seconds
        return f"[{hhmmss(global_sec)}]"

    pattern = re.compile(r"\[(\d{1,2}(?::\d{1,2}){0,2}(?:\.\d+)?)\]")
    return pattern.sub(repl, local_text)


def transcribe(manifest_path: Path, output_path: Path, workspace_root: Path, max_retries: int) -> Dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest_shape(manifest)

    successful: List[Tuple[Dict, str]] = []
    failed: List[Dict] = []

    for seg in manifest["segments"]:
        validate_segment_file(seg)
        idx = seg["index"]
        offset = seg["start_seconds"]
        end = seg["end_seconds"]

        last_err = None
        text = None
        for attempt in range(1, max_retries + 1):
            try:
                text = call_analyze_audio(workspace_root, Path(seg["path"]), DEFAULT_ASR_TASK_PROMPT)
                break
            except Exception as e:  # noqa: BLE001 — we wrap to retry
                last_err = e
                wait = DEFAULT_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                print(
                    f"[transcribe_segments] seg#{idx} attempt {attempt}/{max_retries} failed: {e}; sleep {wait}s",
                    file=sys.stderr,
                )
                time.sleep(wait)
        if text is None:
            failed.append(
                {
                    "index": idx,
                    "start_seconds": offset,
                    "end_seconds": end,
                    "start_hhmmss": hhmmss(offset),
                    "end_hhmmss": hhmmss(end),
                    "error": str(last_err)[:500] if last_err else "unknown",
                }
            )
        else:
            shifted = shift_local_timestamps(text, offset)
            successful.append((seg, shifted))

    # Compose merged transcript: by segment index order, with GAP markers for failed.
    lines: List[str] = []
    lines.append(f"# 高精逐字稿（自动合并）\n")
    lines.append(
        f"音频源：`{manifest.get('input')}` ｜ 总时长：{hhmmss(manifest.get('duration_seconds', 0))}\n"
    )

    success_by_idx = {s[0]["index"]: s[1] for s in successful}
    failed_by_idx = {f["index"]: f for f in failed}
    for seg in manifest["segments"]:
        idx = seg["index"]
        start = hhmmss(seg["start_seconds"])
        end = hhmmss(seg["end_seconds"])
        lines.append(f"\n## 片段 {idx:03d} [{start} → {end}]\n")
        if idx in success_by_idx:
            lines.append(success_by_idx[idx].strip())
        else:
            f = failed_by_idx[idx]
            lines.append(
                f"[GAP: {f['start_hhmmss']} - {f['end_hhmmss']}] ASR 失败 ×{max_retries}，错误：`{f['error']}`"
            )
        lines.append("\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")

    report = {
        "n_segments": len(manifest["segments"]),
        "n_success": len(successful),
        "n_failed": len(failed),
        "failed_segments": failed,
        "transcript_path": str(output_path),
    }
    validate_no_silent_drop(report)
    report_path = output_path.with_name("transcribe_report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, help="segments_manifest.json 路径")
    parser.add_argument("--output", required=True, help="合并稿输出路径，例如 transcript_full.md")
    parser.add_argument(
        "--workspace-root",
        default=os.environ.get("IRIS_WORKSPACE_PATH") or "/workspace/iris_19f7e856-22a9-491e-b611-5e5c09e9e419",
        help="工作区根目录（默认从 IRIS_WORKSPACE_PATH 读取）",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"单段最大重试次数（默认 {DEFAULT_MAX_RETRIES}）",
    )
    args = parser.parse_args()

    report = transcribe(
        Path(args.manifest).resolve(),
        Path(args.output).resolve(),
        Path(args.workspace_root).resolve(),
        args.max_retries,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["n_failed"] == 0 else 0  # 失败不直接退出非零；调用方依据 report 决定


if __name__ == "__main__":
    raise SystemExit(main())
