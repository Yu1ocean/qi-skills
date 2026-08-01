#!/usr/bin/env python3
"""
Takram-style ECharts 网络拓扑图渲染器。
接受命令行参数指定输入 JSON 与输出 HTML 路径，支持 Dreaming 管线自动调用。
"""
import json, os, sys
from collections import defaultdict
from datetime import datetime

def get_cluster(name, nodes_data):
    """从 graph JSON 节点数据中推断聚类标签。"""
    CLUSTER_KEYWORDS = {
        "基建": ["Code over Memory", "双轨架构", "巡检", "零信任", "声明式路由", "多会话控制台",
                 "Live Runtime", "凭证脱敏", "文件写入拦截", "双抓融合"],
        "业务": ["Global E-commerce", "FABE", "流量成本", "TaskFlow"],
        "方法论": ["记忆图谱", "身份域", "技能锻造", "Not-to-Do", "归档架构", "技能热度",
                  "技能自闭环", "Info-Miner", "知识中枢"],
    }
    for cluster, keywords in CLUSTER_KEYWORDS.items():
        for kw in keywords:
            if kw in name:
                return cluster
    return "方法论"

CATEGORY_COLOR = {
    "基建": "#5B8FF9",
    "业务": "#F6BD16",
    "方法论": "#5AD8A6",
}

