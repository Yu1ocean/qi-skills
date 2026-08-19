---
name: eu-am-efficiency-analyzer
description: EU AM（EU 招商商务）效率漏斗分析器。从飞书「明细_分析基盘」读取分析基盘，计算各 AM 的线索量 / 有意愿数 / 主口径入驻数 / 备用口径入驻数，输出漏斗阶段与段转化诊断、瓶颈定位与对标提升量化，并渲染白底气泡矩阵（ECharts HTML + PNG，全行业总览 + 分行业 Tab、四象限、中位数分界线），附带完整口径说明。适用场景：EU AM 效率复盘、招商漏斗诊断、AM 分层与瓶颈定位、入驻率/意愿转化率对比、气泡矩阵可视化。
author: 于奇楠
version: 1.0
---

# EU AM 效率漏斗分析器 (eu-am-efficiency-analyzer) v1.0

把 EU AM 招商效率从「一堆明细行」变成「可判断的漏斗诊断 + 可看懂的气泡矩阵」。计算内核纯函数、无副作用、内置双路重算与漏斗单调性断言（零信任校验）；渲染层强制白底，与计算解耦。

## Common Rationalizations（常见借口库）

以下话术一旦出现，等价于准备越过红线，必须立刻停下回到 SOP：

- 「MCP 链路麻烦，我直接拿 token 调飞书 OpenAPI 读一下 Sheet。」
- 「零信任校验 FAIL 只差一点点，先出图，数字后面再对。」
- 「主口径入驻时间没回填，我就当它 0 混进有效 AM 一起算中位数。」
- 「背景色是深色更好看，白底以后再改。」
- 「口径说明（截止日期 / 剔除规则 / 灰色 AM）先省了，看图的人自己懂。」
- 「罗才鑫这行留着也不影响大局。」

## Red Flags（危险信号）

出现任意一条即熔断或要求确认：

- 绕过 `lark-sheets` MCP 链路裸调 OpenAPI 读写飞书表格。
- `validate_zero_trust` 返回 FAIL 却继续导出 JSON / 渲染图表 / 对外交付。
- 中位数分界线把 `pending`（入驻时间待回填）AM 计入有效样本。
- 产出 HTML/PNG 背景非 `#FFFFFF`（或残留 `#111111` 深色块）。
- 交付物没有口径说明四要素（数据截止日期、剔除规则、灰色 AM 逻辑、主/备用口径定义）。
- 汇报里出现「应该 / 大概 / 大约」但没有可回读的数字证据。

## Verification（强制验收清单）

宣称「分析完成」时必须同时满足：

1. **来源可回读**：数据来自 `明细_分析基盘`，且走 MCP `lark-sheets` 读取，行数与飞书侧一致。
2. **零信任 PASS**：`validate_zero_trust` / `run_funnel_diagnosis.py` 退出码 0，无 FAIL 项。
3. **双口径齐备**：每个 AM 同时给出主口径入驻数（EU/UK 入驻时间有值）与备用口径入驻数（状态=5-已入驻）。
4. **剔除生效**：`罗才鑫` 已剔除，有效 AM 数与灰色 AM 数在输出中显式打印。
5. **白底断言**：PNG 四角像素为 `(255,255,255)`；HTML 含 `backgroundColor` 且不含 `111111`。
6. **象限与分界线**：分界线取**有效 AM**（非 pending）中位数，四象限命名为明星 / 精耕小池 / 规模待提效 / 待突破。
7. **口径说明随交付**：数据截止日期、剔除规则、灰色 AM 复核提示一并输出。

## 合规默认值（Defaults）

- 数据源 Sheet：`https://bytedance.my.larkoffice.com/sheets/Bi8msSkCqhBywbtRGlomkoYJylg`
- 工作表名：`明细_分析基盘`（读取只走 MCP `lark-sheets`，`include_secrets=true`）
- 默认分组维度：`负责AM`（内核维度无关，可传 `行业` / `国家`）
- 默认剔除名单：`罗才鑫`
- 背景色：`#FFFFFF`（HTML `backgroundColor` + matplotlib fig/ax/savefig facecolor）
- 零信任校验：默认开启，FAIL 即熔断
- 结果 JSON 默认名：`am_funnel_diagnosis.json`

## ⚙️ 核心架构 / SOP

```
飞书 明细_分析基盘 --(MCP lark-sheets)--> DataFrame/CSV
   └─> am_analysis_core（纯计算：阶段/段转化/瓶颈/对标/零信任）
         └─> run_funnel_diagnosis.py（薄 CLI + L3 断言）--> result.json
   └─> render_bubble_matrix.py --> 白底 ECharts HTML（聚焦版/全轴版）+ PNG + data.json
```

