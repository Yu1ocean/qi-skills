#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate v1-compatible skill heatmap counts and write them back to the Skill Registry wiki table.

Design goals:
- Keep the legacy `heat_probe.py` slug-matching heuristic as the default counting path.
- Do NOT switch to trace-content parsing even if `trace.jsonl` becomes readable later.
- Only count and write back the 16 skills currently registered in the Skill Registry table.
- Update the target Lark/Wiki document strictly through MCP wrapper scripts.
- Perform RAW readback verification after writeback.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

DEFAULT_DOC_URL = "https://bytedance.larkoffice.com/docx/AKmddboNJos7RcxGiOlcoWCvnjd"

SKILLS_IN_SCOPE: List[str] = [
    "zero-trust-data-analyzer",
    "zero-trust-qa-checker",
    "periodic-report-generator",
    "skill-forge-pipeline-v4",
    "v6-panoramic-chart-generator",
    "cyber-inspiration-generator",
    "omni-asset-archiver",
    "feishu-doc-writing-guide",
    "smart-scheduler",
    "merchant-tier-analyzer",
    "task-flow-engine",
    "info-miner",
    "pro-task-planner",
    "heartbeat-inspector",
    "internet-insight-analyzer",
    "agatha-ai-novelist",
]

LEGACY_ALIAS_MAP: Dict[str, List[str]] = {
    "agatha-ai-novelist": ["agatha", "novelist", "novel"],
    "cyber-inspiration-generator": [
        "cyber_inspiration",
        "cyber-inspiration",
        "inspiration_gen",
        "ep_card",
        "ep-card",
        "epcard",
    ],
    "feishu-doc-writing-guide": [
        "feishu_doc",
        "feishu-doc",
        "doc_writing",
        "lark_doc_write",
        "feishu_writing",
        "doc_write",
    ],
    "heartbeat-inspector": ["heartbeat", "inspector_patrol", "patrol_heartbeat"],
    "info-miner": ["info_miner", "info-miner", "infominer", "miner"],
    "internet-insight-analyzer": ["internet_insight", "insight_analyzer", "external_insight"],
    "merchant-tier-analyzer": ["merchant_tier", "tier_analyzer", "merchant-tier", "skm_hipo", "skm-hipo"],
    "omni-asset-archiver": ["omni_asset", "asset_archiver", "archive", "archiver", "library_archive"],
    "periodic-report-generator": [
        "daily_report",
        "weekly_report",
        "periodic_report",
        "weekly_review",
        "daily-report",
        "weekly-report",
    ],
    "pro-task-planner": ["task_planner", "pro_task", "plan_steps", "task-plan"],
    "skill-forge-pipeline-v4": ["skill_forge", "skill-forge", "forge_pipeline", "forge"],
    "smart-scheduler": ["smart_scheduler", "scheduler", "appointment", "calendar_schedule"],
    "task-flow-engine": ["task_flow", "taskflow", "task-flow", "flow_engine"],
    "v6-panoramic-chart-generator": ["panoramic_chart", "v6_chart", "panoramic", "chart_generator"],
    "zero-trust-data-analyzer": ["zero_trust_data", "zero-trust-data", "ztda", "data_analyzer"],
    "zero-trust-qa-checker": ["zero_trust_qa", "qa_checker", "qa_patrol", "ztqa", "zerotrust_qa"],
}

EXPECTED_V1_COUNTS: Dict[str, int] = {
    "info-miner": 41,
    "zero-trust-qa-checker": 38,
    "periodic-report-generator": 37,
    "omni-asset-archiver": 31,
    "skill-forge-pipeline-v4": 19,
    "smart-scheduler": 18,
    "heartbeat-inspector": 11,
    "task-flow-engine": 11,
    "agatha-ai-novelist": 8,
    "feishu-doc-writing-guide": 8,
    "cyber-inspiration-generator": 6,
    "merchant-tier-analyzer": 5,
    "pro-task-planner": 2,
    "internet-insight-analyzer": 0,
    "v6-panoramic-chart-generator": 0,
    "zero-trust-data-analyzer": 0,
}

