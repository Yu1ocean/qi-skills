#!/usr/bin/env python3
"""
Wiki 拓扑图换图执行器。

读取 wiki_update_manifest.json，完成两类前台更新：
1. 拓扑页：更新标题并嵌入最新 SVG 画板
2. Aime 乐园首页：更新顶部预览、概览、统计面板与最新更新 Timeline

支持一次性补齐历史欠账：
  python3 projects/Aime-Dreaming/scripts/execute_wiki_swap.py \
    projects/Aime-Dreaming/output/dreaming_20260610/wiki_update_manifest.json \
    --backfill-start-cycle 16
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = PROJECT_ROOT.parent.parent
OUTPUT_ROOT = PROJECT_ROOT / "output"
PARENT_WIKI_TOKEN = "JHExwPicJiHc6fkApxZcUMumncg"
RECENT_DOC_LOOKBACK_DAYS = 14
RECENT_DOC_MAX_DATES = 4
RECENT_DOC_MAX_TITLES_PER_DAY = 3



BLOCK_RE = re.compile(r"<!--\s*(BLOCK_[^\s]+)\s*\|\s*([^\s]+)\s*-->(.*?)<!--\s*END_\1\s*-->", re.S)


class WikiSwapError(RuntimeError):
    pass


def validate_lark_cli_command(args: List[str]) -> None:
    if not args or args[0] != "docs":
        raise WikiSwapError(f"非法 lark-cli 命令，只允许 docs 子命令: {args}")
    if "+fetch" in args or "+update" in args:
        if "--api-version" not in args or "v2" not in args:
            raise WikiSwapError(f"lark-cli docs 命令缺少 --api-version v2: {args}")
        if "--as" not in args or "user" not in args:
            raise WikiSwapError(f"lark-cli docs 命令缺少 --as user: {args}")


def run_lark_cli(args: List[str], timeout: int = 120) -> str:
    validate_lark_cli_command(args)
    result = subprocess.run(
        ["lark-cli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(WORKSPACE_ROOT),
    )
    if result.returncode != 0:
        raise WikiSwapError(
            f"lark-cli 执行失败: {' '.join(args)}\nstdout={result.stdout[:500]}\nstderr={result.stderr[:500]}"
        )
    return result.stdout.strip()


def run_lark_cli_json(args: List[str], timeout: int = 120) -> Dict:
    output = run_lark_cli(args, timeout=timeout)
    match = re.search(r"(\{[\s\S]*\})", output)
    if not match:
        raise WikiSwapError(f"无法解析 lark-cli JSON 输出: {output[:500]}")
    return json.loads(match.group(1))


def format_ts(raw_ts: Optional[str]) -> Optional[datetime]:
    if not raw_ts:
        return None
    return datetime.fromtimestamp(int(raw_ts))


def fetch_recent_child_updates(parent_token: str, now: datetime) -> List[str]:
    listing = run_lark_cli_json(
        [
            "wiki",
            "+node-list",
            "--space-id",
            "7274908606431166467",
            "--parent-node-token",
            parent_token,
            "--as",
            "user",
            "--page-all",
            "--format",
            "json",
        ]
    )
    cutoff = now - timedelta(days=RECENT_DOC_LOOKBACK_DAYS)
    grouped = defaultdict(list)

    for node in listing.get("data", {}).get("nodes", []):
        if node.get("title") == "Decision Registry 台账":
            continue
        detail = run_lark_cli_json(
            [
                "wiki",
                "spaces",
                "get_node",
                "--as",
                "user",
                "--params",
                json.dumps({"token": node["node_token"]}, ensure_ascii=False),
                "--format",
                "json",
            ]
        )
        node_detail = detail.get("data", {}).get("node", {})
        edit_dt = format_ts(node_detail.get("obj_edit_time"))
        create_dt = format_ts(node_detail.get("obj_create_time"))
        effective_dt = edit_dt or create_dt
        if not effective_dt or effective_dt < cutoff:
            continue
        grouped[effective_dt.strftime("%Y-%m-%d")].append(node_detail.get("title", node.get("title", "未命名节点")).strip())

    entries = []
    for day in sorted(grouped.keys(), reverse=True)[:RECENT_DOC_MAX_DATES]:
        titles = []
        seen = set()
        for title in grouped[day]:
            if not title or title in seen:
                continue
            seen.add(title)
            titles.append(title)
        if not titles:
            continue
        display = "、".join(titles[:RECENT_DOC_MAX_TITLES_PER_DAY])
        extra = len(titles) - RECENT_DOC_MAX_TITLES_PER_DAY
        if extra > 0:
            display += f" 等 {len(titles)} 个节点"
        entries.append(f"- **{day}｜Wiki 文档更新**：{display}")
    return entries


def download_lark_doc(url: str) -> Path:
    output_dir = PROJECT_ROOT / ".cache" / "wiki_swap_docs"
    output_dir.mkdir(parents=True, exist_ok=True)
    token = url.rstrip("/").split("/")[-1].split("?")[0]
    output_path = output_dir / f"{token}.lark.md"
    result = run_lark_cli_json(
        [
            "docs",
            "+fetch",
            "--api-version",
            "v2",
            "--as",
            "user",
            "--doc",
            url,
            "--doc-format",
            "markdown",
            "--detail",
            "with-ids",
            "--format",
            "json",
        ],
        timeout=180,
    )
    content = result.get("data", {}).get("content") or result.get("data", {}).get("document", {}).get("content")
    if not isinstance(content, str):
        raise WikiSwapError(f"无法从 lark-cli fetch 输出中解析 content: {json.dumps(result, ensure_ascii=False)[:500]}")
    output_path.write_text(content, encoding="utf-8")
    return output_path


def update_lark_doc(document_url: str, markdown_file_path: Path, modifications: List[Dict]) -> str:
    responses = []
    for modification in modifications:
        command = "block_insert_after" if modification["modification_type"] == "insert" else "block_replace"
        args = [
            "docs",
            "+update",
            "--api-version",
            "v2",
            "--as",
            "user",
            "--doc",
            document_url,
            "--command",
            command,
            "--block-id",
            modification["block_id"],
            "--content",
            modification.get("content", ""),
            "--doc-format",
            "markdown",
            "--format",
            "json",
        ]
        responses.append(run_lark_cli(args, timeout=180))
    return "\n".join(responses)


def parse_blocks(markdown_path: Path) -> List[Dict[str, str]]:
    text = markdown_path.read_text(encoding="utf-8")
    blocks = []
    for match in BLOCK_RE.finditer(text):
        blocks.append(
            {
                "block_number": match.group(1),
                "block_id": match.group(2),
                "content": match.group(3).strip("\n"),
            }
        )
    return blocks


def find_block_by_number(blocks: List[Dict[str, str]], block_number: str) -> Optional[Dict[str, str]]:
    for block in blocks:
        if block["block_number"] == block_number:
            return block
    return None


def find_first_block(blocks: List[Dict[str, str]], predicate) -> Optional[Dict[str, str]]:
    for block in blocks:
        if predicate(block):
            return block
    return None


def find_all_blocks(blocks: List[Dict[str, str]], predicate) -> List[Dict[str, str]]:
    return [block for block in blocks if predicate(block)]


def build_single_preview_modifications(blocks: List[Dict[str, str]], anchor_block: Dict[str, str], preview_content: str) -> List[Dict]:
    preview_blocks = find_all_blocks(blocks, lambda block: "![preview](" in block["content"])
    if not preview_blocks:
        return [
            {
                "block_number": anchor_block["block_number"],
                "block_id": anchor_block["block_id"],
                "content": preview_content,
                "modification_type": "insert",
            }
        ]

    modifications = [
        {
            "block_number": preview_blocks[0]["block_number"],
            "block_id": preview_blocks[0]["block_id"],
            "content": preview_content,
            "modification_type": "update",
        }
    ]
    for stale_block in preview_blocks[1:]:
        modifications.append(
            {
                "block_number": stale_block["block_number"],
                "block_id": stale_block["block_id"],
                "content": "",
                "modification_type": "update",
            }
        )
    return modifications


def prepare_preview_asset(output_dir: Path, source_svg_path: Path, cycle: int) -> str:
    preview_filename = f"aime_topology_cycle_{cycle}.svg"
    target_path = output_dir / preview_filename
    shutil.copy2(source_svg_path, target_path)
    return preview_filename


def quote_lines(lines: List[str]) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in lines)


def truncate_relation(text: str, limit: int = 72) -> str:
    normalized = text.split("：", 1)[0].replace("（", "(").replace("）", ")")

    def clean_side(side: str) -> str:
        side = re.sub(r"\([^)]*\)", "", side)
        side = side.split("(", 1)[0]
        side = re.sub(r"\s+", " ", side).strip()
        return side

    relation = normalized
    for separator in ["↔", "→"]:
        if separator in normalized:
            left, right = normalized.split(separator, 1)
            relation = f"{clean_side(left)} {separator} {clean_side(right)}"
            break
    else:
        relation = clean_side(normalized)

    relation = re.sub(r"\s+", " ", relation).strip()
    if len(relation) <= limit:
        return relation
    return relation[: limit - 1] + "…"


def format_node_list(nodes: List[str]) -> str:
    if not nodes:
        return ""
    quoted = [f"「{name}」" for name in nodes]
    if len(quoted) <= 2:
        return "、".join(quoted)
    return "、".join(quoted[:2]) + f" 等 {len(quoted)} 个节点"


def build_cycle_summary(graph: Dict) -> str:
    cycle = graph.get("dreaming_cycle", "?")
    cycle_date = graph.get("cycle_date", "")
    stats = graph.get("stats", {})
    node_count = stats.get("node_count", len(graph.get("nodes", [])))
    edge_count = stats.get("edge_count", len(graph.get("edges", [])))
    density = stats.get("density_pct", 0)
    delta = graph.get("delta_from_previous", {})
    new_nodes = delta.get("new_nodes", [])
    promoted = delta.get("promoted_weak_connections", [])
    strengthened = delta.get("strengthened_edges", [])

    if new_nodes:
        detail = f"新增{format_node_list(new_nodes)}"
        if promoted:
            detail += f"，并晋升「{truncate_relation(promoted[0], 48)}」"
    elif promoted:
        detail = f"晋升「{truncate_relation(promoted[0], 56)}」"
    elif strengthened:
        detail = f"重点强化「{truncate_relation(strengthened[0].replace(' (strengthened)', ''), 56)}」"
    else:
        detail = "主链延续上一轮，无新增节点"

    return (
        f"- **{cycle_date}｜Cycle #{cycle}**："
        f"{node_count} 节点 / {edge_count} 边 / {density:.2f}% 密度；{detail}。"
    )


def load_graph_history(start_cycle: int, end_cycle: int) -> List[Dict]:
    collected = []
    for graph_path in sorted(OUTPUT_ROOT.glob("dreaming_*/graph_after_dreaming.json")):
        try:
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        cycle = graph.get("dreaming_cycle")
        if isinstance(cycle, int) and start_cycle <= cycle <= end_cycle:
            collected.append(graph)
    collected.sort(key=lambda item: item.get("dreaming_cycle", 0), reverse=True)
    return collected


def build_overview_block(manifest: Dict, backfill_start_cycle: Optional[int]) -> str:
    cycle = manifest["cycle"]
    gen_time = manifest.get("generated_at") or manifest.get("graph_generated_at") or manifest.get("update_content_preview", "")
    if not gen_time:
        graph_path = Path(manifest["graph_path"])
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        gen_time = graph.get("generated_at", "未知")

    if backfill_start_cycle and backfill_start_cycle < cycle:
        catchup_text = f"📌 本次已完成 **Cycle #{backfill_start_cycle} ~ #{cycle}** 的前台断链补跑，Aime 乐园首页重新与后端快照追平。"
    else:
        catchup_text = "📌 本页由 Aime-Dreaming 夜间压缩链路自动回写，前台状态与后端最新快照保持同步。"

    lines = [
        "这是当前 **Aime 乐园 Wiki 根节点首页** 承载的实时图谱视图，数据来自 `Aime-Dreaming` 最新一次认知压缩。",
        "",
        catchup_text,
        "",
        f"**当前版本**：Cycle #{cycle}",
        "",
        f"**生成时间**：{gen_time}",
    ]
    return quote_lines(lines)


def build_stats_table(graph: Dict) -> str:
    stats = graph.get("stats", {})
    cycle = graph.get("dreaming_cycle", "?")
    cycle_date = graph.get("cycle_date", "")
    node_count = stats.get("node_count", len(graph.get("nodes", [])))
    edge_count = stats.get("edge_count", len(graph.get("edges", [])))
    density = stats.get("density_pct", 0)
    dangling_count = stats.get("dangling_link_count", 0)
    snapshot_dir = Path(graph["graph_path"]).parent.name

    return f"""<table header-row=\"true\" col-widths=\"220,160,620\">\n    <tr>\n        <td>**指标**</td>\n        <td>**数值**</td>\n        <td>**说明**</td>\n    </tr>\n    <tr>\n        <td>Dreaming Cycle</td>\n        <td>**#{cycle}**</td>\n        <td>{cycle_date} 凌晨完成的最新认知压缩轮次</td>\n    </tr>\n    <tr>\n        <td>节点总数</td>\n        <td>**{node_count}**</td>\n        <td>当前已纳入主线图谱的真实认知节点数</td>\n    </tr>\n    <tr>\n        <td>边总数</td>\n        <td>**{edge_count}**</td>\n        <td>当前物理双向链接 / 语义连接总量</td>\n    </tr>\n    <tr>\n        <td>图密度</td>\n        <td>**{density:.2f}%**</td>\n        <td>图谱结构紧密度，计算口径为 `edge_count / (node_count × (node_count - 1))`</td>\n    </tr>\n    <tr>\n        <td>悬挂链接</td>\n        <td>**{dangling_count}**</td>\n        <td>{'当前无悬挂链接，主线图谱已完全闭环' if dangling_count == 0 else '仍有待修复的悬挂链接，需要继续巡检回补'}</td>\n    </tr>\n    <tr>\n        <td>最新快照</td>\n        <td>`{snapshot_dir}`</td>\n        <td>来源：`projects/Aime-Dreaming/output/{snapshot_dir}/graph_after_dreaming.json`</td>\n    </tr>\n</table>"""


