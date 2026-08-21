#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Concatenate chunk transcript markdown files into a single TXT file.

We avoid using shell `cat` to prevent large stdout and to keep the process robust.

Usage:
  python3 tools/concat_transcripts.py '{
    "input_dir": "output/weibo/transcripts_2m",
    "pattern": "chunk_*.md",
    "output_path": "output/weibo/transcript_bilingual_full.txt",
    "title": "微博视频 1034:5286442608558180 录音逐字稿（英文+中文）"
  }'
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("ERR: expects exactly 1 JSON arg", file=sys.stderr)
        return 2

    cfg = json.loads(sys.argv[1])
    input_dir = Path(cfg["input_dir"]).resolve()
    pattern = cfg.get("pattern", "chunk_*.md")
    output_path = Path(cfg["output_path"]).resolve()
    title = cfg.get("title", "Transcript")

    files = sorted(input_dir.glob(pattern))
    if not files:
        print(f"ERR: no files match {pattern} under {input_dir}", file=sys.stderr)
        return 3

    # Natural sort by chunk index when present
    def key(p: Path):
        m = re.search(r"chunk_(\d+)", p.stem)
        return int(m.group(1)) if m else 10**9

    files = sorted(files, key=key)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with output_path.open("w", encoding="utf-8") as w:
        w.write(title + "\n")
        w.write("Generated at: " + now + "\n")
        w.write("\n" + "=" * 80 + "\n\n")

        for p in files:
            w.write(f"\n\n--- {p.name} ---\n\n")
            w.write(p.read_text(encoding="utf-8").strip())
            w.write("\n")

    print(f"OK: {len(files)} files -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
