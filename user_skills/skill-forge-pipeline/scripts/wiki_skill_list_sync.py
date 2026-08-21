#!/usr/bin/env python3
"""Wiki「技能存量清单」表格 Upsert 钩子 (Forge Pipeline V5.24)

背景
----
forge 长期只同步「专属技能清单」Sheet（DEFAULT_SSOT_SPREADSHEET_TOKEN），
而飞书 Wiki 上给人看的「一、技能存量清单 (Skill Registry)」表格无人维护，
导致 Wiki 三个月未更新、覆盖率一度只有 31.4%。本模块把这张表纳入 forge 闭环。

契约
----
* 目标：Wiki 页面「一、技能存量清单 (Skill Registry)」下方的 6 列表格。
* 主键：**技能名称列**（精确匹配，去空白）。
* 已存在 → 更新「访问链接」（若本次 forge 有说明文档 URL）+「归档日期」（本次 forge 日期）。
* 不存在 → tbody 末尾追加一行，序号 = 现有最大序号 + 1，缺链接填 `⚠️[待补链接]`，
  使用次数填 `-`。
* 幂等：同一技能重复 forge 只会更新原行，绝不新增重复行。
* 写后必须 sleep 2s + `docs +fetch --doc-format markdown` RAW 回读断言
  （行数符合预期 + 目标技能名恰好出现 1 次）；断言失败即 raise。

版本号写入的取舍（重要）
------------------------
现表结构固定为 6 列：序号 | 技能名称 | 简介（≤20 字）| 访问链接 | 归档日期 | 近30天使用次数，
**没有独立版本列**。可选方案有三：
  A. 新增「版本」列 —— 会改动 colgroup 与全部 51 行结构，破坏面最大，且属于擅自改表；
  B. 把版本号追加进「简介」列尾部 —— 简介列限宽 80px、要求 ≤20 字，
     且这一列是人工撰写的沉淀资产（同 doc zone 的 Preserve 语义），机器追加会挤爆并覆盖人工文案；
  C. 不写版本号 —— 版本号的权威载体是 `SKILL.md` frontmatter（SSOT）+「专属技能清单」Sheet
     的【版本号】列，两处均已由 forge 同步；Wiki 这张表的定位是「给人扫读的导航索引」。
按「不破坏现有 6 列结构」为最高优先级，本实现选择 **C**：不写版本号、不增列、
不改写既有「简介」文案，只维护机器可安全托管的两个字段（访问链接 / 归档日期）。
若未来表结构新增版本列，`_upsert_rows()` 会自动识别表头并写入（见 VERSION_HEADERS）。
"""

from __future__ import annotations

import argparse
import datetime
import html
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

DEFAULT_WIKI_URL = "https://bytedance.larkoffice.com/wiki/GU0ewkyaGi4i5nkwBtNcM3aPn9g"
REGISTRY_HEADING_KEYWORD = "技能存量清单"
NAME_HEADERS = ["技能名称", "技能名", "name", "Name"]
LINK_HEADERS = ["访问链接", "链接", "说明文档", "url", "URL"]
DATE_HEADERS = ["归档日期", "日期", "更新日期"]
USAGE_HEADERS = ["近30天使用次数", "使用次数"]
DESC_HEADERS = ["简介（≤20 字）", "简介"]
VERSION_HEADERS = ["版本号", "版本", "version", "Version"]
MISSING_LINK_PLACEHOLDER = "⚠️[待补链接]"
UNKNOWN_USAGE_PLACEHOLDER = "-"
DESC_MAX_LEN = 20
READBACK_WAIT_SECONDS = 2

_BARE_AMP_RE = re.compile(r"&(?!#\d+;|#x[0-9A-Fa-f]+;|[A-Za-z][A-Za-z0-9]*;)")


class WikiSyncError(RuntimeError):
    """Wiki 存量清单同步失败（含写后回读断言失败）。"""