### Step 1 · 读取分析基盘（禁止裸调 OpenAPI）

使用 `lark-sheets` 技能读取，例如：

```bash
lark-cli sheets +csv-get --url "https://bytedance.my.larkoffice.com/sheets/Bi8msSkCqhBywbtRGlomkoYJylg" \
  --sheet-name "明细_分析基盘" > /tmp/eu_am_base.csv
```

调用飞书相关脚本/命令时必须设置 `include_secrets=true`。先 `+workbook-info` 确认工作表名，再读取；不要凭直觉猜 sheet 名。

### Step 2 · 计算漏斗指标

每个 AM 输出四个基础量：

| 指标 | 口径 |
|---|---|
| 线索量 | 该 AM 名下线索行数 |
| 有意愿数 | 意愿标记为有意愿的行数 |
| 主口径入驻数 | EU / UK 入驻时间字段**有值** |
| 备用口径入驻数 | 入驻状态 = `5-已入驻` |

派生：主口径入驻率 = 主口径入驻 / 线索量；备用口径意愿→入驻转化率 = min(备用口径入驻, 有意愿) / 有意愿。

诊断（阶段表 / 段转化 / 瓶颈 / 对标提升 / 零信任）走内核：

```bash
cd user_skills/eu-am-efficiency-analyzer
python3 scripts/run_funnel_diagnosis.py --csv /tmp/eu_am_base.csv --dim 负责AM --out am_funnel_diagnosis.json
```

内核 API（详见 [references/am_analysis_core_README.md](references/am_analysis_core_README.md)）：`FunnelSpec` / `build_snapshots_from_dataframe` / `compute_stage_table` / `compute_segment_table` / `locate_bottleneck_and_gain` / `classify_phase` / `build_heat_matrix` / `rank_bottlenecks` / `quantify_benchmark_uplift` / `validate_zero_trust` / `run_diagnosis` / `export_json`。

> 能力归属说明（如实标注）：漏斗阶段诊断能力**内聚在 `scripts/am_analysis_core.py`**，本技能不存在独立的 `funnel_stage_analyzer.py`（源项目磁盘上亦无该文件）。`scripts/run_funnel_diagnosis.py` 是围绕 `run_diagnosis` **新写的薄封装 CLI**，不是从旧文件迁移而来。

### Step 3 · 渲染白底气泡矩阵

```bash
cd user_skills/eu-am-efficiency-analyzer && python3 scripts/render_bubble_matrix.py
```

- 横轴 = 主口径入驻率；纵轴 = 备用口径意愿→入驻转化率；气泡大小 = 线索量。
- 分界线 = **有效 AM**（主口径入驻数 > 0）中位数；四象限：明星（右上）/ 精耕小池（左上）/ 规模待提效（右下）/ 待突破（左下）。
- 主口径入驻时间待回填的 AM 记为 `pending`，以**灰色气泡**落在备用口径位置并标注「需复核」，不参与中位数计算。
- 输出：`am_bubble_v2_clip.html`（聚焦版）、`am_bubble_v2_preview.html`（全轴版）、PNG、`am_bubble_v2_data.json`；`deploy_site/` 存在时同步产出同域版。
- 全行业总览 + 分行业 Tab：按 `行业` 维度重复 Step 2/3，各行业一个 series/Tab，共用同一套象限与配色。
- 白底为硬约束：改动渲染层后必须复验 PNG 四角像素 `(255,255,255)`，HTML 含 `backgroundColor` 且不含 `111111`。

### Step 4 · 输出口径说明（不可省）

交付必须附：数据截止日期；剔除规则（如剔除罗才鑫）；灰色 AM 逻辑（入驻时间待回填 → 备用口径 + 灰色 + 需复核）；主/备用口径定义；有效 AM 数与灰色 AM 数。

## 📖 案例实录

- 🧑‍💻 用户输入：`分析一下 EU AM 的招商效率，出个气泡矩阵`
- 🤖 标准输出：
  1. MCP 读取 `明细_分析基盘` → 24 位有效 AM（已剔除罗才鑫）；
  2. `run_funnel_diagnosis.py` 退出码 0、零信任 PASS；
  3. 白底 ECharts 聚焦版/全轴版 HTML + PNG，中位数分界线 x=…、y=…；
  4. 附口径说明与灰色 AM 复核清单。

## 变更记录

- **v1.0**：首版。内核 `am_analysis_core.py`（含零信任双路重算与漏斗单调性断言）+ 白底渲染层 `render_bubble_matrix.py` + 薄封装 CLI `run_funnel_diagnosis.py`（L3 断言熔断）；补齐 L1 反合理化三件套与 L2 合规默认值。
