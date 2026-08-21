#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wiki 归档护栏脚本（闭环归档 SOP）

目标：把 info-miner 的“生成飞书文档后必须归档”固化成可执行、可验证、可熔断的低自由度脚本。

L2 Defaults（默认值契约）
- DEFAULT_ARCHIVE_REQUIRED = True
- DEFAULT_CATEGORY_POLICY = "explicit_first_then_infer"
- DEFAULT_ARCHIVE_HEADING = "## 📂 已归档资产"
- DEFAULT_TABLE_HEADERS = ["序号", "归档日期", "资产名称", "来源/主题", "访问链接"]
- DEFAULT_VERIFY_AFTER_WRITE = True
- DEFAULT_LARK_DOMAIN = "https://bytedance.larkoffice.com"

L3 Runtime Gate（物理熔断）
- validate_archive_request(): 归档前断言
- build_archive_patch(): 表格存在/不存在两条分支均做结构化约束
- archive_to_wiki(): 走飞书 MCP 下载 → 更新 → 回读验收，任一步失败即 raise

CLI:
    python3 scripts/wiki_archive_guard.py --selftest
    python3 scripts/wiki_archive_guard.py prepare --markdown-file /abs/path/doc.lark.md --category "AI/Agent" --asset-name "资产" --source-topic "主题" --access-link "https://bytedance.larkoffice.com/docx/xxx"
    python3 scripts/wiki_archive_guard.py archive --category "AI/Agent" --asset-name "资产" --source-topic "主题" --access-link "https://bytedance.larkoffice.com/docx/xxx"
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


# ---------- Defaults ----------
DEFAULT_ARCHIVE_REQUIRED: bool = True
DEFAULT_CATEGORY_POLICY: str = "explicit_first_then_infer"
DEFAULT_ARCHIVE_HEADING: str = "## 📂 已归档资产"
# ---- 归档表 Schema（双轨兼容） ----
# v2 = 线上「工具/方法论」节点实测 canonical schema（2026-08-21 起为唯一新建标准）
SCHEMA_V2: str = "v2"
SCHEMA_V2_HEADERS: tuple[str, ...] = ("编号", "名称", "描述", "归档时间", "标签")
SCHEMA_V2_COL_WIDTHS: str = "153,184,185,120,96"
# v1 = 历史遗留 schema，AI/Agent、文案/创意、跨境运营、组织/管理 四节点仍在使用
SCHEMA_V1: str = "v1"
SCHEMA_V1_HEADERS: tuple[str, ...] = ("序号", "归档日期", "资产名称", "来源/主题", "访问链接")
SCHEMA_V1_COL_WIDTHS: str = "60,110,260,200,200"

DEFAULT_TABLE_HEADERS: tuple[str, ...] = SCHEMA_V2_HEADERS
DEFAULT_TABLE_COL_WIDTHS: str = SCHEMA_V2_COL_WIDTHS
SUPPORTED_TABLE_SCHEMAS: Dict[str, tuple[str, ...]] = {
    SCHEMA_V2: SCHEMA_V2_HEADERS,
    SCHEMA_V1: SCHEMA_V1_HEADERS,
}
DEFAULT_ASSET_ID_PREFIX: str = "IM"
DEFAULT_ASSET_ID_SEQ_WIDTH: int = 3
DEFAULT_VERIFY_AFTER_WRITE: bool = True
DEFAULT_LARK_DOMAIN: str = "https://bytedance.larkoffice.com"
DEFAULT_WRITE_DELAY_SECONDS: int = 2
DEFAULT_ALLOWED_LINK_SEGMENTS: tuple[str, ...] = ("/docx/", "/docs/", "/wiki/", "/file/")
DEFAULT_ALLOWED_MARKDOWN_SUFFIXES: tuple[str, ...] = (".lark.md", ".md")
DEFAULT_REQUIRE_SECRETS_FOR_REMOTE_WRITE: bool = True
# 「文件存在」≠「toolset 可用」：命中以下任一特征即判定候选脚本不可用，必须继续降级。
DEFAULT_TOOLSET_UNAVAILABLE_PATTERNS: tuple[str, ...] = (
    r"toolset\s+\S+\s+not\s+found",
    r"toolset\s+not\s+found",
    r"unknown\s+toolset",
    r"AimeError",
    r"Error\s+from\s+AIME\s+Server",
    r"tool\s+\S+\s+not\s+found",
)
DEFAULT_DOWNLOAD_FALLBACK_TO_LARK_CLI: bool = True

CATEGORY_NODE_MAP: Dict[str, str] = {
    "AI/Agent": "HIAbwCz1CiPYg6kghEXcKS2Onqh",
    "文案/创意": "FyjhwJ18CiFZfXkrvzacKG0SnyE",
    "跨境运营": "MF0Nwy7fUioaqEkIz10cFizCnbg",
    "组织/管理": "QnAvwyEqliEz6dkpRYLcJeVbnQh",
    "行业趋势": "OJ9MwQ4h2i3wDXkktOhckmkKnpg",
    "工具/方法论": "BiqXwKriTimRwXkZfuCclocpnK2",
}

_CATEGORY_ALIASES: Dict[str, Sequence[str]] = {
    "AI/Agent": ("AI/Agent", "ai/agent", "AI-Agent", "ai-agent", "AI Agent", "ai agent", "AI／Agent"),
    "文案/创意": ("文案/创意", "文案创意", "文案-创意", "创意/文案", "创意文案"),
    "跨境运营": ("跨境运营", "跨境/运营", "跨境-运营"),
    "组织/管理": ("组织/管理", "组织管理", "组织-管理", "管理/组织"),
    "行业趋势": ("行业趋势", "行业/趋势", "行业-趋势"),
    "工具/方法论": ("工具/方法论", "工具方法论", "工具-方法论", "方法论/工具"),
}

_BLOCK_RE = re.compile(
    r"<!--\s*(BLOCK_\d+)\s*\|\s*([^\s]+)\s*-->\s*(.*?)\s*<!--\s*END_BLOCK_\d+\s*-->",
    flags=re.S,
)
_ROW_RE = re.compile(r"<tr>\s*(.*?)\s*</tr>", flags=re.S)
_CELL_RE = re.compile(r"<t[dh]>\s*(.*?)\s*</t[dh]>", flags=re.S)
_HEADING_RE = re.compile(r"^\s*##\s+")


class WikiArchiveError(RuntimeError):
    """归档写入异常：一旦触发必须阻断主流程。"""


@dataclass
class Block:
    number: str
    block_id: str
    content: str


@dataclass
class ArchivePatch:
    category: str
    document_url: str
    next_index: int
    modifications: List[Dict[str, str]]
    schema: str = SCHEMA_V2
    asset_id: str = ""
    tags: str = ""


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_category_key(value: Any) -> str:
    text = _normalize_text(value).lower()
    text = text.replace("／", "/")
    text = re.sub(r"[\s\-_/、，,]+", "", text)
    return text


def supported_categories() -> List[str]:
    return list(CATEGORY_NODE_MAP.keys())


def normalize_category(explicit_category: Optional[str] = None, inferred_category: Optional[str] = None) -> str:
    chosen = explicit_category if _normalize_text(explicit_category) else inferred_category
    if not _normalize_text(chosen):
        raise WikiArchiveError(
            "归档熔断：未提供显式 category，且也没有可用的自动推断分类。"
            f"支持分类：{', '.join(supported_categories())}。"
        )

    alias_map: Dict[str, str] = {}
    for canonical, variants in _CATEGORY_ALIASES.items():
        alias_map[_normalize_category_key(canonical)] = canonical
        for item in variants:
            alias_map[_normalize_category_key(item)] = canonical

    normalized = alias_map.get(_normalize_category_key(chosen))
    if not normalized:
        raise WikiArchiveError(
            "归档熔断：category 不在白名单路由表中。"
            f"收到：{chosen!r}；支持分类：{', '.join(supported_categories())}。"
        )
    return normalized


