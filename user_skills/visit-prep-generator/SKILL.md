---
name: visit-prep-generator
description: 基于风神双数据源生成跨境电商商家拜访前情报简报，支持 seller id 查询、EU/UK/JP 核心战场画像、US 标杆对比、数据质量显影、拜访建议与推荐话术输出。适用于商家BD、跨境电商运营、新人首次拜访、老客复访、季度拜访排期或需要把风神商家数据转成飞书拜访简报的场景。
author: 于奇楠 / Aime
metadata:
  version: "1.1"
  category: "运营工具 / 商家BD"
---

# 商家拜访准备生成器

version: 1.1
## Common Rationalizations

以下想法会导致拜访简报失真，必须回到本 Skill 流程：

- “只看一个市场就能判断商家状态。”
- “US 数据缺失可以凭经验补一个对比结论。”
- “风神字段没核对，先把报告写出来。”
- “没有写后回读也可以声称飞书文档已生成。”
- “商家没有数据时，用漂亮话术替代缺口说明。”

## Red Flags

出现任意信号时停止生成结论，先补齐数据或显式标记缺口：

- 未拿到 `seller id` 或 `global_seller_id` 就开始分析。
- EU/UK/JP 与 US 两条数据源未区分用途，或没有用 `global_seller_id` 对齐。
- 把 SKU、竞品、预测、ROI 或 CRM 后续动作写成 v1 能力。
- 关键数值没有口径、时间窗口、市场范围或数据源说明。
- 输出不是飞书文档，或创建文档时未遵守 `feishu-doc-writing-guide` 的个人空间与 RAW 验收要求。

## Verification

交付前逐项验收：

1. 输入完整：seller id 列表非空，目标市场至少包含 EU/UK/JP 之一，分析周期默认近 6 个月或由用户指定。
2. 双源成立：EU/UK/JP 使用核心战场数据源，US 使用标杆对比数据源，JOIN Key 为 `global_seller_id`。
3. 数据显影：缺失、空值、无法匹配、US 无数据均在简报中明确说明，不用推测替代。
4. 输出完整：每个商家包含基础画像、核心战场表现、US 标杆对比、3 条拜访建议、2-3 条推荐话术。
5. 飞书验收：使用 `feishu-doc-writing-guide` 生成飞书文档，并完成写后读回或工具返回验证；不得只返回本地 Markdown。
6. 边界合规：不输出 SKU 级、竞品横向、财务预测、GMV 承诺、拜访后 CRM 闭环。

## 合规默认值

- 目标市场：用户未指定时询问；不得默认全市场。
- 分析周期：默认近 6 个月。
- US 对比：默认拉取；无数据时输出“暂无 US 风神数据，无法进行标杆对比”。
- 输出形态：飞书文档，每个商家一页。
- 文档创建：使用 `feishu-doc-writing-guide`，默认落用户个人空间并保留 RAW 验收。
- 数据校验：可使用 `zero-trust-data-analyzer` 做空值、主键匹配、异常值显影。

## 数据源

- **EU/UK/JP 核心战场：** `https://aeolus-va.tiktok-row.net/pages/dataQuery?appId=555771&dashboardId=511872&id=2476255319&isDefault=1&reportQuerySchemaKey=1108ed5b-0140-4a00-b379-435bddfb7cbf&rid=5466004&sid=2770378&waitForDataReady=0`
- **US 标杆对比：** `https://aeolus-va.tiktok-row.net/pages/dataQuery?appId=555771&rid=5991071&sid=2770378`
- **统一主键：** `global_seller_id`

## 执行流程

1. **确认输入**
   - 获取 seller id 列表、目标市场、是否需要 US 对比、分析月份范围。
   - 若目标市场缺失，先追问；若 seller id 为空，停止。
   - 在任何风神查询或飞书写入前，运行 `python3 scripts/validate_visit_request.py --payload-json '<json>'`；失败即熔断并要求补齐输入。

2. **拉取风神数据**
   - 使用 `aeolus-platform-analysis` 获取 EU/UK/JP 核心战场数据。
   - 默认继续使用 `aeolus-platform-analysis` 获取 US 标杆数据。
   - 只把数据源作为查询入口，不把看板链接直接贴给业务读者替代分析。

3. **做零信任数据校验**
   - 优先检查 `global_seller_id` 是否能匹配两条数据源。
   - 检查商家名称、类目、GMV、渠道结构、市场、月份等字段是否缺失。
   - 可使用 `zero-trust-data-analyzer` 辅助显影空值、重复主键、异常趋势。

4. **形成拜访判断**
   - 先给商家基础画像，再给 EU/UK/JP 核心战场趋势与渠道结构。
   - US 有数据时输出可迁移经验；US 无数据时只说明无法对比，不构造标杆结论。
   - 把结论转化为 3 条拜访建议和 2-3 条推荐话术。

5. **生成飞书文档**
   - 使用 `feishu-doc-writing-guide` 输出飞书文档。
   - 采用 [标准输出模板](references/output-template.md) 的结构，每个商家一页。
   - 表格必须使用飞书支持的 HTML `<table>` 语法；不要使用 Markdown 管道表。

6. **交付与说明**
   - 返回飞书文档链接、数据周期、覆盖 seller 数、缺口列表和验证结果。
   - 如果因风神权限、字段缺失或飞书写入失败无法完成，说明失败点和已完成部分。

## 输出结构

每个商家页面包含：

1. 商家基础画像：名称、类目、GMV 量级、主要市场、入驻时长或可得基础信息。
2. 核心战场表现：EU/UK/JP 月度趋势、渠道结构、关键变化。
3. US 标杆对比：量级、渠道、趋势差异和可迁移经验；无数据则标记缺口。
4. 拜访建议重点：严格 3 条，按优先级排列。
5. 推荐话术方向：2-3 条，可直接用于开场、追问或资源讨论。

## 范围边界

v1 支持 seller 级商家情报、EU/UK/JP 核心战场、US 标杆对比、飞书文档、拜访建议与话术。不支持 SKU 级分析、竞品商家横向对比、复杂经营预测、GMV 目标承诺、资源 ROI 计算、拜访后纪要、任务拆解或 CRM 回写。

## 触发词

- 商家拜访准备
- seller id 拜访简报
- 风神商家画像
- EU/UK/JP 商家表现
- US 标杆对比
- 拜访建议话术

## 案例实录

- 用户输入：

```text
请基于 seller id 123456，生成 EU/UK/JP 商家拜访前情报简报，并拉取 US 对比。
```

- 标准输出：

```text
已生成飞书《商家拜访前情报简报》，覆盖 seller id 123456，周期为近 6 个月。文档包含基础画像、核心战场表现、US 标杆对比、3 条拜访建议和 3 条推荐话术；US 数据缺口已在对应模块显式标记。
```
