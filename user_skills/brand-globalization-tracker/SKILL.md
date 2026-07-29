---
name: brand-globalization-tracker
description: 抓取品牌出海案例正文并萃取品牌名称、关键打法、传播核心、案例亮点、标签数组与深度解构报告，支持输出 JSON、Markdown、案例卡片和 L1-L4 深度文档。适用于品牌案例库建设、微信文章/网页拆解、品牌策略复盘、案例归档与 Bitable 持续沉淀场景。
---

# Brand Globalization Tracker

version: 1.3

用于把分散在网页、微信文章与公开资料里的品牌案例，沉淀成 **可索引卡片 + 可追溯切片 + 可复盘深度文档** 三层资产。

新增 **内外双轨输出标准**：
- **Plan A（内部案例库骨架）**：用于内部沉淀，默认采用极简 L1-L4 骨架，强调短、硬、可横向复用。
- **Plan B（对外呈现版）**：用于对外汇报或跨团队分享，默认采用三段式结构：`赢在哪里 / 别人为什么学不会 / 下周我们能做什么`。
- 若用户只说“生成案例文档”但未指明内外用途，必须先根据上下文判断；判断不出来时，优先产出 **Plan A 内部版**，并显式说明可补一份对外版。

## Common Rationalizations（常见借口库）
- “先把案例讲顺，底层驱动以后再补。”
- “这个品牌看起来像 DTC，我先按 DTC 模板套进去。”
- “证据不够也没关系，先把四层框架填满。”
- “深度文档先复述文章，经营启发回头再提炼。”
- “先把文档发出来，案例库回写以后再说。”

## Red Flags（危险信号）
- 没拿到正文证据或官方切片，就开始输出结构化结论。
- 把品牌成功简单归因于单一因素，如“全靠达人”或“全靠低价”。
- 输出 L1-L4 框架时，为了凑结构强行塞结论，而不是标注“证据不足 / 待验证”。
- JSON、Markdown、卡片、深度文档四份结果口径不一致。
- 宣称“已入库”，但没有命中 record_id 或没有完成写后校验。
- 明明是对外汇报，却仍沿用内部 L1-L4 学术拆解口径，导致可讲述性不足。
- 明明是内部案例库沉淀，却写成大段对外宣讲稿，导致后续横向比对困难。

## Verification（强制验收清单）
完成一次案例拆解时，必须同时满足：
1. 已拿到可追溯的正文文本或本地文本源。
2. JSON 中至少包含 `brand_name`、`key_tactics`、`communication_core`、`case_highlights`、`all_tags`。
3. 标签维度至少输出 `industry_tags`、`marketing_tags`、`target_audience_tags` 三个数组。
4. `all_tags` 已做去重，且覆盖各标签数组中的标签。
5. 若输出 **Plan A 内部案例库版**，必须严格使用 L1-L4：`L1 核心驱动引擎 / L2 增长飞轮与流量模型 / L3 护城河与壁垒 / L4 一号位破局演练`。
6. 若输出 **Plan B 对外呈现版**，必须严格使用三段式结构：`赢在哪里 / 别人为什么学不会 / 下周我们能做什么`。
7. 两种文档都必须包含“下周可执行实验”或等价的行动建议；内部版还必须包含“关键风险提醒”。
8. 无法确认的字段返回空数组、空字符串、null 或明确标注“证据不足 / 待验证”，不得伪造。
9. 如任务要求写入案例库，必须先定位旧 record，再定向 upsert，并完成 RAW 级回读确认。

## 输入要求
- 必填：案例 URL。
- 可选：已抓取好的正文文本路径。
- 可选：官方切片 JSON（TikTok / Instagram / 官网等当期快照）。
- 可选：JSON / Markdown / card / 深度报告的输出路径。
- 可选：案例库 Base token、表 ID、目标 record_id（若任务要求落库）。

## ⚙️ 核心架构 / SOP / 约束条件

