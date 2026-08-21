# -*- coding: utf-8 -*-
import os, json, pandas as pd, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D

FP = '/usr/share/fonts/opentype/noto-cjk-sc/NotoSansCJKsc-Regular.otf'
font_manager.fontManager.addfont(FP)
plt.rcParams['font.sans-serif'] = ['Noto Sans CJK SC']
plt.rcParams['axes.unicode_minus'] = False

ROWS = [
    ("张玲",154,43,31,32),("郭晓彤",119,48,26,28),("谢冰沁Bibi",87,28,10,12),
    ("刘雨欣",80,20,6,11),("Millie Cheng",79,14,13,13),("陈晓",73,35,25,27),
    ("周洋",63,11,3,6),("欧阳嘉桦",59,14,6,9),("王妙辰",55,12,0,6),
    ("唐薇",54,3,0,2),("郎子涵",50,9,0,9),("胡思倩",49,16,1,5),
    ("张莞清",48,12,0,6),("文思琪",47,10,0,3),("郑羽伶",45,20,1,9),
    ("陈杏妹",45,11,2,5),("俞欣洁",43,6,4,4),("滕慧敏",43,2,0,1),
    ("周羽中 Ray",42,17,3,12),("韩希雯",38,14,5,9),("李执",25,4,1,3),
    ("陈晴",19,4,0,2),("王宁",15,6,1,3),("曾光影",13,2,1,1),
]

data = []
for name, leads, will, main, backup in ROWS:
    x = main / leads * 100
    y = (min(backup, will) / will * 100) if will > 0 else 0.0
    data.append(dict(name=name, leads=leads, willing=will, main=main, backup=backup,
                     x=round(x, 1), y=round(y, 1), pending=(main == 0)))

valid = [d for d in data if not d['pending']]
gray = [d for d in data if d['pending']]
mx = float(pd.Series([d['x'] for d in valid]).median())
my = float(pd.Series([d['y'] for d in valid]).median())
print('median x=%.1f y=%.1f  valid=%d gray=%d' % (mx, my, len(valid), len(gray)))

COL = {'star': '#2E6FF2', 'niche': '#22A06B', 'scale': '#F5872C', 'break': '#E03E3E'}
def quad(d):
    if d['x'] >= mx and d['y'] >= my: return 'star'
    if d['x'] < mx and d['y'] >= my: return 'niche'
    if d['x'] >= mx and d['y'] < my: return 'scale'
    return 'break'
for d in valid:
    d['q'] = quad(d)
    d['color'] = COL[d['q']]

# ---- 重叠点微抖动（仅影响绘图坐标，不改真实数值）----
from collections import defaultdict
buckets = defaultdict(list)
for d in data:
    buckets[(round(d['x'], 1), round(d['y'], 1))].append(d)
for k, grp in buckets.items():
    for i, d in enumerate(grp):
        d['px'], d['py'] = d['x'], d['y']
        if len(grp) > 1:
            d['px'] = d['x'] + (i - (len(grp) - 1) / 2) * 2.4
            d['py'] = d['y'] + (i - (len(grp) - 1) / 2) * 4.2

# ---- 灰色AM专项纵向散开（原点附近7个气泡容易堆叠）----
# 按备用口径纵轴值排序，若仍有重叠则强制均匀分布
gray_sorted = sorted(gray, key=lambda d: d['py'])
GRAY_STEP = 8.5  # 每个气泡间距至少8.5个单位
for i, d in enumerate(gray_sorted):
    min_y = -5.0 + i * GRAY_STEP
    if d['py'] < min_y:
        d['py'] = min_y

for i, d in enumerate(sorted(data, key=lambda z: (round(z['y'], 0), z['x']))):
    d['lab_up'] = (i % 2 == 0)

# ---- 横轴上限（当前样本 max x ≈ 34.2%，无极端值，全部数据落在轴内）----
XCAP = 40.0