def build_timeline_entries(current_cycle: int, backfill_start_cycle: Optional[int]) -> List[str]:
    start_cycle = backfill_start_cycle if backfill_start_cycle is not None else max(1, current_cycle - 8)
    history = load_graph_history(start_cycle, current_cycle)
    cycle_entries = [build_cycle_summary(graph) for graph in history]
    recent_doc_entries = fetch_recent_child_updates(PARENT_WIKI_TOKEN, datetime.now())
    return recent_doc_entries + cycle_entries


def ensure_manifest_graph_fields(manifest: Dict, manifest_path: Path) -> Dict:
    graph_path = manifest_path.parent / "graph_after_dreaming.json"
    if not graph_path.exists():
        raise WikiSwapError(f"graph_after_dreaming.json 不存在: {graph_path}")
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph["graph_path"] = str(graph_path)
    manifest["graph_path"] = str(graph_path)
    manifest.setdefault("graph_generated_at", graph.get("generated_at"))
    return graph


def build_topology_modifications(blocks: List[Dict[str, str]], preview_filename: str) -> List[Dict]:
    title_block = find_block_by_number(blocks, "BLOCK_1")
    if not title_block:
        raise WikiSwapError("拓扑页缺少 BLOCK_1 标题块，无法更新")

    modifications = [
        {
            "block_number": title_block["block_number"],
            "block_id": title_block["block_id"],
            "content": f"# Aime 记忆图谱网络拓扑 · Cycle #{CURRENT_CYCLE}",
            "modification_type": "update",
        }
    ]
    preview_content = f"![preview]({preview_filename})"
    modifications.extend(build_single_preview_modifications(blocks, title_block, preview_content))
    return modifications


