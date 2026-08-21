#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书技能说明文档「三分区（Zone）策略」执行器 —— Forge Pipeline V5.23。

## 为什么需要分区

forge 每次发布都会更新飞书技能说明文档。此前的逻辑只有两种形态：**全量覆盖**
或**纯 append**，两者都缺失「哪些区域可覆盖、哪些必须保留」的语义：

* 全量覆盖 → 人工写的使用案例 / 踩坑记录 / 注意事项被机器抹平（沉淀资产丢失）；
* 纯 append → 版本号、触发词、接口契约永远堆叠旧版，读者不知道哪一份才是现行版本。

核心设计原则（两套事实来源，各管一段）：

* **飞书文档是「对人」的**：使用案例、踩坑、注意事项、人工补充背景是**人写的沉淀
  资产**，forge 一律不得覆盖。
* **`SKILL.md` 是「对机器」的 SSOT**：版本号、描述、触发词、接口契约由 `SKILL.md`
  渲染，飞书文档对应章节可以被安全覆盖。

## Zone 定义

| Zone | 内容 | forge 行为 |
|---|---|---|
| Overwrite Zone | 头部版本信息高亮框（版本号/描述/更新时间）、触发词、接口契约/参数说明 | 从 SKILL.md 重新渲染并覆盖 block |
| Preserve Zone  | 使用案例、踩坑记录、注意事项、人工补充背景 | 不 update / 不 delete，云端原样保留 |
| Append Zone    | 更新日志 Changelog / 版本历史 | 末尾追加新条目，不覆盖旧条目 |

Zone 边界由两个**固定标题锚点**划定（见 `PRESERVE_ANCHOR` / `APPEND_ANCHOR`）：

    <文档开头> ... Overwrite Zone ...
    ## 📝 使用案例 & 踩坑记录      <- Preserve Zone 开始
    ... Preserve Zone ...
    ## 📋 更新日志                <- Append Zone 开始
    ... Append Zone ... <文档结尾>

## 零信任断言（L3）

写入后必须 RAW 回读并断言：

1. 两个锚点标题在文档中**各出现恰好 1 次**（多出 = 重复补建，缺失 = 误删）；
2. Preserve Zone 写入前采样的既有正文文本，回读后**仍然存在**（存在性断言）。

任一不满足 -> `raise GuardrailViolation`。**禁止**降级为 WARNING 后继续宣称成功。

## 老文档兼容（安全降级）

存量文档（如本流水线自己的说明文档）没有这两个锚点标题。此时**绝不**猜测边界、
**绝不**删除既有正文，而是在文档末尾补建缺失的锚点章节（Preserve Zone 写入占位
提示 `[待补充使用案例]`），并在日志中显式告知降级发生（`degraded` 字段）。

