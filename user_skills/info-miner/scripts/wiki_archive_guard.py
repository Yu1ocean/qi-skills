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
DEFAULT_TABLE_HEADERS: tuple[str, ...] = ("序号", "归档日期", "资产名称", "来源/主题", "访问链接")
DEFAULT_TABLE_COL_WIDTHS: str = "60,110,260,200,200"
DEFAULT_VERIFY_AFTER_WRITE: bool = True
DEFAULT_LARK_DOMAIN: str = "https://bytedance.larkoffice.com"
DEFAULT_WRITE_DELAY_SECONDS: int = 2
DEFAULT_ALLOWED_LINK_SEGMENTS: tuple[str, ...] = ("/docx/", "/docs/", "/wiki/", "/file/")
DEFAULT_ALLOWED_MARKDOWN_SUFFIXES: tuple[str, ...] = (".lark.md", ".md")
DEFAULT_REQUIRE_SECRETS_FOR_REMOTE_WRITE: bool = True

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


def _extract_table_rows(table_html: str) -> List[List[str]]:
    rows: List[List[str]] = []
    for row_html in _ROW_RE.findall(table_html):
        cells = [_strip_html_tags(cell) for cell in _CELL_RE.findall(row_html)]
        if cells:
            rows.append(cells)
    return rows


def validate_archive_table_headers(table_html: str) -> None:
    rows = _extract_table_rows(table_html)
    if not rows:
        raise WikiArchiveError("归档熔断：已归档资产表格为空，无法确认表头。")
    headers = rows[0]
    expected = list(DEFAULT_TABLE_HEADERS)
    if headers != expected:
        raise WikiArchiveError(
            "归档熔断：已归档资产表格表头不符合约定。"
            f"期望：{expected}；实际：{headers}。"
        )


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