HEAT_INDEX_CANDIDATES = [
    "AIME_武器热度榜_v1.0_·_Weapon_Heat_Index.lark.md",
    "aime_weapon_heat_index_v1.lark.md",
]


class HeatmapError(RuntimeError):
    """Domain-specific fatal error."""


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def output_root() -> Path:
    out = skill_root() / "output"
    out.mkdir(parents=True, exist_ok=True)
    return out


def normalize_slug(text: str) -> str:
    return text.lower().replace("-", "_")


def run_mcp_script(script_relative_path: str, payload: Dict[str, object]) -> str:
    script_path = workspace_root() / script_relative_path
    if not script_path.exists():
        raise HeatmapError(f"未找到 MCP 脚本: {script_path}")

    cmd = [sys.executable, str(script_path), json.dumps(payload, ensure_ascii=False)]
    proc = subprocess.run(
        cmd,
        cwd=str(workspace_root()),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise HeatmapError(
            f"调用 MCP 脚本失败: {script_relative_path}\n"
            f"payload={json.dumps(payload, ensure_ascii=False)}\n"
            f"stdout={proc.stdout}\n"
            f"stderr={proc.stderr}"
        )
    return proc.stdout.strip()


def parse_downloaded_file_path(tool_output: str) -> Path:
    match = re.search(r'file_path:\s*"([^"]+)"', tool_output)
    if not match:
        raise HeatmapError(f"无法从下载输出中解析 file_path:\n{tool_output}")
    return Path(match.group(1))


def download_doc(doc_url: str) -> Path:
    output = run_mcp_script(
        "inner_skills/lark/mcp_lark_lark_download.py",
        {"document_url": doc_url},
    )
    return parse_downloaded_file_path(output)


def update_doc(doc_url: str, markdown_file_path: Path, modifications: List[Dict[str, str]]) -> str:
    payload = {
        "document_url": doc_url,
        "markdown_file_path": str(markdown_file_path),
        "modifications": modifications,
    }
    return run_mcp_script("inner_skills/lark/mcp_lark_update_lark_doc.py", payload)


def detect_v1_anchor() -> Tuple[Optional[datetime], Optional[Path], str]:
    for candidate in HEAT_INDEX_CANDIDATES:
        file_path = workspace_root() / candidate
        if not file_path.exists():
            continue
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"探针时间[：:]\*\*\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", text)
        if not match:
            match = re.search(r"探针时间[：:]\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", text)
        if match:
            anchor_time = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M")
            return anchor_time, file_path, "published_heat_index_anchor"

    for file_path in workspace_root().glob("*Heat_Index*.lark.md"):
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"探针时间[：:]\*\*\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", text)
        if match:
            anchor_time = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M")
            return anchor_time, file_path, "published_heat_index_anchor"

    return None, None, "retained_subagent_window"


def scan_v1_counts(anchor_time: Optional[datetime]) -> Dict[str, object]:
    log_root = workspace_root() / ".aime/log/subagent"
    if not log_root.exists():
        raise HeatmapError(f"日志目录不存在: {log_root}")

    all_dirs = sorted([path for path in log_root.iterdir() if path.is_dir()], key=lambda p: p.name)
    scanned_dirs: List[Path] = []
    if anchor_time is None:
        scanned_dirs = all_dirs
    else:
        for path in all_dirs:
            dir_time = datetime.fromtimestamp(path.stat().st_mtime)
            if dir_time <= anchor_time:
                scanned_dirs.append(path)

    hits: Counter[str] = Counter()
    examples: Dict[str, List[str]] = defaultdict(list)
    matched_dir_count = 0

    for path in scanned_dirs:
        normalized_name = normalize_slug(path.name)
        matched_skills: List[str] = []
        for skill in SKILLS_IN_SCOPE:
            aliases = LEGACY_ALIAS_MAP.get(skill, [])
            if any(normalize_slug(alias) in normalized_name for alias in aliases):
                matched_skills.append(skill)
        if matched_skills:
            matched_dir_count += 1
        for skill in matched_skills:
            hits[skill] += 1
            if len(examples[skill]) < 3:
                examples[skill].append(path.name)

    counts = {skill: int(hits.get(skill, 0)) for skill in SKILLS_IN_SCOPE}
    ranking = sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    return {
        "log_root": str(log_root),
        "total_dirs_available": len(all_dirs),
        "dirs_in_window": len(scanned_dirs),
        "matched_dir_count": matched_dir_count,
        "counts": counts,
        "examples": {skill: examples.get(skill, []) for skill in SKILLS_IN_SCOPE},
        "leaderboard": [{"skill": skill, "count": count} for skill, count in ranking],
    }


