#!/usr/bin/env python3
"""离线自检：Wiki「技能存量清单」Upsert 纯函数（不触网）。

覆盖：表格定位、主键匹配更新、追加新行序号递增、幂等（重复 forge 不产生重复行）、
缺链接占位符、重复行熔断、XML 重建不带 id、& 转义。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wiki_skill_list_sync import (  # noqa: E402
    MISSING_LINK_PLACEHOLDER,
    UNKNOWN_USAGE_PLACEHOLDER,
    WikiSyncError,
    _upsert_rows,
    locate_registry_table,
    render_table_xml,
)

HEADERS = ["序号", "技能名称", "简介（≤20 字）", "访问链接", "归档日期", "近30天使用次数"]


def _row_xml(no: str, name: str, desc: str, link: str, date: str, usage: str) -> str:
    link_cell = f'<a href="{link}">{name} 说明文档</a>' if link else MISSING_LINK_PLACEHOLDER
    cells = [no, name, desc, link_cell, date, usage]
    return "<tr>" + "".join(f'<td vertical-align="top"><p>{c}</p></td>' for c in cells) + "</tr>"


def _doc_xml(rows_xml: str) -> str:
    thead = "<thead><tr>" + "".join(f"<th><p>{h}</p></th>" for h in HEADERS) + "</tr></thead>"
    colgroup = "<colgroup>" + "".join(
        f'<col width="{w}"/>' for w in [78, 273, 80, 273, 119, 78]
    ) + "</colgroup>"
    return (
        '<title id="t">Aime 技能库</title>'
        '<h2 id="h1">一、技能存量清单 (Skill Registry)</h2>'
        f'<table id="tbl">{colgroup}{thead}<tbody>{rows_xml}</tbody></table>'
        '<h2 id="h2">二、其它</h2>'
    )


BASE = _doc_xml(
    _row_xml("1", "alpha-skill", "甲技能", "https://x/docx/A", "2026-01-01", "3")
    + _row_xml("2", "skill-forge-pipeline", "技能锻造流水线", "https://x/docx/B", "2026-05-20", "19")
)

failures: list[str] = []


def check(label: str, cond: bool) -> None:
    print(("✅ " if cond else "❌ ") + label)
    if not cond:
        failures.append(label)


def main() -> int:
    t = locate_registry_table(BASE)
    check("locate: table_id 动态解析", t["table_id"] == "tbl")
    check("locate: 6 列表头", t["headers"] == HEADERS)
    check("locate: 2 行 tbody", len(t["rows"]) == 2)
    check("locate: 链接 href 解析", t["rows"][1][3]["href"] == "https://x/docx/B")

    # 1) 已存在 -> updated，行数不变，归档日期与链接被更新，简介不动
    r = _upsert_rows(
        t, skill_name="skill-forge-pipeline", doc_url="https://x/docx/NEW", archived_date="2026-08-22"
    )
    row = r["rows"][1]
    check("update: action=updated", r["action"] == "updated")
    check("update: 行数不变（幂等）", len(r["rows"]) == 2)
    check("update: 归档日期被刷新", row[4]["text"] == "2026-08-22")
    check("update: 链接被刷新", row[3]["href"] == "https://x/docx/NEW")
    check("update: 简介（人工沉淀）未被覆盖", row[2]["text"] == "技能锻造流水线")

    # 2) 幂等：对更新后的表再跑一次，仍是 updated 且行数不变
    t2 = locate_registry_table(_doc_xml("".join(
        _row_xml(
            c[0]["text"], c[1]["text"], c[2]["text"], c[3]["href"], c[4]["text"], c[5]["text"]
        ) for c in r["rows"]
    )))
    r2 = _upsert_rows(t2, skill_name="skill-forge-pipeline", doc_url="https://x/docx/NEW",
                      archived_date="2026-08-22")
    check("idempotent: 二次 forge 仍 updated / 不增行", r2["action"] == "updated" and len(r2["rows"]) == 2)

    # 3) 不存在 -> appended，序号 = max+1，缺链接占位符，使用次数 -
    r3 = _upsert_rows(t, skill_name="brand-new-skill", doc_url="", archived_date="2026-08-22",
                      desc="一个很长很长很长很长很长很长的简介文案")
    new = r3["rows"][-1]
    check("append: action=appended", r3["action"] == "appended")
    check("append: 行数 +1", len(r3["rows"]) == 3)
    check("append: 序号 = max+1", new[0]["text"] == "3")
    check("append: 缺链接占位符", new[3]["text"] == MISSING_LINK_PLACEHOLDER and not new[3]["href"])
    check("append: 使用次数占位符", new[5]["text"] == UNKNOWN_USAGE_PLACEHOLDER)
    check("append: 简介截断 ≤20 字", len(new[2]["text"]) <= 20 and new[2]["text"].startswith("一个很长"))

    # 4) 重复行熔断
    dup = locate_registry_table(_doc_xml(
        _row_xml("1", "dup-skill", "x", "https://x/a", "2026-01-01", "1")
        + _row_xml("2", "dup-skill", "y", "https://x/b", "2026-01-02", "2")
    ))
    try:
        _upsert_rows(dup, skill_name="dup-skill", doc_url="", archived_date="2026-08-22")
        check("duplicate: 应熔断", False)
    except WikiSyncError:
        check("duplicate: 重复行熔断", True)

    # 5) 重建 XML：不带 id、保留 colgroup、& 转义
    xml = render_table_xml(t, r["rows"])
    check("render: 不含 id 属性", " id=" not in xml)
    check("render: 保留 colgroup 宽度", '<col width="273"/>' in xml)
    amp = _upsert_rows(t, skill_name="amp&skill", doc_url="https://x/a?b=1&c=2",
                       archived_date="2026-08-22")
    xml2 = render_table_xml(t, amp["rows"])
    check("render: & 被转义", "&amp;" in xml2 and "&s" not in xml2.replace("&amp;", ""))

    # 6) 缺标题时熔断
    try:
        locate_registry_table('<h2 id="x">别的章节</h2><p id="y">无表</p>')
        check("missing heading: 应熔断", False)
    except WikiSyncError:
        check("missing heading: 熔断", True)

    print(f"\n{'FAILED: ' + str(failures) if failures else 'ALL PASSED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
