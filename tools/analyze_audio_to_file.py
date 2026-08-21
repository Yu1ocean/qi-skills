#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run analyze_audio MCP tool and persist the full result to a file.

Why this exists:
- The interactive tool output shown in chat may be truncated.
- We still need the full transcript/translation for downstream packaging and Feishu upload.

Usage:
  python3 tools/analyze_audio_to_file.py '{
    "audio_path": "output/weibo/audio_chunks_2m/chunk_000.mp3",
    "task": "...",
    "output_path": "output/weibo/transcripts/chunk_000.md"
  }'

This script prints only a short status line to stdout.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _extract_result_text(stdout: str) -> str:
    """Extract result text from the tool's printed representation.

    Expected patterns:
      AimeToolResultText(result='...')
      AimeToolResultText(result="...")

    If not matched, fall back to the raw stdout.
    """

    # Normalize trailing newlines
    s = stdout.strip()

    # Fast path: if the tool already outputs plain text
    if not s.startswith("AimeToolResultText("):
        return s

    # Extract the python string literal after `result=`.
    # We rely on ast.literal_eval to unescape sequences (\n, \\', etc.).
    m = re.search(r"result=(?P<lit>'(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\")\)?$", s, re.S)
    if not m:
        return s

    lit = m.group("lit")
    try:
        return ast.literal_eval(lit)
    except Exception:
        return s


def main() -> int:
    if len(sys.argv) != 2:
        print("ERR: expects exactly 1 JSON argument", file=sys.stderr)
        return 2

    payload = json.loads(sys.argv[1])
    audio_path = payload["audio_path"]
    task = payload["task"]
    output_path = payload["output_path"]

    cmd_payload = {"path": audio_path, "task": task}

    # Call the MCP wrapper script.
    proc = subprocess.run(
        [
            sys.executable,
            "inner_skills/analyze_media/analyze_audio.py",
            json.dumps(cmd_payload, ensure_ascii=False),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )

    result_text = _extract_result_text(proc.stdout)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result_text, encoding="utf-8")

    # Keep stdout minimal to avoid chat truncation.
    status = "OK" if proc.returncode == 0 else f"RC={proc.returncode}"
    print(f"{status}: wrote {out} ({len(result_text)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