def build_wiki_url(category: str) -> str:
    canonical = normalize_category(category)
    token = CATEGORY_NODE_MAP[canonical]
    return f"{DEFAULT_LARK_DOMAIN}/wiki/{token}"


def validate_access_link(access_link: str) -> None:
    value = _normalize_text(access_link)
    if not value:
        raise WikiArchiveError("归档熔断：访问链接为空，禁止写入空链接占位行。")
    if not value.startswith("https://"):
        raise WikiArchiveError(f"归档熔断：访问链接必须是 https 链接，收到：{value!r}")
    if not any(segment in value for segment in DEFAULT_ALLOWED_LINK_SEGMENTS):
        raise WikiArchiveError(
            "归档熔断：访问链接不是受支持的飞书文档链接。"
            f"要求包含 {DEFAULT_ALLOWED_LINK_SEGMENTS!r}，收到：{value!r}"
        )


def validate_archive_date(archive_date: str) -> None:
    value = _normalize_text(archive_date)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        raise WikiArchiveError(f"归档熔断：归档日期必须为 YYYY-MM-DD，收到：{archive_date!r}")


def validate_archive_request(
    *,
    category: str,
    asset_name: str,
    source_topic: str,
    access_link: str,
    archive_date: str,
) -> None:
    normalize_category(category)
    if not _normalize_text(asset_name):
        raise WikiArchiveError("归档熔断：资产名称为空，禁止写入不可辨识记录。")
    if not _normalize_text(source_topic):
        raise WikiArchiveError("归档熔断：来源/主题为空，禁止写入失去检索价值的记录。")
    validate_access_link(access_link)
    validate_archive_date(archive_date)


def parse_blocks(markdown_text: str) -> List[Block]:
    blocks: List[Block] = []
    for match in _BLOCK_RE.finditer(markdown_text):
        blocks.append(
            Block(
                number=match.group(1),
                block_id=match.group(2),
                content=match.group(3).strip("\n"),
            )
        )
    if not blocks:
        raise WikiArchiveError("归档熔断：未解析到飞书 block 标记，无法生成 MCP 修改补丁。")
    return blocks


def find_archive_heading_index(blocks: Sequence[Block]) -> int:
    for idx, block in enumerate(blocks):
        if DEFAULT_ARCHIVE_HEADING in block.content:
            return idx
    raise WikiArchiveError(
        f"归档熔断：目标文档缺少『{DEFAULT_ARCHIVE_HEADING}』标题，无法确定写入位置。"
    )


def find_section_end_index(blocks: Sequence[Block], heading_idx: int) -> int:
    for idx in range(heading_idx + 1, len(blocks)):
        if _HEADING_RE.match(blocks[idx].content.strip()) and DEFAULT_ARCHIVE_HEADING not in blocks[idx].content:
            return idx
    return len(blocks)