# ---------- PNG ----------
fig, ax = plt.subplots(figsize=(15, 9.5), dpi=140)
fig.patch.set_facecolor('#FFFFFF')
ax.set_facecolor('#FFFFFF')
fig.subplots_adjust(left=0.07, right=0.965, top=0.90, bottom=0.10)

def size(l): return 90 + l * 13

ax.axvline(mx, color='#9aa0a6', ls='--', lw=1.2, zorder=1)
ax.axhline(my, color='#9aa0a6', ls='--', lw=1.2, zorder=1)

for d in gray:
    ax.scatter(d['px'], d['py'], s=size(d['leads']), c='#9E9E9E', alpha=0.42,
               edgecolors='#616161', linewidths=1.0, zorder=2)
for d in valid:
    ax.scatter(d['px'], d['py'], s=size(d['leads']), c=d['color'], alpha=0.72,
               edgecolors='white', linewidths=1.2, zorder=3)

import math
for d in data:
    r_pt = math.sqrt(size(d['leads']) / math.pi)
    lbl = d['name']
    up = (d['lab_up'] if 'lab_up' in d else True)
    ax.annotate(lbl, (d['px'], d['py']),
                xytext=(0, (r_pt + 7) if up else -(r_pt + 7)), textcoords='offset points',
                ha='center', va='bottom' if up else 'top', fontsize=8.6,
                color='#555' if d['pending'] else '#101010',
                fontweight='normal' if d['pending'] else 'bold', zorder=6)
    ax.annotate('%.1f%% / %.1f%%' % (d['x'], d['y']), (d['px'], d['py']),
                xytext=(0, -(r_pt + 12) if up else (r_pt + 12)), textcoords='offset points',
                ha='center', va='top' if up else 'bottom',
                fontsize=6.6, color='#8a8a8a', zorder=6)
for d in gray:
    ax.annotate('⚠ 待回填', (d['px'], d['py']), xytext=(0, 0), textcoords='offset points',
                ha='center', va='center', fontsize=6.8, color='#8a5a00', zorder=7)

ax.set_xlim(-4.5, XCAP + 1.5)
ax.set_ylim(-8, 112)
ax.set_xlabel('入驻率（主口径：EU/UK 入驻时间有值 ÷ 线索数，%）', fontsize=11.5)
ax.set_ylabel('意愿→入驻转化率（备用口径：状态=5-已入驻 ÷ 有意愿数，%）', fontsize=11.5)
ax.set_title('EU AM 气泡矩阵 V2（试跑预览）· 主口径入驻率 × 备用口径意愿转化率 · 气泡=线索量',
             fontsize=15, fontweight='bold', pad=30)
ax.grid(color='#eeeeee', lw=0.8, zorder=0)
for s in ('top', 'right'):
    ax.spines[s].set_visible(False)

# 象限标签放图外四角
kw = dict(transform=ax.transAxes, fontsize=12, fontweight='bold', clip_on=False)
ax.text(0.0, 1.035, '精耕小池', ha='left', color=COL['niche'], **kw)
ax.text(1.0, 1.035, '明星', ha='right', color=COL['star'], **kw)
ax.text(0.0, -0.085, '待突破', ha='left', color=COL['break'], **kw)
ax.text(1.0, -0.085, '规模待提效', ha='right', color=COL['scale'], **kw)
ax.text(0.5, 1.035, '分界线＝%d位主口径有效AM的中位数（x=%.1f%% / y=%.1f%%，灰色气泡不参与统计）' % (len(valid), mx, my),
        transform=ax.transAxes, ha='center', fontsize=9.5, color='#666')