本模块刻意自带一个极小的 `_run()` 子进程封装，不从 `register_skill.py` 反向 import，
以避免循环依赖并保证 zone 解析逻辑可被 `test_doc_zones.py` 离线单测。
"""

from __future__ import annotations

import re
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

# --- Zone 边界锚点（固定标题，不可随意改动：改了等于让所有存量文档一起降级） ---
PRESERVE_ANCHOR = "## 📝 使用案例 & 踩坑记录"
APPEND_ANCHOR = "## 📋 更新日志"
PRESERVE_ANCHOR_TITLE = PRESERVE_ANCHOR.lstrip("# ").strip()
APPEND_ANCHOR_TITLE = APPEND_ANCHOR.lstrip("# ").strip()

PRESERVE_PLACEHOLDER = "[待补充使用案例]"
PRESERVE_HINT = (
    "本章节属于 Preserve Zone：forge 流水线永不覆盖，请在此自由记录使用案例、"
    "踩坑与注意事项。"
)

ZONE_OVERWRITE = "overwrite"
ZONE_PRESERVE = "preserve"
ZONE_APPEND = "append"

# Preserve Zone 存在性断言的采样条数与最小样本长度
PRESERVE_SAMPLE_LIMIT = 8
PRESERVE_SAMPLE_MIN_LEN = 8


class GuardrailViolation(RuntimeError):
    """L3 运行时护栏熔断（与 register_skill.py 同语义，失败即 raise）。"""


# --------------------------------------------------------------------------- #
# 低层通道：一律走 lark-cli 原生通道（MCP-Only Law），禁止裸调 OpenAPI
# --------------------------------------------------------------------------- #
def _run(command: List[str], action: str) -> str:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise GuardrailViolation(
            f"{action} failed with exit code {result.returncode}\n"
            f"CMD: {' '.join(command)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout.strip()


def fetch_doc_xml(doc_url: str) -> str:
    """拉取带 block id 的文档 XML（`--detail with-ids`，唯一权威结构来源）。"""

    return _run(
        [
            "lark-cli", "docs", "+fetch",
            "--as", "user",
            "--doc", doc_url,
            "--doc-format", "xml",
            "--detail", "with-ids",
            "-q", ".data.document.content",
        ],
        "fetch doc xml with block ids",
    )


def doc_update(
    doc_url: str,
    command: str,
    *,
    block_id: str = "",
    content: str = "",
    doc_format: str = "markdown",
    action: str = "",
) -> str:
    args = [
        "lark-cli", "docs", "+update",
        "--as", "user",
        "--doc", doc_url,
        "--command", command,
    ]
    if block_id:
        args += ["--block-id", block_id]
    if content:
        args += ["--content", content, "--doc-format", doc_format]
    return _run(args, action or f"doc update ({command})")


# --------------------------------------------------------------------------- #
# 结构解析
# --------------------------------------------------------------------------- #
@dataclass
class DocBlock:
    """一个顶层正文块（`<ul>`/`<ol>` 自身无 id，故按其 `<li>` 子块展开）。"""

    block_id: str
    tag: str
    text: str
    heading_level: int = 0

    @property
    def is_h2(self) -> bool:
        return self.heading_level == 2


@dataclass
class ZoneMap:
    blocks: List[DocBlock] = field(default_factory=list)
    overwrite: List[DocBlock] = field(default_factory=list)
    preserve: List[DocBlock] = field(default_factory=list)
    append: List[DocBlock] = field(default_factory=list)
    preserve_anchor_id: str = ""
    append_anchor_id: str = ""
    degraded: str = ""

    @property
    def has_anchors(self) -> bool:
        return bool(self.preserve_anchor_id and self.append_anchor_id)

    def zone_of(self, block_id: str) -> str:
        for zone, blocks in (
            (ZONE_OVERWRITE, self.overwrite),
            (ZONE_PRESERVE, self.preserve),
            (ZONE_APPEND, self.append),
        ):
            if any(b.block_id == block_id for b in blocks):
                return zone
        return ""

    def preserve_samples(self) -> List[str]:
        """Preserve Zone 既有正文采样，用于写后「存在性断言」。"""

        samples: List[str] = []
        for block in self.preserve:
            text = (block.text or "").strip()
            if len(text) < PRESERVE_SAMPLE_MIN_LEN:
                continue
            if PRESERVE_PLACEHOLDER in text or text == PRESERVE_ANCHOR_TITLE:
                continue
            samples.append(text)
            if len(samples) >= PRESERVE_SAMPLE_LIMIT:
                break
        return samples


_HEADING_TAG_RE = re.compile(r"^h([1-9])$", re.I)


def _element_text(element: ET.Element) -> str:
    return "".join(element.itertext()).strip()


# 裸 `&` 会让严格 XML 解析直接崩。这在本场景里不是边缘情况而是**必然**：
#   1) Preserve 锚点标题本身就叫「📝 使用案例 & 踩坑记录」；
#   2) 附件 `href` 里的 query string 常带未转义 `&`。
# 因此解析前先把「不属于合法实体」的 `&` 补成 `&amp;`。
_BARE_AMP_RE = re.compile(r"&(?!#\d+;|#x[0-9A-Fa-f]+;|[A-Za-z][A-Za-z0-9]*;)")


def sanitize_doc_xml(doc_xml: str) -> str:
    return _BARE_AMP_RE.sub("&amp;", doc_xml or "")


def parse_doc_blocks(doc_xml: str) -> List[DocBlock]:
    """把文档 XML 解析成有序顶层块列表。

    `<title>` 不是正文块，跳过。`<ul>` / `<ol>` 本身没有 id（飞书里每个 `<li>` 才
    是独立 block），故展开其 `<li>` 子块。
    """

    try:
        root = ET.fromstring(f"<root>{sanitize_doc_xml(doc_xml)}</root>")
    except ET.ParseError as exc:
        raise GuardrailViolation(
            f"无法解析文档 XML，Zone 边界不可信，拒绝盲写。原因：{exc}"
        ) from exc

    blocks: List[DocBlock] = []
    for child in root:
        tag = (child.tag or "").lower()
        if tag == "title":
            continue
        if tag in {"ul", "ol"}:
            for item in child:
                item_id = item.get("id") or ""
                if item_id:
                    blocks.append(DocBlock(item_id, item.tag.lower(), _element_text(item)))
            continue
        block_id = child.get("id") or ""
        if not block_id:
            continue
        level_match = _HEADING_TAG_RE.match(tag)
        blocks.append(
            DocBlock(
                block_id=block_id,
                tag=tag,
                text=_element_text(child),
                heading_level=int(level_match.group(1)) if level_match else 0,
            )
        )
    return blocks


def _normalize_title(text: str) -> str:
    """标题归一化：去掉井号/空白差异，容忍全角空格与 `&` 前后空格写法。"""

    cleaned = (text or "").strip().lstrip("#").strip()
    cleaned = cleaned.replace("\u3000", " ")
    cleaned = re.sub(r"\s*&\s*", " & ", cleaned)
    return re.sub(r"\s+", " ", cleaned)


def _find_anchor(blocks: List[DocBlock], anchor_title: str) -> List[DocBlock]:
    target = _normalize_title(anchor_title)
    return [b for b in blocks if b.is_h2 and _normalize_title(b.text) == target]


def resolve_zones(blocks: List[DocBlock]) -> ZoneMap:
    """依据两个固定标题锚点切出三个 Zone。

    锚点缺失时**不猜测**边界：整篇归入 Overwrite Zone 是危险的（会覆盖人工沉淀），
    因此降级策略是「整篇视为不可动的 Preserve Zone」，仅允许在末尾补建锚点章节。
    """

    zone_map = ZoneMap(blocks=blocks)
    preserve_hits = _find_anchor(blocks, PRESERVE_ANCHOR_TITLE)
    append_hits = _find_anchor(blocks, APPEND_ANCHOR_TITLE)

    problems: List[str] = []
    if len(preserve_hits) != 1:
        problems.append(f"Preserve 锚点『{PRESERVE_ANCHOR_TITLE}』命中 {len(preserve_hits)} 次（期望 1）")
    if len(append_hits) != 1:
        problems.append(f"Append 锚点『{APPEND_ANCHOR_TITLE}』命中 {len(append_hits)} 次（期望 1）")

    if problems:
        # 安全降级：整篇当作 Preserve（只读），绝不误删既有正文。
        zone_map.preserve = list(blocks)
        zone_map.degraded = "；".join(problems)
        return zone_map

    preserve_anchor, append_anchor = preserve_hits[0], append_hits[0]
    ids = [b.block_id for b in blocks]
    p_idx, a_idx = ids.index(preserve_anchor.block_id), ids.index(append_anchor.block_id)
    if p_idx > a_idx:
        zone_map.preserve = list(blocks)
        zone_map.degraded = (
            f"锚点顺序异常：Preserve 锚点(idx={p_idx}) 位于 Append 锚点(idx={a_idx}) 之后"
        )
        return zone_map

    zone_map.overwrite = blocks[:p_idx]
    zone_map.preserve = blocks[p_idx:a_idx]
    zone_map.append = blocks[a_idx:]
    zone_map.preserve_anchor_id = preserve_anchor.block_id
    zone_map.append_anchor_id = append_anchor.block_id
    return zone_map


def fetch_zone_map(doc_url: str) -> ZoneMap:
    return resolve_zones(parse_doc_blocks(fetch_doc_xml(doc_url)))


# --------------------------------------------------------------------------- #
# SKILL.md（SSOT）渲染
# --------------------------------------------------------------------------- #
def read_skill_md(skill_dir: Path) -> str:
    path = Path(skill_dir) / "SKILL.md"
    if not path.exists():
        raise GuardrailViolation(f"SKILL.md 不存在，Overwrite Zone 无 SSOT 可渲染：{path}")
    return path.read_text(encoding="utf-8", errors="ignore")


def _strip_fenced_blocks(text: str) -> str:
    """剔除围栏代码块。

    真机踩坑：`SKILL.md` 里的**文档模板骨架**本身就写着 `## 🔑 触发词` 等标题，
    若不剔除围栏，会把模板占位符当成真正的触发词灌进飞书文档。
    """

    out, fence = [], ""
    for line in text.splitlines():
        stripped = line.lstrip()
        marker = re.match(r"^(`{3,}|~{3,})", stripped)
        if marker:
            token = marker.group(1)[0] * 3
            if not fence:
                fence = token
                continue
            if fence == token:
                fence = ""
                continue
        if not fence:
            out.append(line)
    return "\n".join(out)


def extract_skill_md_section(skill_md: str, title_keyword: str) -> str:
    """抽取 `## ...<keyword>...` 章节正文（不含标题行），围栏内的同名标题不计。"""

    body = _strip_fenced_blocks(skill_md)
    lines = body.splitlines()
    start = -1
    for idx, line in enumerate(lines):
        if re.match(r"^##\s+", line) and title_keyword in line:
            start = idx + 1
            break
    if start < 0:
        return ""
    collected: List[str] = []
    for line in lines[start:]:
        if re.match(r"^##\s+", line):
            break
        collected.append(line)
    return "\n".join(collected).strip()


def parse_skill_md_frontmatter(skill_md: str) -> Dict[str, str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", skill_md, re.S)
    if not match:
        return {}
    meta: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        kv = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line.strip())
        if kv:
            meta[kv.group(1).strip()] = kv.group(2).strip()
    return meta


AUTO_CALLOUT_MARK = "本区块由 forge 流水线自动生成"


def render_version_callout(skill_dir: Path, version: str, updated_at: str) -> str:
    """Overwrite Zone 头部版本信息高亮框（版本号 / 描述 / 更新时间）。"""

    meta = parse_skill_md_frontmatter(read_skill_md(skill_dir))
    name = meta.get("name") or Path(skill_dir).name
    desc = meta.get("description") or ""
    return (
        f"> 🤖 **{AUTO_CALLOUT_MARK}（Overwrite Zone），请勿手工编辑**\n"
        f"> **技能名称**：`{name}`\n"
        f"> **版本号**：{version}\n"
        f"> **描述**：{desc}\n"
        f"> **更新时间**：{updated_at}"
    )


# --------------------------------------------------------------------------- #
# 写入动作
# --------------------------------------------------------------------------- #
def build_new_doc_markdown(
    skill_dir: Path,
    version: str,
    updated_at: str,
    changelog_entry: str = "",
) -> str:
    """新建文档：按 Overwrite -> Preserve（占位）-> Append 顺序生成完整三分区结构。"""

    skill_md = read_skill_md(skill_dir)
    meta = parse_skill_md_frontmatter(skill_md)
    name = meta.get("name") or Path(skill_dir).name
    intro = extract_skill_md_section(skill_md, "技能简介") or meta.get("description", "")
    triggers = extract_skill_md_section(skill_md, "触发词")
    contract = extract_skill_md_section(skill_md, "核心架构") or extract_skill_md_section(
        skill_md, "接口契约"
    )

    parts = [
        f"# 【技能说明】{name} (V{version})",
        "",
        render_version_callout(skill_dir, version, updated_at),
        "",
        "## 📌 技能简介",
        "",
        intro or "（待补充）",
        "",
    ]
    if triggers:
        parts += ["## 🔑 触发词", "", triggers, ""]
    if contract:
        parts += ["## ⚙️ 接口契约 / 核心架构", "", contract, ""]
    parts += [
        PRESERVE_ANCHOR,
        "",
        f"> {PRESERVE_HINT}",
        "",
        PRESERVE_PLACEHOLDER,
        "",
        APPEND_ANCHOR,
        "",
        changelog_entry or f"- **V{version}**：首次发布。",
        "",
    ]
    return "\n".join(parts)


def ensure_zone_anchors(doc_url: str, zone_map: ZoneMap) -> Dict[str, Any]:
    """老文档兼容：末尾补建缺失的锚点章节。

    只做 append，**绝不** delete / 不重排既有正文；补建后必须显式告知降级发生。
    """

    report: Dict[str, Any] = {"created": [], "degraded": zone_map.degraded}
    if zone_map.has_anchors and not zone_map.degraded:
        return report

    titles = {_normalize_title(b.text) for b in zone_map.blocks if b.is_h2}
    chunks: List[str] = []
    if _normalize_title(PRESERVE_ANCHOR_TITLE) not in titles:
        chunks += [PRESERVE_ANCHOR, "", f"> {PRESERVE_HINT}", "", PRESERVE_PLACEHOLDER, ""]
        report["created"].append(PRESERVE_ANCHOR_TITLE)
    if _normalize_title(APPEND_ANCHOR_TITLE) not in titles:
        chunks += [APPEND_ANCHOR, "", "> 本章节只追加、不覆盖历史条目。", ""]
        report["created"].append(APPEND_ANCHOR_TITLE)

    if not chunks:
        # 锚点都在，但命中次数异常（重复）→ 属于人工介入范畴，不自动删除。
        print(
            "⚠️ [ZONE-DEGRADED] 锚点标题存在但边界不可信（可能重复），"
            f"本次不改写 Overwrite Zone。详情：{zone_map.degraded}"
        )
        return report

    print(
        "⚠️ [ZONE-DEGRADED] 检测到老文档缺失 Zone 锚点标题，安全降级："
        f"仅在文档末尾补建 {report['created']}，不改动任何既有正文。"
    )
    doc_update(
        doc_url,
        "append",
        content="\n".join(chunks),
        action="append missing zone anchor sections",
    )
    return report


def update_overwrite_zone(
    doc_url: str,
    zone_map: ZoneMap,
    skill_dir: Path,
    version: str,
    updated_at: str,
) -> Dict[str, Any]:
    """只改 Overwrite Zone 内的 block：版本信息框 + 触发词 + 接口契约。

    实现方式为「按 h2 章节整段重建」，且**所有待删除 block id 必须先通过
    `zone_map.zone_of()` 断言落在 Overwrite Zone**，否则 raise —— 这是防止误伤
    Preserve Zone 的最后一道闸门。
    """

    report: Dict[str, Any] = {"sections": [], "skipped": []}
    if not zone_map.has_anchors or zone_map.degraded:
        report["skipped"].append("zone anchors unavailable -> overwrite zone untouched")
        return report

    skill_md = read_skill_md(skill_dir)
    targets = [
        ("触发词", extract_skill_md_section(skill_md, "触发词")),
        (
            "接口契约",
            extract_skill_md_section(skill_md, "接口契约")
            or extract_skill_md_section(skill_md, "核心架构"),
        ),
    ]

    for keyword, rendered in targets:
        if not rendered:
            report["skipped"].append(f"{keyword}: SKILL.md 无对应章节，跳过覆盖")
            continue
        heading = next(
            (b for b in zone_map.overwrite if b.is_h2 and keyword in b.text), None
        )
        if heading is None:
            report["skipped"].append(f"{keyword}: Overwrite Zone 无对应标题，跳过")
            continue

        ids = [b.block_id for b in zone_map.overwrite]
        start = ids.index(heading.block_id) + 1
        body: List[DocBlock] = []
        for block in zone_map.overwrite[start:]:
            if block.is_h2:
                break
            body.append(block)

        for block in body:
            zone = zone_map.zone_of(block.block_id)
            if zone != ZONE_OVERWRITE:
                raise GuardrailViolation(
                    f"拒绝写入：block {block.block_id} 归属 Zone={zone or 'unknown'}，"
                    f"不在 Overwrite Zone，可能误伤人工沉淀内容。"
                )
        if body:
            doc_update(
                doc_url,
                "block_delete",
                block_id=",".join(b.block_id for b in body),
                action=f"clear overwrite-zone section: {keyword}",
            )
        doc_update(
            doc_url,
            "block_insert_after",
            block_id=heading.block_id,
            content=rendered,
            action=f"re-render overwrite-zone section: {keyword}",
        )
        report["sections"].append({"keyword": keyword, "replaced_blocks": len(body)})

    # 头部版本信息高亮框：幂等重建（先删旧的自动生成块，再插新的）
    callout = render_version_callout(skill_dir, version, updated_at)
    stale = [b for b in zone_map.overwrite if AUTO_CALLOUT_MARK in (b.text or "")]
    for block in stale:
        if zone_map.zone_of(block.block_id) != ZONE_OVERWRITE:
            raise GuardrailViolation(
                f"拒绝删除自动生成块 {block.block_id}：不在 Overwrite Zone。"
            )
    if stale:
        doc_update(
            doc_url,
            "block_delete",
            block_id=",".join(b.block_id for b in stale),
            action="clear stale auto-generated version callout",
        )
    stale_ids = {s.block_id for s in stale}
    anchor_id = next(
        (b.block_id for b in zone_map.overwrite if b.block_id not in stale_ids), ""
    )
    if anchor_id:
        doc_update(
            doc_url,
            "block_insert_after",
            block_id=anchor_id,
            content=callout,
            action="render overwrite-zone version callout",
        )
        report["sections"].append({"keyword": "版本信息高亮框", "replaced_blocks": len(stale)})
    return report


def append_changelog_entry(doc_url: str, entry: str) -> str:
    """Append Zone：末尾追加新版本条目，绝不覆盖旧条目。"""

    if not entry.strip():
        return ""
    return doc_update(
        doc_url, "append", content=entry, action="append changelog entry to append zone"
    )


# --------------------------------------------------------------------------- #
# L3 零信任断言
# --------------------------------------------------------------------------- #
def assert_zone_integrity(doc_url: str, preserve_samples: List[str]) -> Dict[str, Any]:
    """写后 RAW 回读断言：锚点各 1 次 + Preserve Zone 既有正文仍存在。"""

    doc_xml = fetch_doc_xml(doc_url)
    blocks = parse_doc_blocks(doc_xml)
    preserve_hits = _find_anchor(blocks, PRESERVE_ANCHOR_TITLE)
    append_hits = _find_anchor(blocks, APPEND_ANCHOR_TITLE)

    failures: List[str] = []
    if len(preserve_hits) != 1:
        failures.append(
            f"Preserve 锚点『{PRESERVE_ANCHOR_TITLE}』回读命中 {len(preserve_hits)} 次（期望恰好 1）"
        )
    if len(append_hits) != 1:
        failures.append(
            f"Append 锚点『{APPEND_ANCHOR_TITLE}』回读命中 {len(append_hits)} 次（期望恰好 1）"
        )

    haystack = re.sub(r"\s+", "", "".join(b.text or "" for b in blocks))
    missing = [s for s in preserve_samples if re.sub(r"\s+", "", s) not in haystack]
    if missing:
        failures.append(
            "Preserve Zone 存在性断言 FAILED，以下人工沉淀正文在回读结果中消失："
            + "；".join(repr(s[:60]) for s in missing)
        )

    if failures:
        raise GuardrailViolation(
            "【三分区断言失败】飞书说明文档 Zone 完整性回读未通过 -> "
            + " | ".join(failures)
            + f"（doc={doc_url}）"
        )

    result = {
        "preserve_anchor_count": len(preserve_hits),
        "append_anchor_count": len(append_hits),
        "preserve_samples_checked": len(preserve_samples),
        "blocks": len(blocks),
    }
    print(
        "✅ 三分区断言 PASS：锚点各出现 1 次；"
        f"Preserve Zone {len(preserve_samples)} 条人工正文样本全部健在。"
    )
    return result


# --------------------------------------------------------------------------- #
# 编排入口
# --------------------------------------------------------------------------- #
def sync_doc_zones(
    doc_url: str,
    skill_dir: Path,
    version: str,
    updated_at: str,
    changelog_entry: str = "",
) -> Dict[str, Any]:
    """三分区同步主入口（迭代已有文档）。

    顺序契约：读结构 -> 采样 Preserve -> 补建缺失锚点(降级) -> 覆盖 Overwrite ->
    追加 Changelog -> 等 2s -> RAW 回读断言。
    """

    print("🧭 三分区策略：读取云端文档结构（--detail with-ids）...")
    zone_map = fetch_zone_map(doc_url)
    samples = zone_map.preserve_samples()
    report: Dict[str, Any] = {
        "degraded": zone_map.degraded,
        "overwrite_blocks": len(zone_map.overwrite),
        "preserve_blocks": len(zone_map.preserve),
        "append_blocks": len(zone_map.append),
        "preserve_samples": len(samples),
    }
    print(
        f"   Zone 边界：overwrite={len(zone_map.overwrite)} "
        f"preserve={len(zone_map.preserve)} append={len(zone_map.append)}"
    )

    report["anchors"] = ensure_zone_anchors(doc_url, zone_map)
    if report["anchors"].get("created"):
        time.sleep(2)
        zone_map = fetch_zone_map(doc_url)
        samples = zone_map.preserve_samples()
        report["rescanned"] = True
        print(
            f"   补建后重扫：overwrite={len(zone_map.overwrite)} "
            f"preserve={len(zone_map.preserve)} append={len(zone_map.append)}"
        )

    report["overwrite"] = update_overwrite_zone(
        doc_url, zone_map, Path(skill_dir), version, updated_at
    )
    if changelog_entry:
        append_changelog_entry(doc_url, changelog_entry)
        report["changelog_appended"] = True

    time.sleep(2)
    report["assertion"] = assert_zone_integrity(doc_url, samples)
    return report


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="飞书技能说明文档三分区（Zone）同步")
    parser.add_argument("--doc", required=True, help="飞书说明文档 URL")
    parser.add_argument("--skill-dir", required=True, help="目标技能目录（SKILL.md 所在）")
    parser.add_argument("--version", default="", help="本次锻造版本号")
    parser.add_argument("--updated-at", default=time.strftime("%Y-%m-%d %H:%M"))
    parser.add_argument("--changelog-entry", default="", help="追加到 Append Zone 的条目")
    parser.add_argument("--verify-only", action="store_true", help="只做三分区回读断言")
    parser.add_argument("--dry-run", action="store_true", help="只读结构并打印 Zone 边界")
    args = parser.parse_args()

    if args.verify_only:
        zone_map = fetch_zone_map(args.doc)
        assert_zone_integrity(args.doc, zone_map.preserve_samples())
        return 0

    if args.dry_run:
        zone_map = fetch_zone_map(args.doc)
        print(json.dumps({
            "degraded": zone_map.degraded,
            "overwrite": [b.text[:40] for b in zone_map.overwrite],
            "preserve": [b.text[:40] for b in zone_map.preserve],
            "append": [b.text[:40] for b in zone_map.append],
        }, ensure_ascii=False, indent=2))
        return 0

    if not args.version:
        raise SystemExit("--version is required unless --dry-run/--verify-only")
    report = sync_doc_zones(
        args.doc, Path(args.skill_dir), args.version, args.updated_at, args.changelog_entry
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
