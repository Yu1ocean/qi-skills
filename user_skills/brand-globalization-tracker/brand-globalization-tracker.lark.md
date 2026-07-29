## 📌 技能简介
这是一个把品牌出海案例从网页/微信文章沉淀成结构化资产的技能。它不仅能抽品牌名、行业、关键打法、传播核心、案例亮点与标签数组，还新增了 **L1-L4 中立底层解构引擎**，可以直接生成深度复盘文档。

<callout icon="bulb" bgc="5">
  **发布定位：** 面向品牌案例库建设、品牌策略复盘与一号位经营启发场景。核心价值不是“复述文章”，而是把零散案例沉淀成 **案例卡片 + 时间切片 + 深度解构文档** 三层资产。
</callout>

## 🔑 触发词
- 核心关键词：
  - 品牌出海案例
  - 微信文章拆解
  - 深度解构报告
  - L1-L4 品牌复盘
  - 时间切片快照
  - 案例库回写
- 典型指令示例：
  > 把这篇品牌案例拆成结构化 JSON，并给我一份深度分析文档。
  > 用品牌出海案例挖掘机分析这篇微信文章，补齐当期切片并回写案例库。

## ⚙️ 核心架构 / SOP / 约束条件

### 工作流
1. **获取正文**：优先读取已抓取文本；若未提供，则直接对 URL 抓取正文。
2. **结构化萃取**：围绕品牌、行业、关键打法、传播核心、案例亮点、指标与标签数组进行抽取。
3. **中立底层解构**：若要求深度分析，按 `L1 核心驱动引擎 / L2 增长飞轮与流量模型 / L3 护城河与壁垒 / L4 一号位破局演练` 输出长文。
4. **结果标准化**：强制把标签字段转为数组，并合并生成去重后的 `all_tags`。
5. **多形态输出**：支持 JSON、Markdown、卡片 JSON 与深度报告四种结果落盘。
6. **案例库回写**：若任务要求写回 Bitable，必须先命中旧记录再定向 upsert。

### 强制字段
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

### 默认值
- 默认模型：`doubao-1.5-pro-32k-250115`
- 默认超时：`120s`
- 默认正文截断上限：`18000` 字符
- 默认案例主题 slug：`brand_case_1`
- 默认缺失策略：原文未提及则返回空数组 / 空字符串 / null
- 默认深度框架：中立解构，不预设单一成功因子

### 关键护栏
- 没有正文证据，不得直接结构化输出。
- `tags` 必须是数组，不得退化成逗号字符串。
- **严禁削足适履**：证据不足时，直接标注“证据不足 / 待验证”，不要硬塞结论。
- 必须区分 **历史拆解** 与 **当期切片**，避免把不同时间层混写。
- JSON、Markdown、卡片、深度文档四份结果必须口径一致。
- 如需回写案例库，必须先定位旧 record，再更新而不是盲插入。

<callout icon="star" bgc="3">
  **验收标准：** 结果至少包含 `brand_name`、`key_tactics`、`communication_core`、`case_highlights`、`all_tags`；若输出深度分析，必须严格使用 L1-L4 框架，并包含“下周可执行实验”和“关键风险提醒”。
</callout>

## 使用方式
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

## 输出产物
<table header-row="true" header-col="false" col-widths="180,360,240">
  <tr>
    <td>产物</td>
    <td>说明</td>
    <td>典型用途</td>
  </tr>
  <tr>
    <td>JSON</td>
    <td>结构化主结果，包含品牌、打法、传播核心、标签与指标数组</td>
    <td>案例库入库、二次分析、检索筛选</td>
  </tr>
  <tr>
    <td>Markdown</td>
    <td>便于人读的案例摘要</td>
    <td>复盘、分享、沉淀方法论</td>
  </tr>
  <tr>
    <td>Card JSON</td>
    <td>可直接作为交付卡片 payload，必须包含 tags</td>
    <td>群内播报、案例速览、轻量分发</td>
  </tr>
  <tr>
    <td>Deep Report</td>
    <td>基于 L1-L4 的中立深度拆解 Markdown 正文</td>
    <td>飞书深度文档、品牌复盘、策略迁移</td>
  </tr>
</table>

## 📖 案例实录 (Best Practice)
- 🧑‍💻 用户输入：
  ```text
  可以。迭代品牌案例技能。成功后再跑一遍现有案例。
  目标案例：https://mp.weixin.qq.com/s/2Iwayev3Xq9HfnnZ3m6QkA
  ```
- 🤖 标准输出：
  ```text
  输出 GuruNanda 的结构化 JSON、案例摘要、案例卡片与新版深度文档；新版文档严格使用 “L1 核心驱动引擎 / L2 增长飞轮与流量模型 / L3 护城河与壁垒 / L4 一号位破局演练”，并把深度文档链接回写到 GuruNanda 的案例库记录中。
  ```

### 当前技能信息
- 技能名：`brand-globalization-tracker`
- 发布别名：品牌出海案例挖掘机
- 当前版本：`1.2`
- 技能目录：`user_skills/brand-globalization-tracker`
