#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch transcription/translation for segmented audio files.

It calls `inner_skills/analyze_media/analyze_audio.py` for each chunk, writes per-chunk
markdown files, and also appends to a combined markdown file.

This avoids chat output truncation by keeping stdout minimal.
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


def _call_analyze_audio(audio_path: str, task: str) -> tuple[int, str]:
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
    return proc.returncode, _extract_result_text(proc.stdout)


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "ERR: expects exactly 1 JSON argument: {audio_dir, output_dir, combined_path, task}",
            file=sys.stderr,
        )
        return 2

    cfg = json.loads(sys.argv[1])
    audio_dir = Path(cfg["audio_dir"]).resolve()
    output_dir = Path(cfg["output_dir"]).resolve()
    combined_path = Path(cfg["combined_path"]).resolve()
    task = cfg["task"]

    output_dir.mkdir(parents=True, exist_ok=True)
    combined_path.parent.mkdir(parents=True, exist_ok=True)

    chunk_files = sorted(audio_dir.glob("*.mp3"))
    if not chunk_files:
        print(f"ERR: no mp3 files under {audio_dir}", file=sys.stderr)
        return 3

    reset_combined = bool(cfg.get("reset_combined", True))
    skip_existing = bool(cfg.get("skip_existing", True))

    if reset_combined:
        combined_path.write_text("", encoding="utf-8")

    for i, f in enumerate(chunk_files):
        chunk_out = output_dir / (f.stem + ".md")

        if skip_existing and chunk_out.exists() and chunk_out.stat().st_size > 0:
            text = chunk_out.read_text(encoding="utf-8")
            rc = 0
            status = "SKIP"
        else:
            rc, text = _call_analyze_audio(str(f), task)
            chunk_out.write_text(text, encoding="utf-8")
            status = "OK" if rc == 0 else f"RC={rc}"

        with combined_path.open("a", encoding="utf-8") as w:
            w.write(f"\n\n---\n\n## Chunk {i:03d} ({f.name})\n\n")
            w.write(text)

        print(f"{status}: {f.name} -> {chunk_out.name} ({len(text)} chars)")

    print(f"DONE: combined -> {combined_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