legend = [
    Line2D([], [], marker='o', ls='', ms=11, mfc=COL['star'], mec='white', label='明星（右上）'),
    Line2D([], [], marker='o', ls='', ms=11, mfc=COL['niche'], mec='white', label='精耕小池（左上）'),
    Line2D([], [], marker='o', ls='', ms=11, mfc=COL['scale'], mec='white', label='规模待提效（右下）'),
    Line2D([], [], marker='o', ls='', ms=11, mfc=COL['break'], mec='white', label='待突破（左下）'),
    Line2D([], [], marker='o', ls='', ms=11, mfc='#9E9E9E', mec='#616161', alpha=0.5,
           label='灰色＝入驻时间待回填AM（7位，纵轴用备用口径）'),
]
ax.legend(handles=legend, loc='lower right', frameon=True, fontsize=9.5, framealpha=0.95)
fig.savefig('am_bubble_v2_preview.png', bbox_inches='tight', facecolor='#FFFFFF')
print('png ok')

# ---------- HTML (ECharts) ----------
# 全部 AM 均落在轴内，无极端值 → 不再有图外标注逻辑
def _plot_xy(items, xstep, ystep):
    """同坐标簇对角错位，仅影响绘图坐标；真实值另存于 value[6]/value[7] 供 tooltip 使用"""
    b = defaultdict(list)
    for d in items:
        b[(round(d['x'], 1), round(d['y'], 1))].append(d)
    out = {}
    for grp in b.values():
        n = len(grp)
        for i, d in enumerate(sorted(grp, key=lambda z: -z['leads'])):
            k = (i - (n - 1) / 2) if n > 1 else 0
            out[d['name']] = (round(d['x'] + k * xstep, 2), round(d['y'] + k * ystep, 2))
    return out

# ECharts 灰色气泡专项散开：7位灰色AM入驻率均为0%，需加大纵向/横向错位避免堆叠
GRAY_XY = _plot_xy(gray, 1.6, 6.0)

def series(items, color, gray_flag):
    out = []
    for d in items:
        px, py = GRAY_XY.get(d['name'], (d['x'], d['y'])) if gray_flag else (d['x'], d['y'])
        out.append({
            'name': d['name'],
            'value': [px, py, d['leads'], d['willing'], d['main'], d['backup'], d['x'], d['y']],
            'itemStyle': {'color': color(d), 'opacity': 0.42 if gray_flag else 0.75,
                          'borderColor': '#616161' if gray_flag else '#fff', 'borderWidth': 1.2},
        })
    return out