# --------------------------------------------------------------------------- #
# 低层通道：一律走 AIME 定制版 lark-cli（MCP-Only Law），禁止裸调 OpenAPI
# --------------------------------------------------------------------------- #
def _run(command: List[str], action: str) -> str:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise WikiSyncError(
            f"{action} failed with exit code {result.returncode}\n"
            f"CMD: {' '.join(command)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout.strip()


def fetch_doc_xml(doc_url: str) -> str:
    """拉取带 block id 的文档 XML —— 唯一权威结构来源，禁止盲写。"""

    return _run(
        [
            "lark-cli", "docs", "+fetch",
            "--as", "user",
            "--doc", doc_url,
            "--doc-format", "xml",
            "--detail", "with-ids",
            "-q", ".data.document.content",
        ],
        "fetch wiki doc xml with block ids",
    )


def fetch_doc_markdown(doc_url: str) -> str:
    return _run(
        [
            "lark-cli", "docs", "+fetch",
            "--as", "user",
            "--doc", doc_url,
            "--doc-format", "markdown",
            "-q", ".data.document.content",
        ],
        "fetch wiki doc markdown for readback assert",
    )


def block_replace(doc_url: str, block_id: str, content: str) -> str:
    return _run(
        [
            "lark-cli", "docs", "+update",
            "--as", "user",
            "--doc", doc_url,
            "--command", "block_replace",
            "--block-id", block_id,
            "--doc-format", "xml",
            "--content", content,
        ],
        "block_replace wiki registry table",
    )


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def sanitize_doc_xml(doc_xml: str) -> str:
    """把非法实体的裸 `&` 补成 `&amp;`（标题与 href 常带未转义 &，严格 XML 解析必崩）。"""

    return _BARE_AMP_RE.sub("&amp;", doc_xml)


def _cell_text(cell: ET.Element) -> str:
    return "".join(cell.itertext()).strip()


def _cell_href(cell: ET.Element) -> str:
    link = cell.find(".//a")
    if link is not None:
        return (link.get("href") or "").strip()
    return ""


def locate_registry_table(doc_xml: str) -> Dict[str, Any]:
    """定位「技能存量清单」标题之后的第一张表格。

    表格 block id 每次 block_replace 后都会变化，因此必须每次动态解析，禁止硬编码。
    """

    # 文档 XML 是「多个顶层兄弟节点」而非单根，需套一层合成 root 才能被严格解析。
    root = ET.fromstring("<forge-root>" + sanitize_doc_xml(doc_xml) + "</forge-root>")
    children = list(root)
    heading_idx = -1
    for idx, node in enumerate(children):
        if re.fullmatch(r"h[1-9]", node.tag, re.I) and REGISTRY_HEADING_KEYWORD in "".join(node.itertext()):
            heading_idx = idx
            break
    if heading_idx < 0:
        raise WikiSyncError(f"registry heading not found (keyword={REGISTRY_HEADING_KEYWORD!r})")

    table = None
    for node in children[heading_idx + 1:]:
        if node.tag == "table":
            table = node
            break
        if re.fullmatch(r"h[1-2]", node.tag, re.I):
            break  # 已跨到下一章节，说明该章节没有表格
    if table is None:
        raise WikiSyncError("registry table not found under heading")

    table_id = table.get("id") or ""
    if not table_id:
        raise WikiSyncError("registry table has no block id")

    widths = [c.get("width") or "" for c in table.findall("./colgroup/col")]
    headers = [_cell_text(th) for th in table.findall("./thead/tr/th")]
    rows: List[List[Dict[str, str]]] = []
    for tr in table.findall("./tbody/tr"):
        rows.append([{"text": _cell_text(td), "href": _cell_href(td)} for td in tr.findall("./td")])
    return {
        "table_id": table_id,
        "heading_id": children[heading_idx].get("id") or "",
        "widths": widths,
        "headers": headers,
        "rows": rows,
    }


def _find_col(headers: List[str], candidates: List[str]) -> Optional[int]:
    norm = [re.sub(r"\s+", "", h) for h in headers]
    for cand in candidates:
        key = re.sub(r"\s+", "", cand)
        for idx, h in enumerate(norm):
            if h == key:
                return idx
    for cand in candidates:
        key = re.sub(r"\s+", "", cand)
        for idx, h in enumerate(norm):
            if key and key in h:
                return idx
    return None


# --------------------------------------------------------------------------- #
# Upsert 逻辑（纯函数，便于离线自检）
# --------------------------------------------------------------------------- #
def _upsert_rows(
    table: Dict[str, Any],
    *,
    skill_name: str,
    doc_url: str,
    archived_date: str,
    desc: str = "",
    version: str = "",
) -> Dict[str, Any]:
    headers: List[str] = table["headers"]
    # 深拷贝：单元格 dict 不共享，避免 upsert 反向污染调用方传入的 table 快照。
    rows: List[List[Dict[str, str]]] = [[dict(c) for c in r] for r in table["rows"]]
    ncol = len(headers)

    idx_no = 0
    idx_name = _find_col(headers, NAME_HEADERS)
    idx_link = _find_col(headers, LINK_HEADERS)
    idx_date = _find_col(headers, DATE_HEADERS)
    idx_usage = _find_col(headers, USAGE_HEADERS)
    idx_desc = _find_col(headers, DESC_HEADERS)
    idx_version = _find_col(headers, VERSION_HEADERS)  # 现表无此列 → None（见模块 docstring 取舍 C）
    if idx_name is None:
        raise WikiSyncError(f"skill name column not found in headers={headers}")

    target = skill_name.strip()
    matched = [r for r in rows if r[idx_name]["text"].strip() == target] if rows else []
    if len(matched) > 1:
        raise WikiSyncError(f"duplicate rows for skill {target!r} ({len(matched)}) — 需人工先去重")

    action = ""
    if matched:
        row = matched[0]
        action = "updated"
        if doc_url and idx_link is not None:
            row[idx_link] = {"text": f"{target} 说明文档", "href": doc_url}
        if idx_date is not None:
            row[idx_date] = {"text": archived_date, "href": ""}
        # 简介列属人工沉淀，机器不覆盖（Preserve 语义）。
        if version and idx_version is not None:
            row[idx_version] = {"text": version, "href": ""}
    else:
        action = "appended"
        max_no = 0
        for r in rows:
            m = re.search(r"\d+", r[idx_no]["text"])
            if m:
                max_no = max(max_no, int(m.group()))
        new_row: List[Dict[str, str]] = [{"text": "", "href": ""} for _ in range(ncol)]
        new_row[idx_no] = {"text": str(max_no + 1), "href": ""}
        new_row[idx_name] = {"text": target, "href": ""}
        if idx_desc is not None:
            new_row[idx_desc] = {"text": (desc or "").strip()[:DESC_MAX_LEN], "href": ""}
        if idx_link is not None:
            new_row[idx_link] = (
                {"text": f"{target} 说明文档", "href": doc_url}
                if doc_url
                else {"text": MISSING_LINK_PLACEHOLDER, "href": ""}
            )
        if idx_date is not None:
            new_row[idx_date] = {"text": archived_date, "href": ""}
        if idx_usage is not None:
            new_row[idx_usage] = {"text": UNKNOWN_USAGE_PLACEHOLDER, "href": ""}
        if version and idx_version is not None:
            new_row[idx_version] = {"text": version, "href": ""}
        rows.append(new_row)

    return {"action": action, "rows": rows}


def _esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def render_table_xml(table: Dict[str, Any], rows: List[List[Dict[str, str]]]) -> str:
    """重建整表 XML（不带任何 id 属性 —— block_replace 的 content 要求）。"""

    parts = ["<table>"]
    if table["widths"]:
        parts.append("<colgroup>" + "".join(f'<col width="{w}"/>' for w in table["widths"]) + "</colgroup>")
    parts.append(
        "<thead><tr>"
        + "".join(f'<th vertical-align="top"><p>{_esc(h)}</p></th>' for h in table["headers"])
        + "</tr></thead>"
    )
    parts.append("<tbody>")
    for row in rows:
        cells = []
        for cell in row:
            text = cell.get("text", "")
            href = cell.get("href", "")
            inner = f'<a href="{_esc(href)}">{_esc(text)}</a>' if href else _esc(text)
            cells.append(f'<td vertical-align="top"><p>{inner}</p></td>')
        parts.append("<tr>" + "".join(cells) + "</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# L3 写后回读断言
# --------------------------------------------------------------------------- #
def assert_wiki_registry_synced(doc_url: str, skill_name: str, expected_rows: int) -> Dict[str, Any]:
    markdown = fetch_doc_markdown(doc_url)
    target = skill_name.strip()
    occurrences = len(
        [
            line
            for line in markdown.splitlines()
            if line.lstrip().startswith("|") and re.search(rf"\|\s*{re.escape(target)}\s*\|", line)
        ]
    )
    if occurrences != 1:
        raise WikiSyncError(
            f"readback assert failed: skill {target!r} appears in {occurrences} table rows (expected exactly 1)"
        )

    doc_xml = fetch_doc_xml(doc_url)
    table = locate_registry_table(doc_xml)
    actual_rows = len(table["rows"])
    if actual_rows != expected_rows:
        raise WikiSyncError(
            f"readback assert failed: registry rows={actual_rows}, expected={expected_rows}"
        )
    return {
        "rows": actual_rows,
        "name_occurrences": occurrences,
        "table_id": table["table_id"],
    }


# --------------------------------------------------------------------------- #
# 唯一编排入口
# --------------------------------------------------------------------------- #
def sync_wiki_skill_list(
    skill_name: str,
    *,
    doc_url: str = "",
    desc: str = "",
    version: str = "",
    wiki_url: str = DEFAULT_WIKI_URL,
    archived_date: str = "",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """把本次 forge 的技能 upsert 进 Wiki「技能存量清单」表格。

    返回 dict（含 action / rows / table_id / assert 证据）。任何写后回读断言失败都会
    raise WikiSyncError —— 调用方（register_skill.py）负责把它降级为 WARNING，
    但**本函数内部绝不假装成功**。
    """

    archived_date = archived_date or datetime.datetime.now().strftime("%Y-%m-%d")
    doc_xml = fetch_doc_xml(wiki_url)
    table = locate_registry_table(doc_xml)
    before_rows = len(table["rows"])
    result = _upsert_rows(
        table,
        skill_name=skill_name,
        doc_url=doc_url,
        archived_date=archived_date,
        desc=desc,
        version=version,
    )
    rows = result["rows"]
    expected_rows = len(rows)
    payload = render_table_xml(table, rows)

    plan = {
        "wiki_url": wiki_url,
        "table_id": table["table_id"],
        "headers": table["headers"],
        "action": result["action"],
        "rows_before": before_rows,
        "rows_after": expected_rows,
        "archived_date": archived_date,
        "doc_url": doc_url,
    }
    if dry_run:
        plan["dry_run"] = True
        plan["payload_bytes"] = len(payload)
        return plan

    block_replace(wiki_url, table["table_id"], payload)
    time.sleep(READBACK_WAIT_SECONDS)
    plan["assert"] = assert_wiki_registry_synced(wiki_url, skill_name, expected_rows)
    plan["synced"] = True
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Wiki「技能存量清单」表格 Upsert")
    parser.add_argument("--skill-name", required=True)
    parser.add_argument("--doc-url", default="", help="本次 forge 的说明文档 URL（可空）")
    parser.add_argument("--desc", default="", help="新增行时写入的简介（≤20 字）")
    parser.add_argument("--version", default="", help="仅在表格存在版本列时写入")
    parser.add_argument("--wiki-url", default=DEFAULT_WIKI_URL)
    parser.add_argument("--archived-date", default="", help="默认今天 YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="零副作用：只打印 upsert 计划")
    parser.add_argument("--verify-only", action="store_true", help="只做回读断言（需配 --expect-rows）")
    parser.add_argument("--expect-rows", type=int, default=0)
    args = parser.parse_args()

    if args.verify_only:
        if not args.expect_rows:
            raise SystemExit("--verify-only requires --expect-rows")
        print(assert_wiki_registry_synced(args.wiki_url, args.skill_name, args.expect_rows))
        return 0

    report = sync_wiki_skill_list(
        args.skill_name,
        doc_url=args.doc_url,
        desc=args.desc,
        version=args.version,
        wiki_url=args.wiki_url,
        archived_date=args.archived_date,
        dry_run=args.dry_run,
    )
    import json

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
