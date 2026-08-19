# EU AM 效率漏斗分析器 (eu-am-efficiency-analyzer) v1.0 技能说明

<figure view-type="Card"><source name="eu-am-efficiency-analyzer.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NzE3MWYzMzRkY2MwYjdkMWQzOThlMzNjNTNiMGUwZGJfNjQ2YmU3ZWY4M2MxODE1ZDlkZjYzM2FhZWQxZGQyNjJfSUQ6NzY3NTY1MDA4OTMyMjMxOTQ3Nl8xNzg3MTI2NTU2OjE3ODcxMzAxNTZfVjM" mime="application/zip" size="28851" token="IzqZblVuTom3cSxolQcmufJkyxh"/></figure>

## 📌 技能简介

`eu-am-efficiency-analyzer`（EU AM 效率漏斗分析器 v1.0）把 EU 招商商务（AM）的效率评估，从「一堆明细行 + 手工透视」升级为「可判断的漏斗诊断 + 可看懂的白底气泡矩阵」。它从飞书底层数据库读取分析基盘，计算每位 AM 的线索量 / 有意愿数 / 主口径入驻数 / 备用口径入驻数，输出阶段与段转化诊断、瓶颈定位与对标提升量化，并渲染 ECharts 气泡矩阵（全行业总览 + 分行业 Tab 切换）。计算内核纯函数无副作用，内置双路重算与漏斗单调性断言（零信任校验），渲染层强制白底。

适用谁：EU AM 团队负责人、招商效率复盘同学、需要做 AM 分层与瓶颈定位的分析同学。

## 🔑 触发词

- 核心关键词：

  - EU AM 效率
  - AM 漏斗诊断 / 招商漏斗
  - 气泡矩阵 / 四象限 AM 分层
  - 入驻率 / 意愿→入驻转化率
  - 明细_分析基盘
- 典型指令示例：

  > 分析一下 EU AM 的招商效率，出个气泡矩阵  
  > 按行业拆一下 AM 的入驻率和意愿转化率，定位瓶颈环节

## ⚙️ 核心架构 / SOP / 约束条件

```
飞书「明细_分析基盘」--(MCP lark-sheets)--> DataFrame / CSV
   └─> am_analysis_core.py（纯计算：阶段表 / 段转化 / 瓶颈 / 对标 / 零信任校验）
         └─> run_funnel_diagnosis.py（薄封装 CLI + L3 运行时断言）--> result.json
   └─> render_bubble_matrix.py --> 白底 ECharts HTML（聚焦版 / 全轴版）+ PNG + data.json
```

**Step 1 · 读取分析基盘**：数据源 `https://bytedance.my.larkoffice.com/sheets/Bi8msSkCqhBywbtRGlomkoYJylg`，工作表 `明细_分析基盘`。读取必须走 MCP `lark-sheets` 链路（`lark-cli sheets +csv-get`），禁止裸调飞书 OpenAPI；涉及飞书的脚本调用必须 `include_secrets=true`。

**Step 2 · 计算漏斗指标**：

| 指标 | 口径 |
|-|-|
| 线索量 | 该 AM 名下线索行数 |
| 有意愿数 | 意愿标记为「有意愿」的行数 |
| 主口径入驻数 | EU / UK 入驻时间字段**有值** |
| 备用口径入驻数 | 入驻状态 = `5-已入驻` |

派生：主口径入驻率 = 主口径入驻 / 线索量；备用口径意愿→入驻转化率 = min(备用口径入驻, 有意愿) / 有意愿。

**Step 3 · 渲染气泡矩阵**：横轴 = 主口径入驻率，纵轴 = 备用口径意愿→入驻转化率，气泡大小 = 线索量；分界线取**有效 AM**（主口径入驻 > 0）中位数；四象限 = 明星（右上）/ 精耕小池（左上）/ 规模待提效（右下）/ 待突破（左下）。支持全行业总览 + 分行业 Tab 切换。背景强制白底 `#FFFFFF`。

**Step 4 · 口径说明（不可省）**：数据截止日期、剔除规则（如剔除罗才鑫）、灰色 AM 逻辑（入驻时间待回填 → 落备用口径、灰色气泡、标注需复核、不参与中位数）、主/备用口径定义、有效 AM 数与灰色 AM 数。

**约束条件（三层护栏）**：

- L1 认知层：SKILL.md 顶部固化 Common Rationalizations / Red Flags / Verification 三件套。
- L2 默认层：合规默认值（数据源、工作表名、默认维度 `负责AM`、剔除名单、白底 `#FFFFFF`、零信任默认开启）。
- L3 断言层：`run_funnel_diagnosis.py` 在落盘前执行 `validate_input_path` / `validate_snapshots` / `validate_zero_trust_passed` / `validate_output_written`，任一失败 `raise` 熔断（退出码 2）。
- 零信任校验 FAIL 禁止导出结果或对外交付；白底断言要求 PNG 四角像素 `(255,255,255)`、HTML 含 `backgroundColor` 且不含 `111111`。

**能力归属如实说明**：漏斗阶段诊断能力内聚在 `scripts/am_analysis_core.py`；本技能不存在独立的 `funnel_stage_analyzer.py`（源项目磁盘上亦无该文件）。`scripts/run_funnel_diagnosis.py` 是围绕 `run_diagnosis` 新写的薄封装 CLI，并非从旧文件迁移。

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：

```text
分析一下 EU AM 的招商效率，出个气泡矩阵
```

- 🤖 标准输出：

```text
1. MCP lark-sheets 读取「明细_分析基盘」→ 24 位 AM（已剔除罗才鑫）
2. run_funnel_diagnosis.py 退出码 0，零信任校验 PASS（双路重算一致 + 漏斗单调）
3. 白底 ECharts 气泡矩阵：聚焦版 am_bubble_v2_clip.html / 全轴版 am_bubble_v2_preview.html + PNG
   分界线 = 有效 AM 中位数；四象限：明星 / 精耕小池 / 规模待提效 / 待突破
4. 附口径说明：数据截止日期、剔除规则、灰色 AM（入驻时间待回填，走备用口径，需复核）
```