### Step 1：获取正文与证据源
- 优先直接使用 `scripts/analyze_brand_case.py --source-text <file>` 读取已抓取文本。
- 若未提供 `--source-text`，脚本直接对 URL 抓取正文。
- 若任务要求“时间切片”或“新版深度文档”，补充官方切片信息，整理成一个 JSON 文件后再传给脚本。

### Step 2：结构化萃取
- 使用脚本内置 schema 做结构化抽取。
- 必须保留以下核心字段：
  - `brand_name`
  - `industry`
  - `summary`
  - `key_tactics`
  - `communication_core`
  - `case_highlights`
  - `metrics`
  - `industry_tags`
  - `marketing_tags`
  - `target_audience_tags`
  - `content_tags`
  - `channel_tags`
  - `product_tags`
  - `geo_tags`
  - `all_tags`
- 标签必须短语化、可复用，适合沉淀进案例库或后续筛选。

### Step 3：双轨解构文档引擎
- 若任务要求深度分析，先判断产物用途属于 **内部沉淀** 还是 **对外呈现**。
- **Plan A（内部案例库骨架）**：用于内部沉淀、案例库归档、方法论复盘时输出。
  - 必须按以下框架输出：
    - **L1 核心驱动引擎**：这个品牌到底靠什么核心机制跑出来。
    - **L2 增长飞轮与流量模型**：内容、渠道、货盘、转化如何联动。
    - **L3 护城河与壁垒**：哪些能力可积累，哪些只是平台红利。
    - **L4 一号位破局演练**：给其他品牌/创始人的迁移打法、实验设计与边界条件。
  - 风格要求：短、硬、中立、方便横向比对；少写铺陈，多写判断与复用点。
- **Plan B（对外呈现版）**：用于老板汇报、跨团队分享、对外沟通材料时输出。
  - 必须按以下结构输出：
    - **赢在哪里**：用业务语言说明这个品牌的核心胜因。
    - **别人为什么学不会**：说明壁垒来自哪里，避免只复述结果。
    - **下周我们能做什么**：把案例翻译成 3 个以内可执行动作。
  - 风格要求：结论先行、讲述性强、减少学术拆解腔，增强可讲、可抄作业、可带行动。
- 若用户明确要求“两个版本都要”，必须同时产出 Plan A + Plan B，并保持底层判断一致、只是表达层不同。
- **严禁削足适履**：如果案例证据不足，不要强行往模板里塞结论，直接标注“证据不足 / 不成立 / 待验证”。
- 必须显式区分 **历史拆解** 与 **当期切片**，避免把旧报道和当下状态混成一个时间面。

### Step 4：结果标准化
- 所有标签字段强制转成数组。
- `all_tags` 强制由各标签字段合并去重生成。
- 若 `industry` 为空但 `industry_tags` 非空，默认取首个行业标签回填到 `industry`。
- 指标字段统一为对象数组：`name / value / unit / period / evidence`。

### Step 5：多形态输出
- `--output-json`：写出结构化主结果。
- `--output-markdown`：生成便于阅读的案例摘要。
- `--output-card`：生成可交付的案例卡片 JSON，其中必须包含 tags。
- `--output-deep-report`：生成深度文档正文。
  - 若目标是 **Plan A 内部版**，输出极简 L1-L4 骨架。
  - 若目标是 **Plan B 对外版**，输出 `赢在哪里 / 别人为什么学不会 / 下周我们能做什么` 三段式正文。
  - 若用户要求双轨输出，则分别生成两份文档，不得把两个结构混写在同一正文里。

### Step 6：案例库回写（任务要求时执行）
- 先在案例库 Bitable 中按品牌名检索旧记录，命中后优先更新，不得盲目新建重复行。
- 写入前先读取字段结构，确认字段名、类型、单选/多选选项。
- 写入后必须等待并回读关键字段，确认深度文档链接、切片摘要、业务标签等已落盘。
- 若任务未明确要求落库，可跳过本步。

