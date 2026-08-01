#!/usr/bin/env python3
"""
Aime-Dreaming 管线后置钩子：拓扑图静默重绘与 Wiki 自动换图。

职责：
  1. 对比 graph_after_dreaming.json 的前后版本，检测节点/边变化
  2. 若有变化，则重绘 HTML 拓扑图并尝试生成 SVG 白板源文件
  3. 生成 wiki_update_manifest.json
  4. 可选串行调用 execute_wiki_swap.py，把最新拓扑同步到 Aime 乐园 Wiki
  5. 可选写入 PATROL.log

常用调用：
  # 仅为历史补跑生成产物，不写 PATROL，不推送 Wiki
  python3 projects/Aime-Dreaming/scripts/post_dreaming_hook.py --cycle-date 20260610 --skip-patrol-log

  # 正常夜间链路：生成产物后立刻推送 Wiki
  python3 projects/Aime-Dreaming/scripts/post_dreaming_hook.py --cycle-date 20260610 --execute-wiki-swap
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = PROJECT_ROOT / "output"
PATROL_LOG = PROJECT_ROOT / "PATROL.log"

WIKI_TOPOLOGY_URL = "https://bytedance.larkoffice.com/wiki/ZV5fwlNqBiuu4GkNHj2cG27PnWc"
WIKI_PARENT_HOMEPAGE_URL = "https://bytedance.larkoffice.com/wiki/JHExwPicJiHc6fkApxZcUMumncg"

WORKSPACE_ROOT = PROJECT_ROOT.parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aime-Dreaming Post Hook")
    parser.add_argument("--cycle-date", default=date.today().strftime("%Y%m%d"), help="目标 cycle 日期，格式 YYYYMMDD")
    parser.add_argument("--execute-wiki-swap", action="store_true", help="生成 manifest 后立即调用 execute_wiki_swap.py")
    parser.add_argument("--backfill-start-cycle", type=int, default=None, help="传递给 execute_wiki_swap.py，用于首页 Timeline 补账起始 cycle")
    parser.add_argument("--skip-patrol-log", action="store_true", help="仅用于历史补跑，不向 PATROL.log 追加当前执行记录")
    return parser.parse_args()


def find_graph_paths(cycle_date_str: str) -> Tuple[Path, Optional[Path]]:
    current_dir = OUTPUT_ROOT / f"dreaming_{cycle_date_str}"
    current_graph = current_dir / "graph_after_dreaming.json"

    all_dirs = sorted(d for d in OUTPUT_ROOT.iterdir() if d.is_dir() and d.name.startswith("dreaming_"))
    previous_graph = None
    for directory in all_dirs:
        if directory.name == f"dreaming_{cycle_date_str}":
            break
        candidate = directory / "graph_after_dreaming.json"
        if candidate.exists():
            previous_graph = candidate

    return current_graph, previous_graph


def compute_graph_fingerprint(graph_path: Optional[Path]) -> Optional[str]:
    if not graph_path or not graph_path.exists():
        return None
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    node_ids = sorted(node["id"] for node in graph["nodes"])
    edge_keys = sorted(f"{edge['source']}→{edge['target']}" for edge in graph["edges"])
    fingerprint_str = "|".join(node_ids) + "||" + "|".join(edge_keys)
    return hashlib.sha256(fingerprint_str.encode("utf-8")).hexdigest()


def detect_changes(current_graph: Path, previous_graph: Optional[Path]) -> Tuple[bool, str]:
    fp_current = compute_graph_fingerprint(current_graph)
    fp_previous = compute_graph_fingerprint(previous_graph)

    if fp_previous is None:
        return True, "首次生成（无前序快照）"
    if fp_current != fp_previous:
        curr = json.loads(current_graph.read_text(encoding="utf-8"))
        prev = json.loads(previous_graph.read_text(encoding="utf-8"))
        delta_nodes = len(curr["nodes"]) - len(prev["nodes"])
        delta_edges = len(curr["edges"]) - len(prev["edges"])
        return True, f"节点变化: {delta_nodes:+d}, 边变化: {delta_edges:+d}"
    return False, "无变化"


def render_html(current_graph: Path, cycle_date_str: str) -> Tuple[Path, Path]:
    output_dir = OUTPUT_ROOT / f"dreaming_{cycle_date_str}"
    html_path = output_dir / "aime_graph_topology.html"
    deploy_dir = output_dir / "deploy"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    deploy_html = deploy_dir / "index.html"

    render_script = PROJECT_ROOT / "scripts" / "render_graph_html.py"
    subprocess.run(
        [sys.executable, str(render_script), str(current_graph), str(html_path)],
        check=True,
        cwd=str(WORKSPACE_ROOT),
    )
    shutil.copy2(str(html_path), str(deploy_html))
    print(f"✅ HTML 拓扑图已部署到: {deploy_html}")
    return html_path, deploy_html


def generate_svg_topology(current_graph: Path, cycle_date_str: str) -> Optional[Path]:
    output_dir = OUTPUT_ROOT / f"dreaming_{cycle_date_str}"
    svg_path = output_dir / "aime_topology.svg"

    graph = json.loads(current_graph.read_text(encoding="utf-8"))
    cycle_num = graph.get("dreaming_cycle", "?")
    node_count = len(graph["nodes"])
    edge_count = len(graph["edges"])

    goal = (
        f"基于 Aime 认知图谱 Cycle #{cycle_num} 的 graph_after_dreaming.json 数据，"
        f"绘制一张 Takram 极简风格的认知网络拓扑图（architecture 类型）。"
        f"当前规模：{node_count} 节点 / {edge_count} 边。"
        f"要求：节点按 3 个聚类（基建=蓝色, 业务=金色, 方法论=青绿色）着色，"
        f"节点大小正比于出度，边用细线标注方向，整体深色背景，科技感。"
        f"特别注意：节点文字（label）不要有背景色，背景设为透明。"
        f"标题：Aime 认知图谱 · Cycle #{cycle_num}"
    )

    diagram_script = WORKSPACE_ROOT / "tools" / "draw_diagram.py"
    params = json.dumps(
        {
            "goal": goal,
            "diagram_type": "architecture",
            "operation": "create",
            "render_engine": "svg",
            "output_path": str(svg_path),
            "references": [str(current_graph)],
        },
        ensure_ascii=False,
    )

    try:
        result = subprocess.run(
            [sys.executable, str(diagram_script), params],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(WORKSPACE_ROOT),
        )
        if result.returncode == 0:
            print(f"✅ SVG 拓扑图已生成: {svg_path}")
            return svg_path
        print(f"⚠️ SVG 生成失败 (returncode={result.returncode}): {result.stderr[:200]}")
        return None
    except Exception as exc:
        print(f"⚠️ SVG 生成异常: {exc}")
        return None


def reuse_previous_svg(previous_graph: Optional[Path], cycle_date_str: str) -> Optional[Path]:
    if not previous_graph:
        return None

    previous_svg = previous_graph.parent / "aime_topology.svg"
    if not previous_svg.exists():
        return None

    target_svg = OUTPUT_ROOT / f"dreaming_{cycle_date_str}" / "aime_topology.svg"
    shutil.copy2(previous_svg, target_svg)
    print(f"♻️ 复用上一轮 SVG 拓扑图: {previous_svg} -> {target_svg}")
    return target_svg


def write_manifest(html_path: Path, svg_path: Optional[Path], cycle_date_str: str) -> Path:
    graph_path = OUTPUT_ROOT / f"dreaming_{cycle_date_str}" / "graph_after_dreaming.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    cycle_num = graph.get("dreaming_cycle", "?")
    node_count = len(graph["nodes"])
    edge_count = len(graph["edges"])
    density = graph.get("stats", {}).get("density_pct", 0)
    gen_time = graph.get("generated_at", datetime.now().isoformat())

    update_preview = (
        f"# Aime 记忆图谱网络拓扑 · Cycle #{cycle_num}\n\n"
        f"![preview](aime_topology.svg)"
    )

    manifest = {
        "wiki_topology_url": WIKI_TOPOLOGY_URL,
        "wiki_parent_url": WIKI_PARENT_HOMEPAGE_URL,
        "cycle": cycle_num,
        "nodes": node_count,
        "edges": edge_count,
        "density": density,
        "html_path": str(html_path),
        "svg_path": str(svg_path) if svg_path else None,
        "graph_generated_at": gen_time,
        "update_content_preview": update_preview,
        "status": "pending_mcp_update",
    }

    manifest_path = OUTPUT_ROOT / f"dreaming_{cycle_date_str}" / "wiki_update_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ Wiki 更新清单已生成: {manifest_path}")
    print(f"   目标 Wiki 拓扑节点: {WIKI_TOPOLOGY_URL}")
    print(f"   目标 Wiki 父节点首页: {WIKI_PARENT_HOMEPAGE_URL}")
    return manifest_path


def execute_wiki_swap(manifest_path: Path, backfill_start_cycle: Optional[int]) -> bool:
    swap_script = PROJECT_ROOT / "scripts" / "execute_wiki_swap.py"
    command = [sys.executable, str(swap_script), str(manifest_path)]
    if backfill_start_cycle is not None:
        command.extend(["--backfill-start-cycle", str(backfill_start_cycle)])

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(WORKSPACE_ROOT),
    )
    if result.returncode != 0:
        print(f"❌ Wiki 自动推送失败:\n{result.stdout}\n{result.stderr}")
        return False
    print(result.stdout)
    return True


def append_patrol_log(cycle_date_str: str, change_reason: str, html_path: Path, swap_status: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = (
        f"\n[{timestamp}] 拓扑图自动重绘完成 (Post-Dreaming Hook)\n"
        f"- 触发原因: {change_reason}\n"
        f"- 产物: {html_path}\n"
        f"- Wiki 更新清单: output/dreaming_{cycle_date_str}/wiki_update_manifest.json\n"
        f"- 状态: {swap_status}\n"
    )
    PATROL_LOG.write_text(PATROL_LOG.read_text(encoding="utf-8") + entry, encoding="utf-8")
    print("✅ PATROL.log 已追加条目")


def main() -> None:
    args = parse_args()
    cycle_date_str = args.cycle_date

    print(f"🌙 Post-Dreaming Hook 启动 | Cycle Date: {cycle_date_str}")
    print("=" * 60)

    current_graph, previous_graph = find_graph_paths(cycle_date_str)
    if not current_graph.exists():
        print(f"❌ 当前 Cycle 快照不存在: {current_graph}")
        sys.exit(1)

    has_changes, reason = detect_changes(current_graph, previous_graph)
    force_frontend_sync = (not has_changes) and args.execute_wiki_swap
    print(f"📊 变化检测: {'有变化' if has_changes else '无变化'} | {reason}")
    if not has_changes and not force_frontend_sync:
        print("🔄 图谱无变化，跳过重绘。")
        return
    if force_frontend_sync:
        reason = f"{reason}（执行强制前台回写）"
        print("🔄 图谱拓扑无变化，但已显式要求执行 Wiki 前台回写，继续生成产物并推送。")

    print("\n🎨 开始渲染 ECharts HTML 拓扑图...")
    html_path, _deploy_html = render_html(current_graph, cycle_date_str)

    print("\n🖼️ 尝试生成 SVG 静态拓扑图...")
    svg_path = generate_svg_topology(current_graph, cycle_date_str)
    if svg_path is None and not has_changes:
        svg_path = reuse_previous_svg(previous_graph, cycle_date_str)

    print("\n📝 准备 Wiki 换图清单...")
    manifest_path = write_manifest(html_path, svg_path, cycle_date_str)

    swap_status = "待 MCP 执行换图"
    if args.execute_wiki_swap:
        print("\n🚀 执行 Wiki 自动推送...")
        swap_ok = execute_wiki_swap(manifest_path, args.backfill_start_cycle)
        swap_status = "Wiki 已自动更新" if swap_ok else "Wiki 自动更新失败，需人工复核"

    if not args.skip_patrol_log:
        print("\n📋 更新巡检日志...")
        append_patrol_log(cycle_date_str, reason, html_path, swap_status)

    print("\n" + "=" * 60)
    print("✅ Post-Dreaming Hook 执行完毕")
    if args.execute_wiki_swap:
        print(f"   状态: {swap_status}")
    else:
        print("   下一步: 调用 execute_wiki_swap.py 执行 wiki_update_manifest.json 中的换图动作")


if __name__ == "__main__":
    main()