def render(src_path, out_path):
    g = json.load(open(src_path))
    nodes_raw = g["nodes"]
    edges_raw = g["edges"]

    deg = defaultdict(int)
    for e in edges_raw:
        deg[e["source"]] += 1
        deg[e["target"]] += 1

    categories_list = ["基建", "业务", "方法论"]
    cat_idx = {c: i for i, c in enumerate(categories_list)}

    nodes_echarts = []
    id2name = {n["id"]: n["name"] for n in nodes_raw}
    for n in nodes_raw:
        cat = get_cluster(n["name"], nodes_raw)
        d = deg.get(n["id"], 1)
        size = 14 + (d ** 0.6) * 5
        nodes_echarts.append({
            "id": n["id"],
            "name": n["name"],
            "symbolSize": round(size, 1),
            "category": cat_idx[cat],
            "value": d,
            "summary": (n.get("summary", "") or "")[:240],
            "draggable": True,
            "label": {"show": True, "position": "right", "fontSize": 12, "backgroundColor": "transparent"},
        })

    valid_ids = set(id2name.keys())
    edges_echarts = []
    for e in edges_raw:
        if e["source"] not in valid_ids or e["target"] not in valid_ids:
            continue
        edges_echarts.append({
            "source": e["source"],
            "target": e["target"],
            "lineStyle": {"width": 1.2, "opacity": 0.55, "curveness": 0.08},
        })

    categories_echarts = [{"name": c, "itemStyle": {"color": CATEGORY_COLOR[c]}} for c in categories_list]

    cycle_num = g.get("dreaming_cycle", "?")
    cycle_date = g.get("cycle_date", datetime.now().strftime("%Y-%m-%d"))
    stats = {
        "nodes": len(nodes_echarts),
        "edges": len(edges_echarts),
        "density": g.get("stats", {}).get("density_pct", 0),
        "cycle": cycle_num,
        "generated_at": g.get("generated_at", datetime.now().isoformat()),
    }

    top5 = sorted(nodes_echarts, key=lambda x: -x["value"])[:5]

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Aime 认知图谱 · Cycle #__CYCLE__ 全景</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: linear-gradient(135deg, #0e1733 0%, #1a2350 50%, #0e1733 100%);
         color: #e8ecf3; min-height: 100vh; padding: 20px; }
  .header { display: flex; justify-content: space-between; align-items: flex-start;
            padding: 18px 24px; background: rgba(255,255,255,0.04);
            border-radius: 12px; backdrop-filter: blur(10px);
            border: 1px solid rgba(91,143,249,0.3); margin-bottom: 16px; }
  h1 { font-size: 22px; font-weight: 600; background: linear-gradient(90deg,#5B8FF9,#5AD8A6);
       -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  .sub { font-size: 12px; color: #8da0c1; margin-top: 4px; }
  .stats { display: flex; gap: 20px; }
  .stat-card { text-align: center; padding: 6px 14px;
               background: rgba(91,143,249,0.1); border-radius: 8px;
               border: 1px solid rgba(91,143,249,0.25); }
  .stat-num { font-size: 22px; font-weight: 700; color: #5B8FF9; }
  .stat-label { font-size: 11px; color: #8da0c1; }
  #chart { width: 100%; height: calc(100vh - 220px); min-height: 600px;
           background: rgba(0,0,0,0.2); border-radius: 12px;
           border: 1px solid rgba(91,143,249,0.2); }
  .footer { display: flex; justify-content: space-between;
            margin-top: 12px; padding: 10px 16px; font-size: 12px; color: #8da0c1;
            background: rgba(255,255,255,0.03); border-radius: 8px; }
  .top5 { display: flex; gap: 12px; flex-wrap: wrap; }
  .top5 span { color: #5AD8A6; }
</style>
</head>
<body>
  <div class="header">
    <div>
      <h1>✨ Aime 认知图谱 · Cycle #__CYCLE__ 全景 (__DATE__)</h1>
      <div class="sub">Dreaming Cycle → 拓扑自动重绘 · ECharts 力导向网络拓扑</div>
    </div>
    <div class="stats">
      <div class="stat-card"><div class="stat-num">__N__</div><div class="stat-label">节点</div></div>
      <div class="stat-card"><div class="stat-num">__E__</div><div class="stat-label">边</div></div>
      <div class="stat-card"><div class="stat-num">__D__%</div><div class="stat-label">密度</div></div>
    </div>
  </div>
  <div id="chart"></div>
  <div class="footer">
    <div>🔝 出度 Top5：<span class="top5">__TOP5__</span></div>
    <div>生成时间：__GEN__</div>
  </div>
<script>
const nodes = __NODES__;
const edges = __EDGES__;
const categories = __CATS__;

const chart = echarts.init(document.getElementById('chart'), 'dark');
const option = {
  backgroundColor: 'transparent',
  tooltip: {
    trigger: 'item',
    backgroundColor: 'rgba(20,28,60,0.95)',
    borderColor: '#5B8FF9',
    textStyle: { color: '#fff', fontSize: 12 },
    formatter: function(p) {
      if (p.dataType === 'node') {
        return `<b style="color:#5AD8A6">${p.data.name}</b><br/>` +
               `度: ${p.data.value} · 聚类: ${categories[p.data.category].name}<br/>` +
               `<div style="max-width:340px;white-space:normal;color:#cbd5e1;margin-top:4px">${p.data.summary || ''}</div>`;
      }
      return `${nodes.find(n => n.id===p.data.source).name} → ${nodes.find(n => n.id===p.data.target).name}`;
    }
  },
  legend: { data: categories.map(c => c.name), top: 10, textStyle: { color: '#e8ecf3' } },
  series: [{
    type: 'graph',
    layout: 'force',
    data: nodes,
    edges: edges,
    categories: categories,
    roam: true,
    draggable: true,
    label: { show: true, position: 'right', color: '#e8ecf3', fontSize: 11, backgroundColor: 'transparent',
             formatter: p => p.data.name.length > 14 ? p.data.name.slice(0,14)+'…' : p.data.name },
    edgeSymbol: ['none', 'arrow'],
    edgeSymbolSize: 6,
    lineStyle: { color: '#5B8FF9', curveness: 0.08, opacity: 0.55 },
    emphasis: { focus: 'adjacency', lineStyle: { width: 3, opacity: 1 } },
    force: { repulsion: 1400, edgeLength: [160, 280], gravity: 0.05, layoutAnimation: true, friction: 0.4 },
    labelLayout: { hideOverlap: false, moveOverlap: 'shiftY' }
  }]
};
chart.setOption(option);
window.addEventListener('resize', () => chart.resize());
</script>
</body></html>
"""
    top5_html = " · ".join([f"{i+1}. <span>{n['name']}({n['value']})</span>" for i, n in enumerate(top5)])

    html = (html
            .replace("__CYCLE__", str(stats["cycle"]))
            .replace("__DATE__", cycle_date)
            .replace("__N__", str(stats["nodes"]))
            .replace("__E__", str(stats["edges"]))
            .replace("__D__", f"{stats['density']:.1f}")
            .replace("__TOP5__", top5_html)
            .replace("__GEN__", stats["generated_at"])
            .replace("__NODES__", json.dumps(nodes_echarts, ensure_ascii=False))
            .replace("__EDGES__", json.dumps(edges_echarts, ensure_ascii=False))
            .replace("__CATS__", json.dumps(categories_echarts, ensure_ascii=False))
    )

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(html)

    print(f"✅ 图谱可视化已生成: {out_path}")
    print(f"   规模: {stats['nodes']} 节点 / {stats['edges']} 边 / 密度 {stats['density']:.2f}%")
    print(f"   Top5: {[(n['name'], n['value']) for n in top5]}")
    return out_path

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 render_graph_html.py <graph_json_path> [output_html_path]")
        sys.exit(1)
    src = sys.argv[1]
    if len(sys.argv) >= 3:
        out = sys.argv[2]
    else:
        dir_name = os.path.dirname(src)
        out = os.path.join(dir_name, "aime_graph_topology.html")
    render(src, out)