def build_html(clip):
    """clip=True → 聚焦版（横轴 0-40%，贴合实际数据分布）；clip=False → 全轴版（0-105%）"""
    valid_html = list(valid)
    xmax = 40 if clip else 105
    # 象限标签：统一黑底白字矩形，放在绘图区 grid 外侧四角，不遮挡坐标轴
    # grid: left=80, right=60, top=110, bottom=90  →  标签贴 grid 外侧
    # 统一宽度 120px、高 24px，文字水平居中
    W, H = 120, 24
    def quad_label(text, **pos):
        return {
            'type': 'group',
            **pos,
            'children': [
                {'type': 'rect',
                 'shape': {'x': 0, 'y': 0, 'width': W, 'height': H, 'r': 3},
                 'style': {'fill': '#FFFFFF', 'stroke': '#DDDDDD', 'lineWidth': 1}},
                {'type': 'text',
                 'style': {'text': text, 'fontSize': 12, 'fontWeight': 'bold',
                           'fill': '#222222',
                           'x': W / 2, 'y': H / 2,
                           'textAlign': 'center', 'textVerticalAlign': 'middle'}},
            ]
        }
    # 位置说明（相对整个图表容器，grid: left=80 right=60 top=110 bottom=90）：
    #   Y 轴刻度数字位于 grid 左侧 (x<80)，X 轴刻度数字位于 grid 下方 (bottom<90)。
    #   四象限标签统一放「grid 上方留白带」（上方两个）和「容器最底部」（下方两个），
    #   左侧 left=80 / 右侧 right=60，与 grid 边界对称 → 不压坐标轴，左右对称。
    LABEL_TOP = 110 - H - 6    # grid 上边界上方 6px
    LABEL_BOT = 12             # 容器底部 12px
    graphic = [
        # 左上：grid 上方，左对齐 grid 左边界
        quad_label('精耕小池',  left=80,   top=LABEL_TOP),
        # 右上：grid 上方，右对齐 grid 右边界（与左上垂直对齐）
        quad_label('明星',      right=60,  top=LABEL_TOP),
        # 左下：容器底部，左对齐 grid 左边界
        quad_label('待突破',    left=80,   bottom=LABEL_BOT),
        # 右下：容器底部，右对齐 grid 右边界（与左下垂直对齐）
        quad_label('规模待提效', right=60, bottom=LABEL_BOT),
    ]
    sub = '横轴=主口径入驻率 ｜ 纵轴=备用口径意愿→入驻率 ｜ 气泡=线索量 ｜ 分界线=%d位有效AM中位数(x=%.1f%%, y=%.1f%%)' % (len(valid), mx, my)
    opt = {
        'animation': False,
        'backgroundColor': '#fff',
        'title': {'text': 'EU AM 气泡矩阵 V2（%s）' % ('聚焦版' if clip else '全轴版'),
                  'subtext': sub, 'left': 'center', 'top': 8,
                  'textStyle': {'color': '#222'}, 'subtextStyle': {'color': '#666'}},
        'grid': {'left': 80, 'right': 60, 'top': 110, 'bottom': 90},
        'tooltip': {'trigger': 'item'},
        # 图例：4象限各配色 + 灰色（均用 circle icon，与气泡视觉一致）
        # 注意：ECharts 会丢弃「没有同名 series」的 legend 条目，因此下方 series 里
        # 额外挂了 4 个空数据的「图例锚点 series」（LEGEND_ANCHORS），仅供 legend 取色显示，
        # 不参与任何计算与绘制。selectedMode:false 禁用点击，避免误操作隐藏数据。
        'legend': {'top': 78, 'selectedMode': False,
                   'textStyle': {'color': '#333'},
                   'data': [
                       {'name': '明星（高入驻·高转化）',
                        'icon': 'circle',
                        'itemStyle': {'color': '#2E6FF2'}},
                       {'name': '精耕小池（低入驻·高转化）',
                        'icon': 'circle',
                        'itemStyle': {'color': '#22A06B'}},
                       {'name': '规模待提效（高入驻·低转化）',
                        'icon': 'circle',
                        'itemStyle': {'color': '#F5872C'}},
                       {'name': '待突破（低入驻·低转化）',
                        'icon': 'circle',
                        'itemStyle': {'color': '#E03E3E'}},
                       {'name': '⚠️ 入驻填写异常需复核',
                        'icon': 'circle',
                        'itemStyle': {'color': '#9E9E9E', 'borderColor': '#616161', 'opacity': 0.5}},
                   ]},
        'xAxis': {'name': '入驻率(%)', 'nameLocation': 'middle', 'nameGap': 32,
                  'min': -4, 'max': xmax,
                  'splitLine': {'lineStyle': {'color': '#f0f0f0'}}},
        'yAxis': {'name': '意愿→入驻转化率(%)', 'nameLocation': 'middle', 'nameGap': 48,
                  'min': -8, 'max': 112, 'splitLine': {'lineStyle': {'color': '#f0f0f0'}}},
        'series': [
            # 图例锚点 series（空数据，仅为让 legend 4 个象限条目能正常渲染出颜色）
            {'name': '明星（高入驻·高转化）', 'type': 'scatter', 'data': [],
             'itemStyle': {'color': '#2E6FF2'}, 'silent': True, 'tooltip': {'show': False}},
            {'name': '精耕小池（低入驻·高转化）', 'type': 'scatter', 'data': [],
             'itemStyle': {'color': '#22A06B'}, 'silent': True, 'tooltip': {'show': False}},
            {'name': '规模待提效（高入驻·低转化）', 'type': 'scatter', 'data': [],
             'itemStyle': {'color': '#F5872C'}, 'silent': True, 'tooltip': {'show': False}},
            {'name': '待突破（低入驻·低转化）', 'type': 'scatter', 'data': [],
             'itemStyle': {'color': '#E03E3E'}, 'silent': True, 'tooltip': {'show': False}},
            {'name': '主口径有效AM', 'type': 'scatter', 'symbolSize': 'SZ',
             'data': series(valid_html, lambda d: d['color'], False),
             'label': {'show': True, 'formatter': '{b}', 'position': 'inside',
                       'fontSize': 10, 'fontWeight': 'bold', 'color': '#111'},
             'markLine': {'silent': True, 'symbol': 'none',
                          'lineStyle': {'type': 'dashed', 'color': '#9aa0a6'},
                          'data': [
                              {'xAxis': round(mx, 1),
                               'label': {'position': 'insideStartTop',
                                         'formatter': str(round(mx, 1)),
                                         'color': '#9aa0a6', 'fontSize': 11}},
                              {'yAxis': round(my, 1),
                               'label': {'position': 'insideEndTop',
                                         'formatter': str(round(my, 1)),
                                         'color': '#9aa0a6', 'fontSize': 11}},
                          ]}},
            {'name': '⚠️ 入驻填写异常需复核', 'type': 'scatter', 'symbolSize': 'SZ',
             'data': series(gray, lambda d: '#9E9E9E', True),
             'label': {'show': True, 'formatter': '{b}', 'position': 'inside',
                       'fontSize': 9, 'color': '#333'}},
        ],
        'graphic': graphic,
    }
    opt_json = json.dumps(opt, ensure_ascii=False)
    opt_json = opt_json.replace('"SZ"', 'function(v){return Math.sqrt(90+v[2]*13)*1.15;}')
    opt_json = opt_json.replace('"trigger": "item"',
        '"trigger":"item","formatter":function(p){var v=p.value;return "<b>"+p.name+"</b><br/>线索:"+v[2]+"<br/>有意愿:"+v[3]+"<br/>主口径入驻:"+v[4]+"<br/>备用口径入驻:"+v[5]+"<br/>入驻率:"+v[6]+"%<br/>意愿→入驻:"+v[7]+"%";}')
    tpl = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>AM气泡矩阵V2 - __TAG__</title>