def render_leaderboard(scan_result: Dict[str, object], anchor_time: Optional[datetime], anchor_mode: str, anchor_file: Optional[Path]) -> str:
    leaderboard = scan_result["leaderboard"]
    examples = scan_result["examples"]
    lines: List[str] = []
    lines.append("══════════════════════════════════════════════")
    lines.append("⚔️ Skill Heatmap Generator · legacy heat_probe v1")
    lines.append("══════════════════════════════════════════════")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"统计口径: slug 启发式（仅目录名，不读取 trace.jsonl 正文）")
    lines.append(f"日志目录: {scan_result['log_root']}")
    lines.append(f"当前保留目录数: {scan_result['total_dirs_available']}")
    lines.append(f"本次窗口目录数: {scan_result['dirs_in_window']}")
    lines.append(f"命中至少 1 个技能别名的目录数: {scan_result['matched_dir_count']}")
    lines.append(f"目标文档: {DEFAULT_DOC_URL}")
    if anchor_time is not None and anchor_file is not None:
        lines.append(
            f"窗口模式: {anchor_mode} | 锚点时间: {anchor_time.strftime('%Y-%m-%d %H:%M')} | 锚点文件: {anchor_file.name}"
        )
    else:
        lines.append(f"窗口模式: {anchor_mode} | 未发现本地热度榜锚点文件，按当前保留窗口统计")
    lines.append("")
    lines.append("排行榜（仅 16 个已登记技能）")
    for index, item in enumerate(leaderboard, start=1):
        skill = item["skill"]
        count = item["count"]
        medal = ""
        if index == 1:
            medal = "🥇 "
        elif index == 2:
            medal = "🥈 "
        elif index == 3:
            medal = "🥉 "
        lines.append(f"{medal}{index:>2}. {skill:<31} {count:>3}")
    lines.append("")
    lines.append("命中样本（每个技能最多展示 3 条）")
    for item in leaderboard:
        skill = item["skill"]
        sample_text = ", ".join(examples.get(skill, [])) or "-"
        lines.append(f"- {skill}: {sample_text}")
    return "\n".join(lines)


def extract_registry_table(markdown_text: str) -> Tuple[str, str, str]:
    pattern = re.compile(
        r"<!--\s*(BLOCK_\d+)\s*\|\s*([^ ]+)\s*-->\s*(<table[^>]*>.*?</table>)\s*<!--\s*END_\1\s*-->",
        re.S,
    )
    for match in pattern.finditer(markdown_text):
        block_number, block_id, table_html = match.groups()
        if "技能名称" in table_html and "近30天使用次数" in table_html:
            return block_number, block_id, table_html
    raise HeatmapError("未在目标文档中找到包含“技能名称 / 近30天使用次数”的 Registry 表格 block")


def rebuild_row(cells: List[str]) -> str:
    lines = ["    <tr>"]
    for cell in cells:
        lines.append(f"        <td>{cell}</td>")
    lines.append("    </tr>")
    return "\n".join(lines)


