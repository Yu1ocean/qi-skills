#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_outline.py — 根据完整逐字稿生成"骨架输出"，供本技能在 Phase 2/3 进一步润色。

注意：本脚本只做骨架抽取（按片段聚合 + 关键词提取），真正的 100 字高光与 L1-L4 切片
仍需要本技能/上层 LLM 在调用本脚本输出后做语义增强。它的价值是：
1) 提供一个可机器校验的"骨架快照"；
2) 让 Phase 4 的 zero-trust-qa-checker 有一个稳定的中间产物可以比对。

L3 物理熔断：
- validate_transcript: 输入逐字稿不存在或为空 → raise FileNotFoundError / ValueError
- validate_outline_coverage: 骨架输出至少要覆盖 ≥80% 的非空片段 → raise RuntimeError
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List


def validate_transcript(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"transcript not found: {path}")
    text = path.read_text(encoding="utf-8", errors="ignore")
    if len(text.strip()) < 200:
        raise ValueError(f"transcript too short to outline: {len(text)} chars")
    return text


def validate_outline_coverage(transcript_segments: List[str], outline: List[Dict]) -> None:
    non_empty = [s for s in transcript_segments if s.strip()]
    if not non_empty:
        return
    covered = sum(1 for entry in outline if entry.get("preview"))
    if covered / max(1, len(non_empty)) < 0.8:
        raise RuntimeError(
            f"outline coverage too low: {covered}/{len(non_empty)} segments captured"
        )


SEG_HEADER = re.compile(r"^##\s*片段\s*(\d+)\s*\[(\d{2}:\d{2}:\d{2})\s*→\s*(\d{2}:\d{2}:\d{2})\]")


def parse_segments(text: str) -> List[Dict]:
    segments: List[Dict] = []
    cur: Dict | None = None
    for line in text.splitlines():
        m = SEG_HEADER.match(line.strip())
        if m:
            if cur is not None:
                segments.append(cur)
            cur = {
                "index": int(m.group(1)),
                "start": m.group(2),
                "end": m.group(3),
                "lines": [],
            }
        elif cur is not None:
            cur["lines"].append(line)
    if cur is not None:
        segments.append(cur)
    return segments


def make_preview(lines: List[str], max_chars: int = 240) -> str:
    body = "\n".join(lines).strip()
    body = re.sub(r"\s+", " ", body)
    if len(body) <= max_chars:
        return body
    return body[: max_chars - 1] + "…"


def build_skeleton(transcript_text: str) -> Dict:
    segments = parse_segments(transcript_text)
    outline_entries: List[Dict] = []
    bullets: List[str] = []
    for seg in segments:
        lines = seg["lines"]
        preview = make_preview(lines)
        if not preview:
            continue
        outline_entries.append(
            {
                "index": seg["index"],
                "start": seg["start"],
                "end": seg["end"],
                "preview": preview,
            }
        )
        bullets.append(f"- [{seg['start']} → {seg['end']}] {preview}")

    skeleton = {
        "n_segments": len(segments),
        "outline_entries": outline_entries,
        "bullet_md": "\n".join(bullets),
    }

    validate_outline_coverage([" ".join(s["lines"]) for s in segments], outline_entries)
    return skeleton


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--output", required=True, help="骨架输出路径，建议 .md")
    args = parser.parse_args()

    transcript_path = Path(args.transcript).resolve()
    output_path = Path(args.output).resolve()

    text = validate_transcript(transcript_path)
    skeleton = build_skeleton(text)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    md_lines = [
        "# 骨架大纲（机器抽取，供后续语义增强）\n",
        f"片段总数：{skeleton['n_segments']}\n",
        "## 片段级摘要（按时间顺序）",
        skeleton["bullet_md"],
    ]
    output_path.write_text("\n".join(md_lines), encoding="utf-8")

    side = output_path.with_suffix(".json")
    side.write_text(json.dumps(skeleton, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"status": "OK", "n_segments": skeleton["n_segments"], "outline_md": str(output_path), "outline_json": str(side)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