def build_homepage_modifications(blocks: List[Dict[str, str]], overview: str, stats_table: str, timeline_entries: List[str], preview_filename: str) -> List[Dict]:
    title_block = find_block_by_number(blocks, "BLOCK_2") or find_first_block(blocks, lambda block: "# 🧠 Aime 乐园 · 主线拓扑总览" in block["content"])
    overview_block = find_block_by_number(blocks, "BLOCK_9") or find_first_block(blocks, lambda block: "Aime 乐园 Wiki 根节点首页" in block["content"])
    stats_block = find_block_by_number(blocks, "BLOCK_10") or find_first_block(blocks, lambda block: "<table" in block["content"] and "Dreaming Cycle" in block["content"])
    updates_heading = find_block_by_number(blocks, "BLOCK_4") or find_first_block(blocks, lambda block: "# 🌲 最新更新" in block["content"])

    if not title_block or not overview_block or not stats_block or not updates_heading:
        raise WikiSwapError("Aime 乐园首页 block 结构异常，缺少标题 / 概览 / 统计 / 最新更新关键块")

    update_heading_index = next(i for i, block in enumerate(blocks) if block["block_number"] == updates_heading["block_number"])
    timeline_blocks = [
        block
        for block in blocks[update_heading_index + 1 :]
        if block["content"].strip().startswith("- **")
    ]

    modifications = []
    preview_content = f"![preview]({preview_filename})"
    modifications.extend(build_single_preview_modifications(blocks, title_block, preview_content))

    modifications.extend(
        [
            {
                "block_number": overview_block["block_number"],
                "block_id": overview_block["block_id"],
                "content": overview,
                "modification_type": "update",
            },
            {
                "block_number": stats_block["block_number"],
                "block_id": stats_block["block_id"],
                "content": stats_table,
                "modification_type": "update",
            },
        ]
    )

    existing_count = len(timeline_blocks)
    target_count = len(timeline_entries)
    overlap = min(existing_count, target_count)

    for idx in range(overlap):
        block = timeline_blocks[idx]
        modifications.append(
            {
                "block_number": block["block_number"],
                "block_id": block["block_id"],
                "content": timeline_entries[idx],
                "modification_type": "update",
            }
        )

    if existing_count > target_count:
        for block in timeline_blocks[target_count:]:
            modifications.append(
                {
                    "block_number": block["block_number"],
                    "block_id": block["block_id"],
                    "content": "",
                    "modification_type": "update",
                }
            )
    elif target_count > existing_count:
        anchor = timeline_blocks[-1] if timeline_blocks else updates_heading
        remaining = "\n\n".join(timeline_entries[existing_count:])
        modifications.append(
            {
                "block_number": anchor["block_number"],
                "block_id": anchor["block_id"],
                "content": remaining,
                "modification_type": "insert",
            }
        )

    return modifications