## 合规默认值（Defaults）
- 默认模型：`doubao-1.5-pro-32k-250115`
- 默认超时：`120s`
- 默认正文截断上限：`18000` 字符
- 默认案例主题 slug：`brand_case_1`
- 默认标签维度：`industry_tags`、`marketing_tags`、`target_audience_tags` 必填
- 默认缺失策略：原文未提及则返回空数组 / 空字符串 / null
- 默认底层分析立场：中立解构，不带预设品牌成败立场
- 默认深度文档制式：**Plan A 内部案例库骨架**
- 默认对外汇报制式：**Plan B 三段式（赢在哪里 / 别人为什么学不会 / 下周我们能做什么）**

## 调用方式
在技能目录下直接运行：

```bash
python3 scripts/analyze_brand_case.py \
  --url "https://mp.weixin.qq.com/s/xxxx" \
  --source-text "path/to/article.txt" \
  --official-snapshots-json "path/to/official_snapshots.json" \
  --output-json "outputs/case.json" \
  --output-markdown "outputs/case.md" \
  --output-card "/workspace/.ephemeral_pool/[TASK_ID]_brand_case_1.card.json" \
  --output-deep-report "outputs/case_deep_report.md"
```

**⚠️ 注意：**
- 调用脚本时必须通过 `bash` 工具直接执行。
- 涉及 LLM 调用时，必须设置 `include_secrets=true`。
- 若要把深度报告发布为飞书文档，必须使用 `feishu-doc-writing-guide` 与 `lark-doc` 链路。
- 若要更新多维表格，必须先读取字段结构，再使用 `lark-cli base +record-upsert` 定向更新。

## 输出字段建议
- `industry_tags`：如口腔护理、保健消费、天然疗法
- `marketing_tags`：如创始人IP、UGC、直播带货、中腰部达人
- `target_audience_tags`：如敏感牙人群、健康养生人群、TikTok冲动消费人群
- `channel_tags`：如 TikTok Shop、直播、短视频、达人分销
- `geo_tags`：如 美国、TikTok美区

## 📖 案例实录 (Best Practice)
- 🧑‍💻 用户输入：
  ```text
  迭代品牌案例技能。成功后再跑一遍现有案例。
  目标案例：https://mp.weixin.qq.com/s/2Iwayev3Xq9HfnnZ3m6QkA
  ```
- 🤖 标准输出：
  ```text
  若用于内部沉淀：输出 GuruNanda 的结构化 JSON、案例摘要、案例卡片与 Plan A 内部案例库骨架文档；文档框架为“L1 核心驱动引擎 / L2 增长飞轮与流量模型 / L3 护城河与壁垒 / L4 一号位破局演练”。

  若用于对外汇报：输出 Plan B 对外案例文档；文档框架为“赢在哪里 / 别人为什么学不会 / 下周我们能做什么”。

  若用户要求双轨输出：同时生成 Plan A + Plan B 两份飞书文档，并确保底层判断一致、表达层分轨。
  ```

## 更新日志 (Changelog)
- 1.3（2026-06-06）：新增“内外双轨输出标准”；内部默认采用 Plan A 极简 L1-L4 骨架，对外默认采用 Plan B 三段式“赢在哪里 / 别人为什么学不会 / 下周我们能做什么”，并补充默认选择逻辑与验收标准。
- 1.2（2026-06-06）：升级为中立底层解构引擎；新增 L1-L4 深度报告输出、官方切片 JSON 输入、`--output-deep-report` 参数，以及“严禁削足适履”的分析红线。
- 1.1（2026-06-06）：首次正式发布，支持微信文章案例抓取、LLM 结构化萃取、标签数组输出，以及 JSON / Markdown / 卡片三种落盘格式。
- 0.1（2026-06-06）：初版脚手架。