def patch_registry_table(table_html: str, counts: Dict[str, int]) -> Tuple[str, Dict[str, str], Dict[str, str]]:
    table_match = re.search(r"(<table[^>]*>)(.*?)(</table>)", table_html, re.S)
    if not table_match:
        raise HeatmapError("表格 HTML 结构异常，无法解析 <table>...</table>")

    table_open, table_inner, table_close = table_match.groups()
    row_blocks = re.findall(r"<tr>(.*?)</tr>", table_inner, re.S)
    if not row_blocks:
        raise HeatmapError("未在表格中解析到任何 <tr> 行")

    rebuilt_rows: List[str] = []
    before_values: Dict[str, str] = {}
    after_values: Dict[str, str] = {}

    for index, row_block in enumerate(row_blocks):
        cells = re.findall(r"<td>(.*?)</td>", row_block, re.S)
        if index == 0:
            rebuilt_rows.append(rebuild_row(cells))
            continue
        if len(cells) != 6:
            raise HeatmapError(f"表格第 {index + 1} 行列数异常，预期 6 列，实际 {len(cells)} 列")

        skill_name = re.sub(r"\s+", " ", cells[1]).strip()
        old_value = re.sub(r"\s+", " ", cells[5]).strip()
        if skill_name in counts:
            cells[5] = str(counts[skill_name])
            before_values[skill_name] = old_value
            after_values[skill_name] = cells[5]
        rebuilt_rows.append(rebuild_row(cells))

    missing = [skill for skill in SKILLS_IN_SCOPE if skill not in after_values]
    if missing:
        raise HeatmapError(f"表格中缺少以下已登记技能行，无法完成写回: {', '.join(missing)}")

    new_table_html = f"{table_open}\n" + "\n".join(rebuilt_rows) + f"\n{table_close}"
    return new_table_html, before_values, after_values


def parse_registry_counts(markdown_text: str) -> Dict[str, str]:
    _, _, table_html = extract_registry_table(markdown_text)
    row_blocks = re.findall(r"<tr>(.*?)</tr>", table_html, re.S)
    result: Dict[str, str] = {}
    for index, row_block in enumerate(row_blocks):
        if index == 0:
            continue
        cells = re.findall(r"<td>(.*?)</td>", row_block, re.S)
        if len(cells) != 6:
            continue
        skill_name = re.sub(r"\s+", " ", cells[1]).strip()
        value = re.sub(r"\s+", " ", cells[5]).strip()
        result[skill_name] = value
    return result


def verify_readback(doc_url: str, expected_counts: Dict[str, int], output_dir: Path) -> Dict[str, object]:
    downloaded = download_doc(doc_url)
    readback_copy = output_dir / "wiki_after.lark.md"
    shutil.copy2(downloaded, readback_copy)
    markdown_text = downloaded.read_text(encoding="utf-8", errors="ignore")
    observed = parse_registry_counts(markdown_text)
    mismatches = []
    for skill, expected in expected_counts.items():
        actual = observed.get(skill, "")
        if actual != str(expected):
            mismatches.append({"skill": skill, "expected": str(expected), "actual": actual})
    return {
        "readback_file": str(readback_copy),
        "observed": observed,
        "mismatches": mismatches,
        "success": not mismatches,
    }


