#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Transcribe/translate a subset of chunked audio files.

Designed to run in small batches to avoid long-running bash timeouts.

Usage:
  python3 tools/transcribe_chunk_range.py '{
    "audio_dir": "output/weibo/audio_chunks_2m",
    "output_dir": "output/weibo/transcripts_2m",
    "start": 15,
    "end": 19,
    "task": "...",
    "skip_existing": true
  }'

start/end are chunk indices (based on chunk_XXX.mp3).
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path


def _extract_result_text(stdout: str) -> str:
    s = stdout.strip()
    if not s.startswith("AimeToolResultText("):
        return s
    m = re.search(r"result=(?P<lit>'(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\")\)?$", s, re.S)
    if not m:
        return s
    lit = m.group("lit")
    try:
        return ast.literal_eval(lit)
    except Exception:
        return s


def _call_analyze_audio(audio_path: str, task: str) -> tuple[int, str, str]:
    payload = {"path": audio_path, "task": task}
    proc = subprocess.run(
        [
            sys.executable,
            "inner_skills/analyze_media/analyze_audio.py",
            json.dumps(payload, ensure_ascii=False),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return proc.returncode, _extract_result_text(proc.stdout), proc.stdout


def main() -> int:
    if len(sys.argv) != 2:
        print("ERR: expects 1 JSON arg", file=sys.stderr)
        return 2

    cfg = json.loads(sys.argv[1])
    audio_dir = Path(cfg["audio_dir"]).resolve()
    output_dir = Path(cfg["output_dir"]).resolve()
    start = int(cfg["start"])
    end = int(cfg["end"])
    task = cfg["task"]
    skip_existing = bool(cfg.get("skip_existing", True))

    output_dir.mkdir(parents=True, exist_ok=True)

    for idx in range(start, end + 1):
        audio_path = audio_dir / f"chunk_{idx:03d}.mp3"
        if not audio_path.exists():
            print(f"MISSING: {audio_path.name}")
            continue

        out_path = output_dir / f"chunk_{idx:03d}.md"
        if skip_existing and out_path.exists() and out_path.stat().st_size > 0:
            print(f"SKIP: {audio_path.name}")
            continue

        rc, text, raw = _call_analyze_audio(str(audio_path), task)
        if rc != 0:
            # Persist raw output for debugging while keeping stdout short
            debug_path = output_dir / f"chunk_{idx:03d}.raw.txt"
            debug_path.write_text(raw, encoding="utf-8")
            print(f"FAIL(rc={rc}): {audio_path.name} (raw->{debug_path.name})")
            continue

        out_path.write_text(text, encoding="utf-8")
        print(f"OK: {audio_path.name} -> {out_path.name} ({len(text)} chars)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
