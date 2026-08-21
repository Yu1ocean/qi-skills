#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线自检：三分区（Zone）边界解析与断言逻辑（V5.23）。

只测纯函数，不触网、不写飞书 —— 这样 zone 边界这类「一错就误删人工沉淀」的逻辑
可以在每次改动后零成本回归。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from doc_zone_manager import (  # noqa: E402
    APPEND_ANCHOR_TITLE,
    PRESERVE_ANCHOR_TITLE,
    ZONE_OVERWRITE,
    ZONE_PRESERVE,
    GuardrailViolation,
    extract_skill_md_section,
    parse_doc_blocks,
    parse_skill_md_frontmatter,
    resolve_zones,
)

FULL_DOC = (
    '<title id="T">【技能说明】demo (V1.0)</title>'
    '<h1 id="b1">【技能说明】demo (V1.0)</h1>'
    '<h2 id="b2">🔑 触发词</h2>'
    '<ul><li id="b3">demo-trigger</li><li id="b4">forge</li></ul>'
    f'<h2 id="b5">{PRESERVE_ANCHOR_TITLE}</h2>'
    '<p id="b6">踩坑：跨 Sheet COUNTIFS 非空条件会失效，必须反向计法。</p>'
    f'<h2 id="b7">{APPEND_ANCHOR_TITLE}</h2>'
    '<p id="b8">- V1.0：首次发布。</p>'
)

LEGACY_DOC = (
    '<title id="T">老文档</title>'
    '<h1 id="c1">老文档</h1>'
    '<h2 id="c2">📌 技能简介</h2>'
    '<p id="c3">人工写的宝贵背景说明。</p>'
)

SKILL_MD = """---
name: demo-skill
version: 1.2
description: 演示技能
---

# demo

## 🔑 触发词

- 核心关键词：
  - demo

## 📖 案例实录

正文模板骨架如下：

```markdown
## 🔑 触发词
- <这是模板占位符，不该被抽取>
```

## 更新日志

- V1.2：xxx
"""

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✅ {name}")
    else:
        failures.append(f"{name} :: {detail}")
        print(f"  ❌ {name} :: {detail}")


print("[1] 正常三分区文档的边界切分")
blocks = parse_doc_blocks(FULL_DOC)
zm = resolve_zones(blocks)
check("title 不计入正文块", all(b.block_id != "T" for b in blocks), [b.block_id for b in blocks])
check("ul 展开为 li 块", {"b3", "b4"} <= {b.block_id for b in blocks})
check("无降级", zm.degraded == "", zm.degraded)
check("overwrite = b1..b4", [b.block_id for b in zm.overwrite] == ["b1", "b2", "b3", "b4"],
      [b.block_id for b in zm.overwrite])
check("preserve = b5,b6", [b.block_id for b in zm.preserve] == ["b5", "b6"],
      [b.block_id for b in zm.preserve])
check("append = b7,b8", [b.block_id for b in zm.append] == ["b7", "b8"],
      [b.block_id for b in zm.append])
check("zone_of(b6)=preserve", zm.zone_of("b6") == ZONE_PRESERVE, zm.zone_of("b6"))
check("zone_of(b3)=overwrite", zm.zone_of("b3") == ZONE_OVERWRITE, zm.zone_of("b3"))
check("preserve 采样含人工正文", any("踩坑" in s for s in zm.preserve_samples()),
      zm.preserve_samples())
check("preserve 采样排除锚点标题",
      all(s != PRESERVE_ANCHOR_TITLE for s in zm.preserve_samples()))

print("[2] 老文档（无锚点）必须安全降级为全 Preserve")
zm2 = resolve_zones(parse_doc_blocks(LEGACY_DOC))
check("标记降级", bool(zm2.degraded), zm2.degraded)
check("overwrite 为空（不覆盖任何正文）", zm2.overwrite == [], zm2.overwrite)
check("整篇归入 preserve", len(zm2.preserve) == 3, len(zm2.preserve))
check("has_anchors=False", zm2.has_anchors is False)

print("[3] 锚点重复 / 顺序颠倒 必须降级")
dup = FULL_DOC + f'<h2 id="d1">{PRESERVE_ANCHOR_TITLE}</h2>'
check("重复锚点降级", bool(resolve_zones(parse_doc_blocks(dup)).degraded))
reversed_doc = (
    '<h1 id="e1">x</h1>'
    f'<h2 id="e2">{APPEND_ANCHOR_TITLE}</h2>'
    f'<h2 id="e3">{PRESERVE_ANCHOR_TITLE}</h2>'
)
check("顺序颠倒降级", bool(resolve_zones(parse_doc_blocks(reversed_doc)).degraded))

print("[4] 标题归一化容忍 & 前后空格差异")
variant = FULL_DOC.replace(PRESERVE_ANCHOR_TITLE, "📝 使用案例  &  踩坑记录")
check("空格变体仍可识别", resolve_zones(parse_doc_blocks(variant)).degraded == "",
      resolve_zones(parse_doc_blocks(variant)).degraded)

print("[4b] 裸 & 与 &amp; 两种形态都必须可解析（锚点标题自带 &）")
escaped = FULL_DOC.replace(" & ", " &amp; ")
check("&amp; 形态可解析且不降级", resolve_zones(parse_doc_blocks(escaped)).degraded == "",
      resolve_zones(parse_doc_blocks(escaped)).degraded)
amp_href = FULL_DOC + '<p id="f1">see http://x/y?a=1&b=2 tail</p>'
check("href 裸 & 不致崩", len(parse_doc_blocks(amp_href)) == len(parse_doc_blocks(FULL_DOC)) + 1)

print("[5] 非法 XML 必须 raise 而非静默")
try:
    parse_doc_blocks("<h1 id='x'>unclosed")
    check("非法 XML raise", False, "no raise")
except GuardrailViolation:
    check("非法 XML raise", True)

print("[6] SKILL.md SSOT 解析（围栏内模板占位符必须被剔除）")
meta = parse_skill_md_frontmatter(SKILL_MD)
check("frontmatter version", meta.get("version") == "1.2", meta)
check("frontmatter name", meta.get("name") == "demo-skill", meta)
trig = extract_skill_md_section(SKILL_MD, "触发词")
check("抽到真实触发词", "demo" in trig, trig)
check("未抽到模板占位符", "模板占位符" not in trig, trig)
check("缺失章节返回空", extract_skill_md_section(SKILL_MD, "不存在的章节") == "")

print()
if failures:
    print(f"❌ FAILED: {len(failures)} case(s)")
    for f in failures:
        print(f"   - {f}")
    raise SystemExit(1)
print("✅ ALL ZONE TESTS PASSED")