def write_json(path: Path, payload: Dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_summary_lines(counts: Dict[str, int], verification: Dict[str, object]) -> List[str]:
    ranking = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    lines = ["关键计数摘要:"]
    lines.extend([f"- {skill}={count}" for skill, count in ranking])
    lines.append(
        f"Wiki 写回: {'成功' if verification['success'] else '失败'} | RAW 回读: {'成功' if verification['success'] else '失败'}"
    )
    return lines


def validate_runtime_assertions(doc_url: str) -> None:
    if not doc_url.startswith("https://bytedance.larkoffice.com/docx/"):
        raise HeatmapError(f"目标文档 URL 非法，预期 docx 链接，实际: {doc_url}")

    if len(SKILLS_IN_SCOPE) != 16:
        raise HeatmapError(f"统计范围异常，预期 16 个技能，实际 {len(SKILLS_IN_SCOPE)} 个")

    missing_alias = [skill for skill in SKILLS_IN_SCOPE if skill not in LEGACY_ALIAS_MAP]
    if missing_alias:
        raise HeatmapError(f"以下技能缺少 legacy alias 配置，无法执行 v1 兼容统计: {', '.join(missing_alias)}")

    log_root = workspace_root() / ".aime/log/subagent"
    if not log_root.exists():
        raise HeatmapError(f"日志目录不存在: {log_root}")

    assert DEFAULT_DOC_URL == doc_url, "运行时禁止擅自切换默认目标文档"


def main() -> int:
    output_dir = output_root()
    doc_url = DEFAULT_DOC_URL
    validate_runtime_assertions(doc_url)

    anchor_time, anchor_file, anchor_mode = detect_v1_anchor()
    scan_result = scan_v1_counts(anchor_time)
    counts = scan_result["counts"]

    leaderboard_text = render_leaderboard(scan_result, anchor_time, anchor_mode, anchor_file)
    (output_dir / "leaderboard.txt").write_text(leaderboard_text, encoding="utf-8")

    before_download = download_doc(doc_url)
    before_copy = output_dir / "wiki_before.lark.md"
    shutil.copy2(before_download, before_copy)
    before_markdown = before_download.read_text(encoding="utf-8", errors="ignore")

    block_number, block_id, table_html = extract_registry_table(before_markdown)
    new_table_html, before_values, after_values = patch_registry_table(table_html, counts)

    update_output = update_doc(
        doc_url,
        before_download,
        [
            {
                "block_number": block_number,
                "block_id": block_id,
                "content": new_table_html,
                "modification_type": "update",
            }
        ],
    )

    time.sleep(2)
    verification = verify_readback(doc_url, counts, output_dir)

    compatibility_check = {
        skill: {
            "expected_v1": EXPECTED_V1_COUNTS[skill],
            "actual": counts[skill],
            "matches_expected": counts[skill] == EXPECTED_V1_COUNTS[skill],
        }
        for skill in EXPECTED_V1_COUNTS
    }

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "doc_url": doc_url,
        "window": {
            "mode": anchor_mode,
            "anchor_time": anchor_time.strftime("%Y-%m-%d %H:%M:%S") if anchor_time else None,
            "anchor_file": str(anchor_file) if anchor_file else None,
            "log_root": scan_result["log_root"],
            "total_dirs_available": scan_result["total_dirs_available"],
            "dirs_in_window": scan_result["dirs_in_window"],
            "matched_dir_count": scan_result["matched_dir_count"],
        },
        "counts": counts,
        "leaderboard": scan_result["leaderboard"],
        "examples": scan_result["examples"],
        "expected_v1_reference": EXPECTED_V1_COUNTS,
        "compatibility_check": compatibility_check,
        "wiki_update": {
            "block_number": block_number,
            "block_id": block_id,
            "before_values": before_values,
            "after_values": after_values,
            "update_output": update_output,
            "readback": verification,
        },
        "artifacts": {
            "leaderboard": str(output_dir / "leaderboard.txt"),
            "counts_json": str(output_dir / "heatmap_counts.json"),
            "wiki_before": str(before_copy),
            "wiki_after": str(output_dir / "wiki_after.lark.md"),
        },
    }
    write_json(output_dir / "heatmap_counts.json", payload)

    summary_lines = []
    summary_lines.append("[skill-heatmap-generator] 本地试跑完成")
    summary_lines.append(f"- 目标文档: {doc_url}")
    summary_lines.append(
        f"- 窗口模式: {anchor_mode}"
        + (f" | 锚点时间: {anchor_time.strftime('%Y-%m-%d %H:%M:%S')}" if anchor_time else "")
    )
    summary_lines.extend(build_summary_lines(counts, verification))
    summary_lines.append(f"- 输出文件: {output_dir / 'heatmap_counts.json'}")
    summary_lines.append(f"- 输出文件: {output_dir / 'leaderboard.txt'}")
    summary_lines.append(f"- 写前下载副本: {before_copy}")
    summary_lines.append(f"- 写后回读副本: {output_dir / 'wiki_after.lark.md'}")

    print("\n".join(summary_lines))

    if not verification["success"]:
        mismatch_text = json.dumps(verification["mismatches"], ensure_ascii=False)
        print(f"[skill-heatmap-generator] RAW 回读失败: {mismatch_text}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