<script src="https://lf9-cdn-tos.bytecdntp.com/cdn/expire-1-M/echarts/5.4.2/echarts.min.js"></script>
<style>body{margin:0;font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:#fff}#c{width:100%;height:96vh}</style>
</head><body><div id="c"></div>
<script>var ch=echarts.init(document.getElementById('c'));ch.setOption(__OPT__);window.onresize=function(){ch.resize()};</script>
</body></html>"""
    return tpl.replace('__OPT__', opt_json).replace('__TAG__', '聚焦版' if clip else '全轴版')

open('am_bubble_v2_clip.html', 'w', encoding='utf-8').write(build_html(True))
open('am_bubble_v2_preview.html', 'w', encoding='utf-8').write(build_html(False))
# 部署版：把 CDN echarts 换成同域路径（deploy_site/echarts.min.js 已就位）
CDN = 'https://lf9-cdn-tos.bytecdntp.com/cdn/expire-1-M/echarts/5.4.2/echarts.min.js'
if os.path.isdir('deploy_site'):
    open('deploy_site/index.html', 'w', encoding='utf-8').write(
        build_html(True).replace(CDN, 'echarts.min.js'))
    open('deploy_site/full.html', 'w', encoding='utf-8').write(
        build_html(False).replace(CDN, 'echarts.min.js'))
json.dump(data, open('am_bubble_v2_data.json', 'w'), ensure_ascii=False, indent=1)
print('html ok')
for d in sorted(data, key=lambda z: -z['leads']):
    print(d['name'], d['x'], d['y'], d.get('q', 'PENDING'))