def write_helper_markdown(output_dir: Path, preview_filename: str) -> Dict[str, Path]:
    topology_md = output_dir / "topology_wiki_update.lark.md"
    parent_md = output_dir / "parent_homepage_update.lark.md"
    topology_md.write_text(f"# Aime 记忆图谱网络拓扑 · Cycle #{CURRENT_CYCLE}\n\n![preview]({preview_filename})\n", encoding="utf-8")
    parent_md.write_text(f"![preview]({preview_filename})\n", encoding="utf-8")
    return {"topology": topology_md, "parent": parent_md}


def mark_backfilled_manifests(current_manifest_path: Path, current_cycle: int, backfill_start_cycle: Optional[int], executed_at: str) -> None:
    if backfill_start_cycle is None or backfill_start_cycle >= current_cycle:
        return

    for manifest_path in OUTPUT_ROOT.glob("dreaming_*/wiki_update_manifest.json"):
        if manifest_path == current_manifest_path:
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        cycle = data.get("cycle")
        if not isinstance(cycle, int):
            continue
        if backfill_start_cycle <= cycle < current_cycle:
            data["status"] = f"backfilled_to_cycle{current_cycle}_dashboard"
            data["executed_at"] = executed_at
            manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="执行 Aime-Dreaming Wiki 换图与首页回写")
    parser.add_argument("manifest_json_path", help="wiki_update_manifest.json 路径")
    parser.add_argument("--backfill-start-cycle", type=int, default=None, help="若指定，则首页 Timeline 回填该起始 Cycle 到当前 Cycle，并把更早 manifest 标记为已补账")
    args = parser.parse_args()

    manifest_path = Path(args.manifest_json_path).resolve()
    if not manifest_path.exists():
        raise WikiSwapError(f"Manifest 不存在: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    graph = ensure_manifest_graph_fields(manifest, manifest_path)

    global CURRENT_CYCLE
    CURRENT_CYCLE = manifest["cycle"]

    print("📋 Wiki 换图执行器启动")
    print(f"   Cycle #{manifest['cycle']} | {manifest['nodes']} 节点 / {manifest['edges']} 边")
    print(f"   目标拓扑页: {manifest['wiki_topology_url']}")
    print(f"   目标首页: {manifest['wiki_parent_url']}")

    if not manifest.get("svg_path") or not Path(manifest["svg_path"]).exists():
        raise WikiSwapError(f"SVG 产物不存在，无法换图: {manifest.get('svg_path')}")

    preview_filename = prepare_preview_asset(manifest_path.parent, Path(manifest["svg_path"]), manifest["cycle"])
    helper_files = write_helper_markdown(manifest_path.parent, preview_filename)

    print("\n📥 下载目标 Wiki 文档...")
    topology_md_path = download_lark_doc(manifest["wiki_topology_url"])
    parent_md_path = download_lark_doc(manifest["wiki_parent_url"])

    topology_blocks = parse_blocks(topology_md_path)
    parent_blocks = parse_blocks(parent_md_path)

    timeline_entries = build_timeline_entries(manifest["cycle"], args.backfill_start_cycle)
    overview = build_overview_block(manifest, args.backfill_start_cycle)
    stats_table = build_stats_table(graph)

    print("\n🧩 生成 block 级更新补丁...")
    topology_modifications = build_topology_modifications(topology_blocks, preview_filename)
    homepage_modifications = build_homepage_modifications(parent_blocks, overview, stats_table, timeline_entries, preview_filename)

    print("\n🚀 更新拓扑页...")
    topology_result = update_lark_doc(manifest["wiki_topology_url"], helper_files["topology"], topology_modifications)
    print(topology_result)

    print("\n🚀 更新 Aime 乐园首页...")
    homepage_result = update_lark_doc(manifest["wiki_parent_url"], helper_files["parent"], homepage_modifications)
    print(homepage_result)

    executed_at = datetime.now().isoformat()
    manifest["status"] = "wiki_updated"
    manifest["executed_at"] = executed_at
    manifest["topology_doc_update"] = "success"
    manifest["parent_homepage_update"] = "success"
    manifest["timeline_range"] = {
        "start_cycle": args.backfill_start_cycle if args.backfill_start_cycle is not None else max(1, manifest["cycle"] - 8),
        "end_cycle": manifest["cycle"],
        "entry_count": len(timeline_entries),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    mark_backfilled_manifests(manifest_path, manifest["cycle"], args.backfill_start_cycle, executed_at)

    print("\n✅ Wiki 换图流程完成")
    print(f"   拓扑页已更新到 Cycle #{manifest['cycle']}")
    print(f"   首页 Timeline 已覆盖 {manifest['timeline_range']['start_cycle']} ~ {manifest['timeline_range']['end_cycle']}")


if __name__ == "__main__":
    try:
        CURRENT_CYCLE = 0
        main()
    except Exception as exc:
        print(f"❌ {exc}")
        sys.exit(1)