def _strip_html_tags(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _extract_table_rows_raw(table_html: str) -> List[List[str]]:
    """按行提取单元格的原始内容（保留 <a href> 锚点），供链接类断言使用。"""
    rows: List[List[str]] = []
    for row_html in _ROW_RE.findall(table_html):
        cells = [
            re.sub(r"^<t[dh][^>]*>|</t[dh]>$", "", cell.strip(), flags=re.S)
            for cell in _CELL_RE.findall(row_html)
        ]
        if cells:
            rows.append(cells)
    return rows


def _extract_table_rows(table_html: str) -> List[List[str]]:
    rows: List[List[str]] = []
    for row_html in _ROW_RE.findall(table_html):
        cells = [_strip_html_tags(cell) for cell in _CELL_RE.findall(row_html)]
        if cells:
            rows.append(cells)
    return rows


def detect_table_schema(table_html: str) -> str:
    """识别线上归档表使用的 schema（v2 新 / v1 遗留），无法识别即熔断。

    线上 6 个分类节点存在 schema 漂移：「工具/方法论」已升级为
    `编号|名称|描述|归档时间|标签`，其余节点仍是 `序号|归档日期|资产名称|来源/主题|访问链接`。
    因此校验必须双轨接受，并按实际命中的 schema 构造归档行，而不是一律熔断。
    """
    rows = _extract_table_rows(table_html)
    if not rows:
        raise WikiArchiveError("归档熔断：已归档资产表格为空，无法确认表头。")
    headers = rows[0]
    for schema, expected in SUPPORTED_TABLE_SCHEMAS.items():
        if headers == list(expected):
            return schema
    raise WikiArchiveError(
        "归档熔断：已归档资产表格表头不属于任何受支持的 schema。"
        f"支持：v2={list(SCHEMA_V2_HEADERS)} / v1={list(SCHEMA_V1_HEADERS)}；实际：{headers}。"
    )


def validate_archive_table_headers(table_html: str) -> str:
    """双 schema 表头校验；返回命中的 schema 名。"""
    return detect_table_schema(table_html)


def find_existing_table_block_index(blocks: Sequence[Block], heading_idx: int, section_end_idx: int) -> Optional[int]:
    for idx in range(heading_idx + 1, section_end_idx):
        content = blocks[idx].content
        if "<table" not in content:
            continue
        validate_archive_table_headers(content)
        return idx
    return None


def _safe_int(value: str) -> Optional[int]:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def next_archive_index(table_html: Optional[str]) -> int:
    if not table_html:
        return 1
    rows = _extract_table_rows(table_html)
    if len(rows) <= 1:
        return 1
    indices = [idx for idx in (_safe_int(row[0]) for row in rows[1:]) if idx is not None]
    return (max(indices) + 1) if indices else 1


def _asset_id_date_part(archive_date: str) -> str:
    """`2026-08-21` → `260821`，与线上既有编号风格（IM-260821-001）一致。"""
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", _normalize_text(archive_date))
    if not match:
        raise WikiArchiveError(f"归档熔断：archive_date 必须为 YYYY-MM-DD，实际：{archive_date!r}")
    return f"{match.group(1)[2:]}{match.group(2)}{match.group(3)}"


def next_archive_asset_id(table_html: Optional[str], archive_date: str) -> str:
    """按当日已有最大序号 +1 生成编号（如 IM-260821-002）。

    编号风格取自线上历史数据，不自创格式；同日无既有编号时从 001 起。
    """
    date_part = _asset_id_date_part(archive_date)
    pattern = re.compile(rf"^{re.escape(DEFAULT_ASSET_ID_PREFIX)}-{date_part}-(\d+)$")
    seq_max = 0
    if table_html:
        rows = _extract_table_rows(table_html)
        for row in rows[1:]:
            if not row:
                continue
            match = pattern.match(_normalize_text(row[0]))
            if match:
                seq_max = max(seq_max, int(match.group(1)))
    return f"{DEFAULT_ASSET_ID_PREFIX}-{date_part}-{seq_max + 1:0{DEFAULT_ASSET_ID_SEQ_WIDTH}d}"


def build_archive_tags(category: str, source_topic: str, tags: Optional[str] = None) -> str:
    """标签 = 分类名（如 `工具 / 方法论`）+ 主题关键词，与线上历史行写法一致。"""
    explicit = _normalize_text(tags)
    if explicit:
        return explicit
    category_label = " / ".join(part.strip() for part in str(category).split("/") if part.strip())
    keyword = _normalize_text(source_topic)
    # 来源/主题常写成 "微博@林亦LYi · AI 数据可视化"，取最后一段作为关键词
    for sep in ("·", "|", "/"):
        if sep in keyword:
            keyword = keyword.split(sep)[-1].strip()
    if not keyword:
        return category_label
    return f"{category_label} / {keyword}"


def build_archive_row(
    index: int,
    archive_date: str,
    asset_name: str,
    source_topic: str,
    access_link: str,
    *,
    schema: str = SCHEMA_V2,
    asset_id: Optional[str] = None,
    tags: Optional[str] = None,
    category: str = "",
) -> str:
    """按命中的 schema 构造归档行。

    v2：编号 | 名称（带超链接） | 描述 | 归档时间 | 标签
    v1：序号 | 归档日期 | 资产名称 | 来源/主题 | 访问链接
    """
    safe_asset_name = html.escape(asset_name, quote=False)
    safe_source_topic = html.escape(source_topic, quote=False)

    if schema == SCHEMA_V1:
        return (
            "    <tr>\n"
            f"        <td>{index}</td>\n"
            f"        <td>{archive_date}</td>\n"
            f"        <td>{safe_asset_name}</td>\n"
            f"        <td>{safe_source_topic}</td>\n"
            f'        <td><a href="{access_link}">打开文档</a></td>\n'
            "    </tr>"
        )
    if schema != SCHEMA_V2:
        raise WikiArchiveError(f"归档熔断：不支持的归档表 schema：{schema!r}")

    final_id = _normalize_text(asset_id)
    if not final_id:
        raise WikiArchiveError("归档熔断：v2 schema 必须提供编号（asset_id），不得留空。")
    final_tags = html.escape(build_archive_tags(category, source_topic, tags), quote=False)
    return (
        "    <tr>\n"
        f"        <td>{final_id}</td>\n"
        f'        <td><a href="{access_link}">{safe_asset_name}</a></td>\n'
        f"        <td>{safe_source_topic}</td>\n"
        f"        <td>{archive_date}</td>\n"
        f"        <td>{final_tags}</td>\n"
        "    </tr>"
    )


def append_row_to_table(table_html: str, row_html: str) -> str:
    if "</table>" not in table_html:
        raise WikiArchiveError("归档熔断：检测到表格 block，但缺少 </table> 结束标记。")
    validate_archive_table_headers(table_html)
    updated, count = re.subn(r"\s*</table>\s*$", f"\n{row_html}\n</table>", table_html.strip(), count=1)
    if count != 1:
        raise WikiArchiveError("归档熔断：向已归档资产表格追加新行失败。")
    return updated


def build_archive_table(row_html: str, *, schema: str = SCHEMA_V2) -> str:
    """表格不存在时新建：默认使用 v2 canonical 表头与线上实测列宽。"""
    headers = SUPPORTED_TABLE_SCHEMAS.get(schema)
    if headers is None:
        raise WikiArchiveError(f"归档熔断：不支持的归档表 schema：{schema!r}")
    col_widths = SCHEMA_V1_COL_WIDTHS if schema == SCHEMA_V1 else SCHEMA_V2_COL_WIDTHS
    header_cells = "\n".join(f"        <td>{header}</td>" for header in headers)
    return (
        f'<table header-row="true" col-widths="{col_widths}">\n'
        "    <tr>\n"
        f"{header_cells}\n"
        "    </tr>\n"
        f"{row_html}\n"
        "</table>"
    )


def find_insert_anchor_index(blocks: Sequence[Block], heading_idx: int, section_end_idx: int) -> int:
    if section_end_idx - heading_idx <= 1:
        return heading_idx
    return section_end_idx - 1


def build_archive_patch(
    *,
    markdown_text: str,
    document_url: str,
    category: str,
    asset_name: str,
    source_topic: str,
    access_link: str,
    archive_date: str,
    tags: Optional[str] = None,
) -> ArchivePatch:
    validate_archive_request(
        category=category,
        asset_name=asset_name,
        source_topic=source_topic,
        access_link=access_link,
        archive_date=archive_date,
    )
    blocks = parse_blocks(markdown_text)
    heading_idx = find_archive_heading_index(blocks)
    section_end_idx = find_section_end_index(blocks, heading_idx)
    table_idx = find_existing_table_block_index(blocks, heading_idx, section_end_idx)

    if table_idx is not None:
        current_table = blocks[table_idx].content
        schema = detect_table_schema(current_table)
        next_index = next_archive_index(current_table)
        asset_id = next_archive_asset_id(current_table, archive_date)
        final_tags = build_archive_tags(category, source_topic, tags)
        row_html = build_archive_row(
            next_index,
            archive_date,
            asset_name,
            source_topic,
            access_link,
            schema=schema,
            asset_id=asset_id,
            tags=final_tags,
            category=category,
        )
        new_content = append_row_to_table(current_table, row_html)
        modifications = [
            {
                "block_number": blocks[table_idx].number,
                "block_id": blocks[table_idx].block_id,
                "content": new_content + "\n",
                "modification_type": "update",
            }
        ]
        return ArchivePatch(
            category=category,
            document_url=document_url,
            next_index=next_index,
            modifications=modifications,
            schema=schema,
            asset_id=asset_id if schema == SCHEMA_V2 else "",
            tags=final_tags if schema == SCHEMA_V2 else "",
        )

    # 表格不存在 → 按 v2 canonical schema 新建
    schema = SCHEMA_V2
    next_index = 1
    asset_id = next_archive_asset_id(None, archive_date)
    final_tags = build_archive_tags(category, source_topic, tags)
    row_html = build_archive_row(
        next_index,
        archive_date,
        asset_name,
        source_topic,
        access_link,
        schema=schema,
        asset_id=asset_id,
        tags=final_tags,
        category=category,
    )
    new_table = build_archive_table(row_html, schema=schema)
    anchor_idx = find_insert_anchor_index(blocks, heading_idx, section_end_idx)
    modifications = [
        {
            "block_number": blocks[anchor_idx].number,
            "block_id": blocks[anchor_idx].block_id,
            "content": new_table + "\n",
            "modification_type": "insert",
        }
    ]
    return ArchivePatch(
        category=category,
        document_url=document_url,
        next_index=next_index,
        modifications=modifications,
        schema=schema,
        asset_id=asset_id,
        tags=final_tags,
    )


def verify_archive_presence_in_markdown(
    markdown_text: str,
    *,
    asset_name: str,
    access_link: str,
    expected_index: Optional[int] = None,
    expected_asset_id: Optional[str] = None,
) -> None:
    """RAW 回读断言：新增行的编号 + 名称 + 链接必须真实存在。

    v2 schema 下不再断言「期望序号」这类旧语义，而是断言编号（如 IM-260821-002）
    与带超链接的名称同行出现；v1 遗留节点仍按资产名称 + 链接同行断言。
    """
    blocks = parse_blocks(markdown_text)
    heading_idx = find_archive_heading_index(blocks)
    section_end_idx = find_section_end_index(blocks, heading_idx)
    table_idx = find_existing_table_block_index(blocks, heading_idx, section_end_idx)
    if table_idx is None:
        raise WikiArchiveError("归档熔断：RAW 回读未检测到『已归档资产』表格。")

    table_html = blocks[table_idx].content
    schema = detect_table_schema(table_html)
    if asset_name not in table_html or access_link not in table_html:
        raise WikiArchiveError(
            "归档熔断：RAW 回读未找到刚写入的资产名称或访问链接。"
            f" asset_name={asset_name!r}, access_link={access_link!r}"
        )

    rows = _extract_table_rows(table_html)[1:]
    if schema == SCHEMA_V2:
        raw_rows = _extract_table_rows_raw(table_html)[1:]
        target_found = any(
            len(row) >= 5
            and (expected_asset_id is None or _normalize_text(row[0]) == _normalize_text(expected_asset_id))
            and asset_name in row[1]
            and access_link in row[1]
            for row in raw_rows
        )
        if not target_found:
            raise WikiArchiveError(
                "归档熔断：RAW 回读未找到「编号 + 名称 + 链接」三者齐备的新归档行。"
                f" expected_asset_id={expected_asset_id!r}, asset_name={asset_name!r}, access_link={access_link!r}"
            )
        return

    target_found = any(
        len(row) >= 5
        and asset_name == _normalize_text(row[2])
        and (expected_index is None or _normalize_text(row[0]) == str(expected_index))
        for row in rows
    )
    if not target_found:
        raise WikiArchiveError(
            "归档熔断：RAW 回读未找到 v1 schema 下的新归档行。"
            f" expected_index={expected_index}, asset_name={asset_name!r}"
        )


def get_workspace_root() -> Path:
    env_path = os.environ.get("IRIS_WORKSPACE_PATH")
    if env_path:
        return Path(env_path).resolve()
    return Path(__file__).resolve().parents[3]


def run_subprocess(command: List[str], action: str, *, input_text: Optional[str] = None) -> str:
    result = subprocess.run(command, input=input_text, capture_output=True, text=True)
    if result.returncode != 0:
        raise WikiArchiveError(
            f"{action} failed with exit code {result.returncode}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout.strip()


def require_secrets() -> None:
    if not DEFAULT_REQUIRE_SECRETS_FOR_REMOTE_WRITE:
        return
    jwt = _normalize_text(os.environ.get("AIME_USER_CLOUD_JWT"))
    if not jwt:
        raise WikiArchiveError(
            "归档熔断：远端归档必须带用户鉴权。"
            "请通过 bash 工具直接执行，并设置 include_secrets=true。"
        )


def resolve_existing_script(candidates: Sequence[Path], action: str) -> Path:
    """Resolve a usable local MCP/shortcut script without modifying inner_skills.

    The resolver keeps legacy paths working but no longer assumes the historical
    inner_skills/lark wrappers are present.  All candidates are local AIME MCP
    shortcuts or lark-cli-backed scripts; OpenAPI/JWT direct calls are forbidden.
    """
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    formatted = "\n".join(f"- {candidate}" for candidate in candidates)
    raise WikiArchiveError(
        f"归档熔断：未找到可用的 Lark MCP {action} 脚本，禁止降级到 OpenAPI。候选路径：\n{formatted}"
    )


def list_existing_scripts(candidates: Sequence[Path]) -> List[Path]:
    """Return every candidate that physically exists (existence != usability)."""
    return [candidate for candidate in candidates if candidate.exists() and candidate.is_file()]


def is_toolset_unavailable(output: str) -> bool:
    """Detect that an existing MCP shortcut is backed by a retired AIME toolset.

    ``lark_download`` still ships as a file, but its toolset has been removed, so
    running it fails with ``toolset lark_download not found``.  Existence checks
    alone are therefore insufficient — we must probe and keep degrading.
    """
    text = _normalize_text(output)
    if not text:
        return False
    for pattern in DEFAULT_TOOLSET_UNAVAILABLE_PATTERNS:
        if re.search(pattern, text, flags=re.I):
            return True
    return False


def ephemeral_pool_dir() -> Path:
    pool = Path(os.environ.get("EPHEMERAL_POOL_DIR") or "/workspace/.ephemeral_pool")
    pool.mkdir(parents=True, exist_ok=True)
    return pool


def _split_top_level_xml_elements(xml_text: str) -> List[tuple[str, str, str]]:
    """Split DocxXML into top-level (tag, attrs, whole_element) triples."""
    elements: List[tuple[str, str, str]] = []
    pos = 0
    length = len(xml_text)
    open_re = re.compile(r"<([A-Za-z][\w:-]*)((?:\"[^\"]*\"|'[^']*'|[^>\"'])*?)(/?)>")
    while pos < length:
        match = open_re.search(xml_text, pos)
        if not match:
            break
        tag, attrs, self_closing = match.group(1), match.group(2), match.group(3)
        if self_closing:
            elements.append((tag, attrs, match.group(0)))
            pos = match.end()
            continue
        depth = 1
        cursor = match.end()
        token_re = re.compile(rf"</{re.escape(tag)}\s*>|<{re.escape(tag)}(?=[\s/>])")
        end = length
        while cursor < length:
            token = token_re.search(xml_text, cursor)
            if not token:
                break
            if token.group(0).startswith("</"):
                depth -= 1
                if depth == 0:
                    end = token.end()
                    break
            else:
                depth += 1
            cursor = token.end()
        elements.append((tag, attrs, xml_text[match.start():end]))
        pos = end
    return elements


def _attr(attrs: str, name: str) -> str:
    match = re.search(rf'{re.escape(name)}\s*=\s*"([^"]*)"', attrs)
    return match.group(1) if match else ""


def _xml_inline_to_markdown(fragment: str) -> str:
    text = re.sub(r"<a\s+[^>]*href=\"([^\"]*)\"[^>]*>(.*?)</a>", r"[\2](\1)", fragment, flags=re.S)
    return _strip_html_tags(text)


def _normalize_cell_anchors(fragment: str) -> str:
    """把单元格内的链接统一规范为 HTML 锚点 `<a href="u">text</a>`。

    历史实现把锚点转成 markdown `[text](url)` 再写回，但飞书对表格单元格内的
    markdown 链接解析不稳定：锚文本会累积字面方括号（`[text]`），多轮写回后甚至
    出现名称列被清空。统一用 HTML 锚点可保证「读回 → 追加 → 写回」幂等。
    """
    anchors: List[tuple[str, str]] = []

    def _stash(match: "re.Match[str]") -> str:
        href = match.group(1)
        text = _strip_html_tags(match.group(2))
        # 兼容历史脏数据：锚文本被写成 "[真实名称]" 时剥掉外层方括号
        stripped = re.sub(r"^\[(.*)\]$", r"\1", text.strip(), flags=re.S)
        anchors.append((href, stripped))
        return f"\x00ANCHOR{len(anchors) - 1}\x00"

    stashed = re.sub(r"<a\s+[^>]*href=\"([^\"]*)\"[^>]*>(.*?)</a>", _stash, fragment, flags=re.S)
    text = _strip_html_tags(stashed)
    for idx, (href, label) in enumerate(anchors):
        text = text.replace(f"\x00ANCHOR{idx}\x00", f'<a href="{href}">{html.escape(label, quote=False)}</a>')
    return text


def _xml_cell_text(cell_xml: str) -> str:
    inner = re.sub(r"^<t[dh][^>]*>|</t[dh]>$", "", cell_xml.strip(), flags=re.S)
    return _normalize_cell_anchors(inner)


def xml_table_to_markdown_table(table_xml: str) -> str:
    """Normalize a DocxXML table into the markdown-format HTML table contract."""
    widths = re.findall(r'<col\s+width="(\d+)"\s*/?>', table_xml)
    col_widths = ",".join(widths) if widths else DEFAULT_TABLE_COL_WIDTHS
    rows_html: List[str] = []
    for row_xml in re.findall(r"<tr[^>]*>(.*?)</tr>", table_xml, flags=re.S):
        cells = re.findall(r"<t[dh][^>]*>.*?</t[dh]>", row_xml, flags=re.S)
        if not cells:
            continue
        body = "\n".join(f"        <td>{_xml_cell_text(cell)}</td>" for cell in cells)
        rows_html.append("    <tr>\n" + body + "\n    </tr>")
    if not rows_html:
        raise WikiArchiveError("归档熔断：XML 表格转换失败，未解析到任何数据行。")
    return (
        f'<table header-row="true" col-widths="{col_widths}">\n'
        + "\n".join(rows_html)
        + "\n</table>"
    )


def _xml_element_to_block_content(tag: str, attrs: str, whole: str) -> str:
    if tag == "table":
        return xml_table_to_markdown_table(whole)
    inner = re.sub(rf"^<{re.escape(tag)}[^>]*>|</{re.escape(tag)}>$", "", whole.strip(), flags=re.S)
    if re.fullmatch(r"h[1-9]", tag):
        level = int(tag[1:])
        return f"{'#' * level} {_xml_inline_to_markdown(inner)}"
    if tag == "title":
        return f"# {_xml_inline_to_markdown(inner)}"
    return _xml_inline_to_markdown(inner)


def _element_block_id(attrs: str, whole: str) -> str:
    block_id = _attr(attrs, "id")
    if block_id:
        return block_id
    nested = re.search(r'\sid="([^"]+)"', whole)
    return nested.group(1) if nested else ""


def docx_xml_to_pseudo_markdown(xml_text: str) -> str:
    """Convert DocxXML (with-ids) into the pseudo ``.lark.md`` block format."""
    elements = _split_top_level_xml_elements(xml_text)
    if not elements:
        raise WikiArchiveError("归档熔断：DocxXML 解析失败，未发现任何顶层 block。")
    chunks: List[str] = []
    number = 0
    for tag, attrs, whole in elements:
        block_id = _element_block_id(attrs, whole)
        if not block_id:
            continue
        number += 1
        content = _xml_element_to_block_content(tag, attrs, whole)
        chunks.append(
            f"<!-- BLOCK_{number} | {block_id} -->\n{content}\n<!-- END_BLOCK_{number} -->"
        )
    if not chunks:
        raise WikiArchiveError("归档熔断：DocxXML 中未找到带 block id 的顶层节点。")
    return "\n".join(chunks) + "\n"


def lark_cli_download(document_url: str) -> Path:
    """Fallback download path: ``lark-cli docs +fetch`` XML (with-ids) → pseudo lark.md."""
    lark_cli = shutil.which("lark-cli")
    if not lark_cli:
        raise WikiArchiveError("归档熔断：未找到 lark-cli，无法执行 docs +fetch 下载兜底，禁止退回 OpenAPI。")

    raw = run_subprocess(
        [
            lark_cli, "docs", "+fetch", "--as", "user",
            "--doc", document_url,
            "--doc-format", "xml",
            "--detail", "with-ids",
            "--format", "json",
        ],
        "lark-cli docs +fetch xml with-ids",
    )
    try:
        payload = json.loads(raw)
        content = payload["data"]["document"]["content"]
    except Exception as exc:  # noqa: BLE001
        raise WikiArchiveError(f"归档熔断：lark-cli docs +fetch 输出解析失败：{exc}；原始输出前 500 字：{raw[:500]}")
    if not _normalize_text(content):
        raise WikiArchiveError("归档熔断：lark-cli docs +fetch 返回空文档内容。")

    pseudo = docx_xml_to_pseudo_markdown(content)
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", document_url.rstrip("/").split("/")[-1])[:40] or "doc"
    target = ephemeral_pool_dir() / f"wiki_archive_{slug}_{stamp}_{os.getpid()}.lark.md"
    target.write_text(pseudo, encoding="utf-8")
    return target


def parse_download_paths(output: str) -> List[str]:
    patterns = (
        r'file_path:\s*"([^"]+)"',
        r'"file_path"\s*:\s*"([^"]+)"',
        r'\[\s*"([^"]+?\.(?:lark\.md|md))"\s*\]',
        r'([^\s"\']+\.(?:lark\.md|md))',
    )
    paths: List[str] = []
    for pattern in patterns:
        for raw_path in re.findall(pattern, output):
            if isinstance(raw_path, tuple):
                raw_path = next((item for item in raw_path if item), "")
            if raw_path and raw_path not in paths:
                paths.append(raw_path)
    return paths


def mcp_download(document_url: str) -> Path:
    """Download the target doc, probing每个候选脚本的真实可用性后逐级降级。

    降级链路：本地 MCP 下载脚本（存在且可运行）→ lark-cli docs +fetch xml with-ids
    → 全部不可用才 raise。禁止退回 OpenAPI / JWT 直调。
    """
    workspace_root = get_workspace_root()
    candidates = [
        workspace_root / "inner_skills/lark/mcp_lark_lark_download.py",
        workspace_root / "inner_skills/lark_download/lark_download.py",
    ]
    existing = list_existing_scripts(candidates)
    failures: List[str] = []

    for download_script in existing:
        try:
            output = run_subprocess(
                ["python3", str(download_script), json.dumps({"document_url": document_url}, ensure_ascii=False)],
                f"lark download via {download_script}",
            )
        except WikiArchiveError as exc:
            if is_toolset_unavailable(str(exc)):
                failures.append(f"{download_script}: toolset 不可用（已降级）")
                continue
            failures.append(f"{download_script}: {exc}")
            continue

        if is_toolset_unavailable(output):
            failures.append(f"{download_script}: toolset 不可用（已降级）")
            continue

        paths = parse_download_paths(output)
        for raw_path in paths:
            path = Path(raw_path).expanduser().resolve()
            if path.exists() and path.name.endswith(DEFAULT_ALLOWED_MARKDOWN_SUFFIXES):
                return path
        failures.append(f"{download_script}: 输出中未找到可用 Markdown 文件（{paths}）")

    if DEFAULT_DOWNLOAD_FALLBACK_TO_LARK_CLI:
        try:
            return lark_cli_download(document_url)
        except WikiArchiveError as exc:
            failures.append(f"lark-cli docs +fetch: {exc}")

    formatted = "\n".join(f"- {item}" for item in failures) or "- 无任何可用候选"
    raise WikiArchiveError(
        "归档熔断：所有 Lark 下载候选（本地 MCP 脚本 + lark-cli docs +fetch）均不可用，禁止降级到 OpenAPI。\n"
        f"失败明细：\n{formatted}"
    )


def _run_lark_cli_update(document_url: str, modifications: List[Dict[str, str]]) -> str:
    lark_cli = shutil.which("lark-cli")
    if not lark_cli:
        raise WikiArchiveError("归档熔断：未找到 lark-cli，无法执行 docs +update MCP shortcut，禁止退回 OpenAPI。")

    outputs: List[str] = []
    for modification in modifications:
        mod_type = modification.get("modification_type")
        block_id = modification.get("block_id")
        content = modification.get("content", "")
        if not block_id:
            raise WikiArchiveError(f"归档熔断：修改补丁缺少 block_id：{modification!r}")
        if mod_type == "update":
            command = "block_replace"
        elif mod_type == "insert":
            command = "block_insert_after"
        else:
            raise WikiArchiveError(f"归档熔断：不支持的 modification_type：{mod_type!r}")

        outputs.append(
            run_subprocess(
                [
                    lark_cli,
                    "docs",
                    "+update",
                    "--as",
                    "user",
                    "--doc",
                    document_url,
                    "--command",
                    command,
                    "--block-id",
                    block_id,
                    "--doc-format",
                    "markdown",
                    "--content",
                    "-",
                ],
                f"lark-cli docs +update {command}",
                input_text=content,
            )
        )
    return "\n".join(outputs)


def mcp_update(document_url: str, markdown_file_path: Path, modifications: List[Dict[str, str]]) -> str:
    workspace_root = get_workspace_root()
    script_candidates = [
        workspace_root / "inner_skills/lark/mcp_lark_update_lark_doc.py",
        workspace_root / "inner_skills/lark_doc_update/lark_doc_update.py",
        workspace_root / "inner_skills/lark_update/lark_update.py",
    ]
    update_script = next((candidate for candidate in script_candidates if candidate.exists() and candidate.is_file()), None)

    if update_script is not None:
        payload = {
            "document_url": document_url,
            "markdown_file_path": str(markdown_file_path.resolve()),
            "modifications": modifications,
        }
        return run_subprocess(
            ["python3", str(update_script), json.dumps(payload, ensure_ascii=False)],
            f"lark update via {update_script}",
        )

    if shutil.which("lark-cli"):
        return _run_lark_cli_update(document_url, modifications)

    formatted = "\n".join(f"- {candidate}" for candidate in script_candidates)
    raise WikiArchiveError(
        "归档熔断：未找到可用的 Lark MCP 更新脚本或 lark-cli docs +update shortcut，禁止降级到 OpenAPI。"
        f"候选路径：\n{formatted}"
    )


def prepare_archive_from_file(
    *,
    markdown_file: Path,
    category: Optional[str],
    inferred_category: Optional[str],
    asset_name: str,
    source_topic: str,
    access_link: str,
    archive_date: Optional[str] = None,
    document_url: Optional[str] = None,
    tags: Optional[str] = None,
) -> Dict[str, Any]:
    canonical_category = normalize_category(category, inferred_category)
    final_archive_date = _normalize_text(archive_date) or dt.date.today().isoformat()
    final_document_url = _normalize_text(document_url) or build_wiki_url(canonical_category)
    markdown_text = markdown_file.read_text(encoding="utf-8", errors="ignore")
    patch = build_archive_patch(
        markdown_text=markdown_text,
        document_url=final_document_url,
        category=canonical_category,
        asset_name=asset_name,
        source_topic=source_topic,
        access_link=access_link,
        archive_date=final_archive_date,
        tags=tags,
    )
    return {
        "category": patch.category,
        "document_url": patch.document_url,
        "wiki_node_token": CATEGORY_NODE_MAP[patch.category],
        "schema": patch.schema,
        "asset_id": patch.asset_id,
        "tags": patch.tags,
        "next_index": patch.next_index,
        "archive_date": final_archive_date,
        "modifications": patch.modifications,
        "markdown_file_path": str(markdown_file.resolve()),
    }


def archive_to_wiki(
    *,
    category: Optional[str],
    inferred_category: Optional[str],
    asset_name: str,
    source_topic: str,
    access_link: str,
    archive_date: Optional[str] = None,
    tags: Optional[str] = None,
    target_doc: Optional[str] = None,
) -> Dict[str, Any]:
    if DEFAULT_ARCHIVE_REQUIRED is not True:
        raise WikiArchiveError("归档熔断：DEFAULT_ARCHIVE_REQUIRED 被关闭，违反 info-miner 闭环归档约束。")
    require_secrets()

    canonical_category = normalize_category(category, inferred_category)
    # --target-doc 仅供沙盒/回归验证：把写入重定向到一次性临时 Docx，避免污染正式归档节点。
    document_url = _normalize_text(target_doc) or build_wiki_url(canonical_category)
    markdown_file = mcp_download(document_url)
    prepared = prepare_archive_from_file(
        markdown_file=markdown_file,
        category=canonical_category,
        inferred_category=None,
        asset_name=asset_name,
        source_topic=source_topic,
        access_link=access_link,
        archive_date=archive_date,
        document_url=document_url,
        tags=tags,
    )

    update_output = mcp_update(
        document_url=prepared["document_url"],
        markdown_file_path=Path(prepared["markdown_file_path"]),
        modifications=prepared["modifications"],
    )

    if DEFAULT_VERIFY_AFTER_WRITE:
        time.sleep(DEFAULT_WRITE_DELAY_SECONDS)
        verify_file = mcp_download(document_url)
        verify_markdown = verify_file.read_text(encoding="utf-8", errors="ignore")
        verify_archive_presence_in_markdown(
            verify_markdown,
            asset_name=asset_name,
            access_link=access_link,
            expected_index=int(prepared["next_index"]),
            expected_asset_id=prepared["asset_id"] or None,
        )

    return {
        "category": prepared["category"],
        "document_url": prepared["document_url"],
        "wiki_node_token": prepared["wiki_node_token"],
        "schema": prepared["schema"],
        "asset_id": prepared["asset_id"],
        "tags": prepared["tags"],
        "next_index": prepared["next_index"],
        "archive_date": prepared["archive_date"],
        "update_output": update_output,
        "verified": DEFAULT_VERIFY_AFTER_WRITE,
    }


def _fixture_no_table() -> str:
    return """<!-- BLOCK_1 | block-a -->
## 其他标题<!-- END_BLOCK_1 -->
<!-- BLOCK_2 | block-b -->
## 📂 已归档资产<!-- END_BLOCK_2 -->
<!-- BLOCK_3 | block-c -->
> 本节点由 `info-miner` 自动追加新归档条目，无需手动维护。
<!-- END_BLOCK_3 -->
<!-- BLOCK_4 | block-d -->
## 下一个标题<!-- END_BLOCK_4 -->
"""


def _fixture_with_table() -> str:
    return """<!-- BLOCK_1 | block-a -->
## 📂 已归档资产<!-- END_BLOCK_1 -->
<!-- BLOCK_2 | block-b -->
> 说明文字
<!-- END_BLOCK_2 -->
<!-- BLOCK_3 | block-c -->
<table header-row="true" col-widths="60,110,260,200,200">
    <tr>
        <td>序号</td>
        <td>归档日期</td>
        <td>资产名称</td>
        <td>来源/主题</td>
        <td>访问链接</td>
    </tr>
    <tr>
        <td>1</td>
        <td>2026-05-20</td>
        <td>既有资产</td>
        <td>AI/Agent · 既有案例</td>
        <td><a href="https://bytedance.larkoffice.com/docx/old">打开文档</a></td>
    </tr>
</table>
<!-- END_BLOCK_3 -->
"""


def _fixture_with_table_v2() -> str:
    """v2 canonical fixture，镜像线上「工具/方法论」节点实际表头与历史行。"""
    return """<!-- BLOCK_1 | block-a -->
## 📂 已归档资产<!-- END_BLOCK_1 -->
<!-- BLOCK_2 | block-b -->
> 说明文字
<!-- END_BLOCK_2 -->
<!-- BLOCK_3 | block-v2 -->
<table header-row="true" col-widths="153,184,185,120,96">
    <tr>
        <td>编号</td>
        <td>名称</td>
        <td>描述</td>
        <td>归档时间</td>
        <td>标签</td>
    </tr>
    <tr>
        <td>IM-260821-001</td>
        <td><a href="https://bytedance.larkoffice.com/docx/oldv2">【info-miner】Lieflat Charts 溯源与引入评估</a></td>
        <td>微博@林亦LYi · AI 数据可视化</td>
        <td>2026-08-21</td>
        <td>工具 / 方法论 / AI 数据可视化</td>
    </tr>
</table>
<!-- END_BLOCK_3 -->
"""


def _fixture_bad_headers() -> str:
    return """<!-- BLOCK_1 | block-a -->
## 📂 已归档资产<!-- END_BLOCK_1 -->
<!-- BLOCK_2 | block-bad -->
<table header-row="true" col-widths="60,60,60,60,60">
    <tr>
        <td>A</td>
        <td>B</td>
        <td>C</td>
        <td>D</td>
        <td>E</td>
    </tr>
</table>
<!-- END_BLOCK_2 -->
"""


def _fixture_docx_xml() -> str:
    """Minimal DocxXML (with-ids) fixture mirroring真实 Wiki 分类节点结构。"""
    return (
        '<title id="TTL">AI/Agent</title>'
        '<h2 id="doxcnH1">📚 分区说明</h2>'
        '<h2 id="doxcnH2">📂 已归档资产</h2>'
        '<blockquote id="doxcnBQ"><p id="doxcnBQP">本节点由 <code>info-miner</code> 自动追加。</p></blockquote>'
        '<table id="doxcnTBL"><colgroup><col width="60"/><col width="110"/><col width="260"/>'
        '<col width="200"/><col width="200"/></colgroup>'
        '<thead><tr><th vertical-align="top"><p id="h1">序号</p></th>'
        '<th vertical-align="top"><p id="h2">归档日期</p></th>'
        '<th vertical-align="top"><p id="h3">资产名称</p></th>'
        '<th vertical-align="top"><p id="h4">来源/主题</p></th>'
        '<th vertical-align="top"><p id="h5">访问链接</p></th></tr></thead>'
        '<tbody><tr><td vertical-align="top"><p id="c1">1</p></td>'
        '<td vertical-align="top"><p id="c2">2026-05-20</p></td>'
        '<td vertical-align="top"><p id="c3">既有资产</p></td>'
        '<td vertical-align="top"><p id="c4">AI/Agent · 既有案例</p></td>'
        '<td vertical-align="top"><p id="c5">'
        '<a href="https://bytedance.larkoffice.com/docx/old">打开文档</a></p></td></tr></tbody></table>'
    )


def _selftest() -> int:
    cases: List[tuple[str, str]] = []

    try:
        canonical = normalize_category(" ai-agent ")
        cases.append(("normalize category alias", "OK_PASS" if canonical == "AI/Agent" else "FAIL_BAD_VALUE"))
    except Exception:
        cases.append(("normalize category alias", "FAIL_RAISED"))

    try:
        normalize_category("不存在的分类")
        cases.append(("reject unsupported category", "FAIL_NOT_RAISED"))
    except WikiArchiveError:
        cases.append(("reject unsupported category", "OK_RAISED"))

    try:
        patch = build_archive_patch(
            markdown_text=_fixture_no_table(),
            document_url=build_wiki_url("AI/Agent"),
            category="AI/Agent",
            asset_name="新资产",
            source_topic="AI/Agent · 归档测试",
            access_link="https://bytedance.larkoffice.com/docx/test123",
            archive_date="2026-05-20",
        )
        ok = patch.next_index == 1 and patch.modifications[0]["modification_type"] == "insert"
        cases.append(("insert table when missing", "OK_PASS" if ok else "FAIL_BAD_PATCH"))
    except Exception:
        cases.append(("insert table when missing", "FAIL_RAISED"))

    try:
        patch = build_archive_patch(
            markdown_text=_fixture_with_table(),
            document_url=build_wiki_url("AI/Agent"),
            category="AI/Agent",
            asset_name="第二条资产",
            source_topic="AI/Agent · 归档测试",
            access_link="https://bytedance.larkoffice.com/docx/test456",
            archive_date="2026-05-20",
        )
        content = patch.modifications[0]["content"]
        ok = patch.next_index == 2 and patch.modifications[0]["modification_type"] == "update" and "第二条资产" in content
        cases.append(("append row when table exists", "OK_PASS" if ok else "FAIL_BAD_PATCH"))
    except Exception:
        cases.append(("append row when table exists", "FAIL_RAISED"))

    try:
        table_with_new_row = append_row_to_table(
            """<table header-row=\"true\" col-widths=\"60,110,260,200,200\">\n    <tr>\n        <td>序号</td>\n        <td>归档日期</td>\n        <td>资产名称</td>\n        <td>来源/主题</td>\n        <td>访问链接</td>\n    </tr>\n    <tr>\n        <td>1</td>\n        <td>2026-05-20</td>\n        <td>既有资产</td>\n        <td>AI/Agent · 既有案例</td>\n        <td><a href="https://bytedance.larkoffice.com/docx/old">打开文档</a></td>\n    </tr>\n</table>""",
            build_archive_row(
                2, "2026-05-20", "第二条资产", "AI/Agent · 归档测试",
                "https://bytedance.larkoffice.com/docx/test456", schema=SCHEMA_V1,
            ),
        )
        verify_markdown = (
            "<!-- BLOCK_1 | block-a -->\n## 📂 已归档资产<!-- END_BLOCK_1 -->\n"
            "<!-- BLOCK_2 | block-b -->\n> 说明文字\n<!-- END_BLOCK_2 -->\n"
            f"<!-- BLOCK_3 | block-c -->\n{table_with_new_row}\n<!-- END_BLOCK_3 -->\n"
        )
        verify_archive_presence_in_markdown(
            markdown_text=verify_markdown,
            asset_name="第二条资产",
            access_link="https://bytedance.larkoffice.com/docx/test456",
            expected_index=2,
        )
        cases.append(("verify written row", "OK_PASS"))
    except Exception:
        cases.append(("verify written row", "FAIL_RAISED"))

    try:
        validate_archive_request(
            category="AI/Agent",
            asset_name="",
            source_topic="主题",
            access_link="https://bytedance.larkoffice.com/docx/test789",
            archive_date="2026-05-20",
        )
        cases.append(("reject empty asset name", "FAIL_NOT_RAISED"))
    except WikiArchiveError:
        cases.append(("reject empty asset name", "OK_RAISED"))

    # v1.11: 候选脚本可用性探测（文件存在 ≠ toolset 可用）
    try:
        ok = (
            is_toolset_unavailable("AimeError: toolset lark_download not found")
            and is_toolset_unavailable("Error from AIME Server: toolset lark_download not found")
            and not is_toolset_unavailable('file_path: "/tmp/a.lark.md"')
        )
        cases.append(("detect retired toolset output", "OK_PASS" if ok else "FAIL_BAD_VALUE"))
    except Exception:
        cases.append(("detect retired toolset output", "FAIL_RAISED"))

    # v1.11: DocxXML(with-ids) → 伪 lark.md 转换 + 表头提取
    try:
        pseudo = docx_xml_to_pseudo_markdown(_fixture_docx_xml())
        blocks = parse_blocks(pseudo)
        heading_idx = find_archive_heading_index(blocks)
        section_end_idx = find_section_end_index(blocks, heading_idx)
        table_idx = find_existing_table_block_index(blocks, heading_idx, section_end_idx)
        ok = (
            table_idx is not None
            and blocks[table_idx].block_id == "doxcnTBL"
            and next_archive_index(blocks[table_idx].content) == 2
            and 'header-row="true"' in blocks[table_idx].content
            and "<p id=" not in blocks[table_idx].content
            and '<a href="https://bytedance.larkoffice.com/docx/old">打开文档</a>' in blocks[table_idx].content
        )
        cases.append(("docx xml -> pseudo lark.md", "OK_PASS" if ok else "FAIL_BAD_VALUE"))
    except Exception:
        cases.append(("docx xml -> pseudo lark.md", "FAIL_RAISED"))

    # v1.11: XML 链路生成的伪 markdown 能直接支撑补丁构造
    try:
        patch = build_archive_patch(
            markdown_text=docx_xml_to_pseudo_markdown(_fixture_docx_xml()),
            document_url=build_wiki_url("AI/Agent"),
            category="AI/Agent",
            asset_name="XML 链路资产",
            source_topic="AI/Agent · XML fallback",
            access_link="https://bytedance.larkoffice.com/docx/xmlnew",
            archive_date="2026-08-19",
        )
        ok = (
            patch.next_index == 2
            and patch.modifications[0]["modification_type"] == "update"
            and patch.modifications[0]["block_id"] == "doxcnTBL"
        )
        cases.append(("build patch from xml fallback", "OK_PASS" if ok else "FAIL_BAD_PATCH"))
    except Exception:
        cases.append(("build patch from xml fallback", "FAIL_RAISED"))

    # v1.12: 双 schema 表头识别（线上 6 节点存在 schema 漂移）
    try:
        v1_tbl = parse_blocks(_fixture_with_table())[2].content
        v2_tbl = parse_blocks(_fixture_with_table_v2())[2].content
        ok = detect_table_schema(v1_tbl) == SCHEMA_V1 and detect_table_schema(v2_tbl) == SCHEMA_V2
        cases.append(("detect dual schema headers", "OK_PASS" if ok else "FAIL_BAD_VALUE"))
    except Exception:
        cases.append(("detect dual schema headers", "FAIL_RAISED"))

    try:
        detect_table_schema(parse_blocks(_fixture_bad_headers())[1].content)
        cases.append(("reject unknown schema headers", "FAIL_NOT_RAISED"))
    except WikiArchiveError:
        cases.append(("reject unknown schema headers", "OK_RAISED"))

    # v1.12: canonical 表头 = 线上实际 schema
    try:
        ok = (
            DEFAULT_TABLE_HEADERS == ("编号", "名称", "描述", "归档时间", "标签")
            and "编号" in build_archive_table(build_archive_row(
                1, "2026-08-21", "新资产", "工具/方法论 · 测试",
                "https://bytedance.larkoffice.com/docx/new", schema=SCHEMA_V2,
                asset_id="IM-260821-001", category="工具/方法论",
            ))
            and "序号" in build_archive_table("    <tr></tr>", schema=SCHEMA_V1)
        )
        cases.append(("canonical headers = online v2", "OK_PASS" if ok else "FAIL_BAD_VALUE"))
    except Exception:
        cases.append(("canonical headers = online v2", "FAIL_RAISED"))

    # v1.12: 编号按当日最大序号 +1 自增
    try:
        v2_tbl = parse_blocks(_fixture_with_table_v2())[2].content
        ok = (
            next_archive_asset_id(v2_tbl, "2026-08-21") == "IM-260821-002"
            and next_archive_asset_id(v2_tbl, "2026-08-22") == "IM-260822-001"
            and next_archive_asset_id(None, "2026-08-21") == "IM-260821-001"
        )
        cases.append(("asset id auto increment", "OK_PASS" if ok else "FAIL_BAD_VALUE"))
    except Exception:
        cases.append(("asset id auto increment", "FAIL_RAISED"))

    try:
        next_archive_asset_id(None, "2026/08/21")
        cases.append(("reject bad archive date for id", "FAIL_NOT_RAISED"))
    except WikiArchiveError:
        cases.append(("reject bad archive date for id", "OK_RAISED"))

    # v1.12: 标签 = 分类名 + 主题关键词
    try:
        ok = (
            build_archive_tags("工具/方法论", "微博@林亦LYi · AI 数据可视化") == "工具 / 方法论 / AI 数据可视化"
            and build_archive_tags("AI/Agent", "任意主题", tags="显式标签") == "显式标签"
        )
        cases.append(("build tags from category + topic", "OK_PASS" if ok else "FAIL_BAD_VALUE"))
    except Exception:
        cases.append(("build tags from category + topic", "FAIL_RAISED"))

    # v1.12: v2 表格追加行 —— 不再熔断，且按 v2 字段映射构造
    try:
        patch = build_archive_patch(
            markdown_text=_fixture_with_table_v2(),
            document_url=build_wiki_url("工具/方法论"),
            category="工具/方法论",
            asset_name="第二条 v2 资产",
            source_topic="工具/方法论 · 归档回归",
            access_link="https://bytedance.larkoffice.com/docx/v2new",
            archive_date="2026-08-21",
        )
        content = patch.modifications[0]["content"]
        ok = (
            patch.schema == SCHEMA_V2
            and patch.asset_id == "IM-260821-002"
            and patch.modifications[0]["modification_type"] == "update"
            and "<td>IM-260821-002</td>" in content
            and '<a href="https://bytedance.larkoffice.com/docx/v2new">第二条 v2 资产</a>' in content
            and "工具 / 方法论 / 归档回归" in content
        )
        cases.append(("append row on v2 schema", "OK_PASS" if ok else "FAIL_BAD_PATCH"))
    except Exception:
        cases.append(("append row on v2 schema", "FAIL_RAISED"))

    # v1.12: RAW 回读断言 = 编号 + 名称 + 链接真实存在
    try:
        patch = build_archive_patch(
            markdown_text=_fixture_with_table_v2(),
            document_url=build_wiki_url("工具/方法论"),
            category="工具/方法论",
            asset_name="回读校验资产",
            source_topic="工具/方法论 · RAW",
            access_link="https://bytedance.larkoffice.com/docx/v2verify",
            archive_date="2026-08-21",
        )
        verify_markdown = (
            "<!-- BLOCK_1 | block-a -->\n## \U0001f4c2 已归档资产<!-- END_BLOCK_1 -->\n"
            f"<!-- BLOCK_2 | block-v2 -->\n{patch.modifications[0]['content'].strip()}\n<!-- END_BLOCK_2 -->\n"
        )
        verify_archive_presence_in_markdown(
            verify_markdown,
            asset_name="回读校验资产",
            access_link="https://bytedance.larkoffice.com/docx/v2verify",
            expected_asset_id=patch.asset_id,
        )
        cases.append(("verify v2 row by id+name+link", "OK_PASS"))
    except Exception:
        cases.append(("verify v2 row by id+name+link", "FAIL_RAISED"))

    try:
        verify_archive_presence_in_markdown(
            _fixture_with_table_v2(),
            asset_name="不存在的资产",
            access_link="https://bytedance.larkoffice.com/docx/nope",
            expected_asset_id="IM-260821-999",
        )
        cases.append(("reject missing v2 row", "FAIL_NOT_RAISED"))
    except WikiArchiveError:
        cases.append(("reject missing v2 row", "OK_RAISED"))

    # v1.12: 单元格锚点幂等（防 markdown 链接方括号累积 / 名称列被清空）
    try:
        ok = (
            _normalize_cell_anchors('<p id="x"><a href="https://u/1">名称</a></p>')
            == '<a href="https://u/1">名称</a>'
            and _normalize_cell_anchors('<p id="x"><a href="https://u/1">[名称]</a></p>')
            == '<a href="https://u/1">名称</a>'
            and _normalize_cell_anchors('<p id="x">纯文本</p>') == "纯文本"
        )
        cases.append(("cell anchor round-trip idempotent", "OK_PASS" if ok else "FAIL_BAD_VALUE"))
    except Exception:
        cases.append(("cell anchor round-trip idempotent", "FAIL_RAISED"))

    print("=== wiki_archive_guard selftest ===")
    failed = 0
    for name, status in cases:
        print(f"- {name}: {status}")
        if not status.startswith("OK"):
            failed += 1
    if failed:
        print(f"FAILED ({failed}/{len(cases)})")
        return 2
    print(f"PASSED ({len(cases)} cases)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true", help="运行内置自检")
    subparsers = parser.add_subparsers(dest="command")

    common_parent = argparse.ArgumentParser(add_help=False)
    common_parent.add_argument("--category", help="用户显式指定的分类，优先级最高")
    common_parent.add_argument("--inferred-category", help="未显式指定时，LLM 推断出的分类")
    common_parent.add_argument("--asset-name", required=True, help="归档资产名称")
    common_parent.add_argument("--source-topic", required=True, help="来源/主题")
    common_parent.add_argument("--access-link", required=True, help="飞书文档直达链接")
    common_parent.add_argument("--archive-date", help="归档日期，默认当天 YYYY-MM-DD")
    common_parent.add_argument("--tags", help="标签列（v2 schema）；不传则由分类名 + 主题关键词自动生成")

    prepare = subparsers.add_parser("prepare", parents=[common_parent], help="基于本地 .lark.md 生成 MCP 修改补丁")
    prepare.add_argument("--markdown-file", required=True, help="已下载的飞书 Markdown 文件绝对路径")
    prepare.add_argument("--document-url", help="目标文档 URL；不传则根据分类映射自动生成 wiki URL")

    archive = subparsers.add_parser("archive", parents=[common_parent], help="直接执行远端 Wiki 归档（飞书 MCP 路径）")
    archive.add_argument(
        "--target-doc",
        help="【仅供验证】把写入重定向到指定临时 Docx URL，替代分类映射出的正式归档节点",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.selftest:
        return _selftest()

    if args.command == "prepare":
        markdown_file = Path(args.markdown_file).resolve()
        if not markdown_file.exists():
            raise WikiArchiveError(f"prepare 失败：markdown 文件不存在：{markdown_file}")
        result = prepare_archive_from_file(
            markdown_file=markdown_file,
            category=args.category,
            inferred_category=args.inferred_category,
            asset_name=args.asset_name,
            source_topic=args.source_topic,
            access_link=args.access_link,
            archive_date=args.archive_date,
            document_url=args.document_url,
            tags=args.tags,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "archive":
        result = archive_to_wiki(
            category=args.category,
            inferred_category=args.inferred_category,
            asset_name=args.asset_name,
            source_topic=args.source_topic,
            access_link=args.access_link,
            archive_date=args.archive_date,
            tags=args.tags,
            target_doc=getattr(args, "target_doc", None),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except WikiArchiveError as exc:
        print(f"FAILED\n- error: {exc}")
        raise SystemExit(2)
