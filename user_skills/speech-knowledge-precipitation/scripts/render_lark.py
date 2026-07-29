#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_lark.py — 把 highlight + outline + qa_report + transcript 组装成 .lark.md。

强制保证最终 .lark.md 满足"输出契约"：
100 字高光 + 全局大纲 + 多主题 L1-L4 + 秒级时间戳 + 空降链接 + 高精逐字稿附录

L3 物理熔断：
- validate_inputs: 任一必填输入不存在或空 → raise FileNotFoundError / ValueError
- validate_output_contract: 渲染完成后，文档内必须同时包含全部六个 section 标识 → raise RuntimeError
- validate_highlight_length: 100 字高光长度需 ≤ 220 字符且非空 → raise ValueError
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List

CONTRACT_SECTIONS = [
    "📌 核心高光",
    "📚 全局大纲",
    "🧭 多主题深度切片",
    "🛡️ 零信任质检报告",
    "📖 高精逐字稿",
]


def validate_inputs(paths: Dict[str, Path]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, p in paths.items():
        if k == "qa_report" and (p is None or not p.exists()):
            out[k] = "（本次未提供 QA 报告）"
            continue
        if not p.exists():
            raise FileNotFoundError(f"missing required input '{k}': {p}")
        text = p.read_text(encoding="utf-8", errors="ignore")
        if not text.strip():
            raise ValueError(f"input '{k}' is empty: {p}")
        out[k] = text
    return out


def validate_highlight_length(highlight: str) -> None:
    body = highlight.strip()
    if not body:
        raise ValueError("highlight is empty")
    plain = re.sub(r"\s+", "", body)
    if len(plain) > 220:
        raise ValueError(f"highlight too long: {len(plain)} chars (>220)")


def validate_output_contract(rendered: str) -> None:
    missing = [s for s in CONTRACT_SECTIONS if s not in rendered]
    if missing:
        raise RuntimeError(
            "output contract violated: missing sections — " + ", ".join(missing)
        )


def render(
    title: str,
    highlight: str,
    outline: str,
    slices: str,
    qa_report: str,
    transcript: str,
    audio_basename: str,
    source_manifest: str | None = None,
) -> str:
    source_section = ""
    if source_manifest:
        try:
            manifest = json.loads(source_manifest)
        except json.JSONDecodeError:
            manifest = {}
        if manifest.get("source_type") == "minutes_transcript":
            minute_url = manifest.get("minute_url", "")
            minute_token = manifest.get("minute_token", "")
            source_audio = manifest.get("source_audio_name", audio_basename)
            source_section = (
                "## 🔗 原始来源\n\n"
                f"- 来源类型：`minutes_transcript`\n"
                f"- 源音频：`{source_audio}`\n"
                f"- 妙记入口：[{minute_token}]({minute_url})\n\n"
            )

    head = (
        source_section
        + f"## 📌 核心高光（100 字）\n\n{highlight.strip()}\n\n"
        + "## 📚 全局大纲\n\n" + outline.strip() + "\n\n"
        + "## 🧭 多主题深度切片（L1-L4 + 秒级时间戳）\n\n" + slices.strip() + "\n\n"
        + "## 🛡️ 零信任质检报告\n\n" + qa_report.strip() + "\n\n"
        + f"## 📖 高精逐字稿（附录，全量｜源文件：`{audio_basename}`）\n\n" + transcript.strip() + "\n"
    )
    return head


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True, help="文档主题标题（不再写入正文 H1，避免 mcp 自动加标题后重复）")
    parser.add_argument("--highlight", required=True, help="100 字高光 .md 路径")
    parser.add_argument("--outline", required=True, help="全局大纲 .md 路径")
    parser.add_argument("--slices", required=True, help="L1-L4 切片 .md 路径")
    parser.add_argument("--transcript", required=True, help="高精逐字稿 .md 路径")
    parser.add_argument("--qa-report", required=False, default=None, help="QA 报告 .md 路径，可选")
    parser.add_argument("--audio-basename", required=True, help="音频源文件名，用于附录标头")
    parser.add_argument("--source-manifest", required=False, default=None, help="source_manifest.json 路径；minutes_transcript 模式用于写入原始来源互引")
    parser.add_argument("--output", required=True, help="输出 .lark.md 路径")
    args = parser.parse_args()

    paths = {
        "highlight": Path(args.highlight).resolve(),
        "outline": Path(args.outline).resolve(),
        "slices": Path(args.slices).resolve(),
        "transcript": Path(args.transcript).resolve(),
        "qa_report": Path(args.qa_report).resolve() if args.qa_report else None,
    }
    contents = validate_inputs(paths)
    validate_highlight_length(contents["highlight"])

    source_manifest = None
    if args.source_manifest:
        source_manifest_path = Path(args.source_manifest).resolve()
        if not source_manifest_path.exists():
            raise FileNotFoundError(f"source_manifest not found: {source_manifest_path}")
        source_manifest = source_manifest_path.read_text(encoding="utf-8", errors="ignore")

    rendered = render(
        title=args.title,
        highlight=contents["highlight"],
        outline=contents["outline"],
        slices=contents["slices"],
        qa_report=contents.get("qa_report", "（本次未提供 QA 报告）"),
        transcript=contents["transcript"],
        audio_basename=args.audio_basename,
        source_manifest=source_manifest,
    )
    validate_output_contract(rendered)

    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")

    print(json.dumps({"status": "OK", "output": str(out), "n_chars": len(rendered)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