def build_archive_row(index: int, archive_date: str, asset_name: str, source_topic: str, access_link: str) -> str:
    safe_asset_name = html.escape(asset_name, quote=False)
    safe_source_topic = html.escape(source_topic, quote=False)
    return (
        "    <tr>\n"
        f"        <td>{index}</td>\n"
        f"        <td>{archive_date}</td>\n"
        f"        <td>{safe_asset_name}</td>\n"
        f"        <td>{safe_source_topic}</td>\n"
        f"        <td>[打开文档]({access_link})</td>\n"
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


def build_archive_table(row_html: str) -> str:
    header_cells = "\n".join(f"        <td>{header}</td>" for header in DEFAULT_TABLE_HEADERS)
    return (
        f'<table header-row="true" col-widths="{DEFAULT_TABLE_COL_WIDTHS}">\n'
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
        next_index = next_archive_index(current_table)
        row_html = build_archive_row(next_index, archive_date, asset_name, source_topic, access_link)
        new_content = append_row_to_table(current_table, row_html)
        modifications = [
            {
                "block_number": blocks[table_idx].number,
                "block_id": blocks[table_idx].block_id,
                "content": new_content + "\n",
                "modification_type": "update",
            }
        ]
        return ArchivePatch(category=category, document_url=document_url, next_index=next_index, modifications=modifications)

    next_index = 1
    row_html = build_archive_row(next_index, archive_date, asset_name, source_topic, access_link)
    new_table = build_archive_table(row_html)
    anchor_idx = find_insert_anchor_index(blocks, heading_idx, section_end_idx)
    modifications = [
        {
            "block_number": blocks[anchor_idx].number,
            "block_id": blocks[anchor_idx].block_id,
            "content": new_table + "\n",
            "modification_type": "insert",
        }
    ]
    return ArchivePatch(category=category, document_url=document_url, next_index=next_index, modifications=modifications)


def verify_archive_presence_in_markdown(
    markdown_text: str,
    *,
    asset_name: str,
    access_link: str,
    expected_index: Optional[int] = None,
) -> None:
    blocks = parse_blocks(markdown_text)
    heading_idx = find_archive_heading_index(blocks)
    section_end_idx = find_section_end_index(blocks, heading_idx)
    table_idx = find_existing_table_block_index(blocks, heading_idx, section_end_idx)
    if table_idx is None:
        raise WikiArchiveError("归档熔断：RAW 回读未检测到『已归档资产』表格。")

    table_html = blocks[table_idx].content
    if asset_name not in table_html or access_link not in table_html:
        raise WikiArchiveError(
            "归档熔断：RAW 回读未找到刚写入的资产名称或访问链接。"
            f" asset_name={asset_name!r}, access_link={access_link!r}"
        )

    if expected_index is not None:
        rows = _extract_table_rows(table_html)
        target_found = any(len(row) >= 5 and row[0] == str(expected_index) and row[2] == asset_name for row in rows[1:])
        if not target_found:
            raise WikiArchiveError(
                "归档熔断：RAW 回读未找到期望序号的新归档行。"
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
    workspace_root = get_workspace_root()
    download_script = resolve_existing_script(
        [
            workspace_root / "inner_skills/lark/mcp_lark_lark_download.py",
            workspace_root / "inner_skills/lark_download/lark_download.py",
        ],
        "下载",
    )

    output = run_subprocess(
        ["python3", str(download_script), json.dumps({"document_url": document_url}, ensure_ascii=False)],
        f"lark download via {download_script}",
    )
    paths = parse_download_paths(output)
    if not paths:
        raise WikiArchiveError(f"归档熔断：无法从 Lark 下载输出中解析文件路径。输出：{output}")

    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if path.exists() and path.name.endswith(DEFAULT_ALLOWED_MARKDOWN_SUFFIXES):
            return path
    raise WikiArchiveError(f"归档熔断：Lark 下载结果中未找到可用 Markdown 文件：{paths}")


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
    )
    return {
        "category": patch.category,
        "document_url": patch.document_url,
        "wiki_node_token": CATEGORY_NODE_MAP[patch.category],
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
) -> Dict[str, Any]:
    if DEFAULT_ARCHIVE_REQUIRED is not True:
        raise WikiArchiveError("归档熔断：DEFAULT_ARCHIVE_REQUIRED 被关闭，违反 info-miner 闭环归档约束。")
    require_secrets()

    canonical_category = normalize_category(category, inferred_category)
    document_url = build_wiki_url(canonical_category)
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
        )

    return {
        "category": prepared["category"],
        "document_url": prepared["document_url"],
        "wiki_node_token": prepared["wiki_node_token"],
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
        <td>[打开文档](https://bytedance.larkoffice.com/docx/old)</td>
    </tr>
</table>
<!-- END_BLOCK_3 -->
"""


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
            """<table header-row=\"true\" col-widths=\"60,110,260,200,200\">\n    <tr>\n        <td>序号</td>\n        <td>归档日期</td>\n        <td>资产名称</td>\n        <td>来源/主题</td>\n        <td>访问链接</td>\n    </tr>\n    <tr>\n        <td>1</td>\n        <td>2026-05-20</td>\n        <td>既有资产</td>\n        <td>AI/Agent · 既有案例</td>\n        <td>[打开文档](https://bytedance.larkoffice.com/docx/old)</td>\n    </tr>\n</table>""",
            build_archive_row(2, "2026-05-20", "第二条资产", "AI/Agent · 归档测试", "https://bytedance.larkoffice.com/docx/test456"),
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

    prepare = subparsers.add_parser("prepare", parents=[common_parent], help="基于本地 .lark.md 生成 MCP 修改补丁")
    prepare.add_argument("--markdown-file", required=True, help="已下载的飞书 Markdown 文件绝对路径")
    prepare.add_argument("--document-url", help="目标文档 URL；不传则根据分类映射自动生成 wiki URL")

    subparsers.add_parser("archive", parents=[common_parent], help="直接执行远端 Wiki 归档（飞书 MCP 路径）")
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
