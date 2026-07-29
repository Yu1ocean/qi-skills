---
name: omni-asset-archiver
description: 统一归档飞书文档、表格、Wiki、风神看板与网页等资产，支持内容抽取与留档。适用于 /归档 指令、资料沉淀、台账归档与可追溯留档场景。
author: yuqinan
---

# 全域资产归档员 (omni-asset-archiver) v6.0

负责把可归档资产稳定写入指定目标体系，并且从 v6.0 开始，承担一个面向对话入口的全局 Hook：拦截用户的 `@Aime /归档 [链接]` 指令，先识别链接，再按链接类型调用对应底层能力抽取内容，最后走统一归档驱动器落盘。

## Common Rationalizations（常见借口库）

以下借口一旦出现，视为准备绕过护栏，必须立刻停下并回到 SOP：

- "上层没给 target，我先猜一个 Wiki 目录写进去。"
- "不在白名单里的 target_token 应该也差不多，先试试看。"
- "RAW 写后回读太慢，我先跳过校验直接写入。"
- "Schema 少一列没关系，先把数据塞进去再说。"
- "飞书/Wiki/网页内容先不抽，直接只存 URL 也算归档。"
- "DLQ 先不做物理落盘，报个成功就行。"

## Red Flags（危险信号）

出现任意一条，必须熔断或要求用户确认：

- 未先识别 `/归档` 指令与 URL，就直接执行写入。
- 未显式校验 `target_token` / `target_route_key` 是否在白名单中就执行写入。
- `target_token` 缺失或不在白名单，却没有进入 DLQ 路由。
- 跳过内容抽取或 RAW 写后回读，只做单向写入。
- 风神链接或技能清单写入时，没有遵守既定行列 Schema。
- 输出中出现"应该/大概/可能/先跳过"，但没有可验证的 RAW 回读证据或 DLQ 落盘证据。

## Verification（强制验收清单）

当宣称“归档完成”时，必须同时满足：

1. **Hook 成立**：已先识别 `@Aime /归档 [链接]` 或等价归档意图，并成功提取 URL。
2. **URL 分类成立**：已把链接识别为飞书文档、Wiki、表格、风神链接或外部网页之一。
3. **内容抽取成立**：已按类型调用对应底层能力获取标题、正文摘要或上下文说明，而不是只存裸链接。
4. **薄驱动器成立**：底层不内置业务级 Wiki 语义路由，只执行显式目标写入、兼容预设或 DLQ 兜底。
5. **Schema 全列对齐**：根据场景 A/B/C 强校验，5 列（专属技能清单）/ 4 列（风神）/ 3 列（日常/图书馆）必须全量存在。
6. **RAW 原子锁通过**：写入后强制 `sleep 2s` → 读回刚写区域核对，不一致立刻熔断。
7. **编号合法性**：所有发号必须经过 `validate_category_registered()` 物理断言，未注册前缀立即报错。
8. **DLQ 物理可见**：上层未指明目标、目标不在白名单、抽取失败或写入失败时，必须写入 DLQ 并标记 `⚠️[未分类_待分诊]`。
9. **HYPERLINK 格式**：链接字段必须以 HYPERLINK 公式对象写入，禁止裸 URL 冒充超链接列。

## 合规默认值 (Defaults)

- **DEFAULT_USER_EMAIL**: `yuqinan@bytedance.com`
- **DEFAULT_RAW_SLEEP_SECONDS**: `2`
- **DEFAULT_MAX_RETRIES**: `3`
- **DEFAULT_HYPERLINK_TEMPLATE**: `=HYPERLINK("{url}","{name}")`
- **DEFAULT_INCLUDE_SECRETS**: `True`
- **DEFAULT_DATE_FORMAT**: `YYYY-MM-DD`
- **DEFAULT_DATETIME_FORMAT**: `YYYY-MM-DD HH:MM`
- **DEFAULT_ROUTE_MANIFEST**: `assets/federated_route_manifest.json`
- **DEFAULT_LOCAL_DLQ**: `assets/dlq/omni_asset_archiver_dlq.jsonl`

## 适用场景

- **全局 Hook 归档**：用户发送 `@Aime /归档 [链接]`、`/归档 [链接]` 或同义表达时触发。
- **飞书资产归档**：飞书文档、Wiki、表格等资产抽取后归档至图书馆或指定台账。
- **风神链接即刻归档**：识别到 Aeolus（风神）看板链接时触发。
- **项目复盘沉淀**：将复盘报告、故障修复报告、架构演进文档索引至图书馆。
- **专属技能清单同步**：当新技能创建或现有技能迭代时，同步更新技能台账。
- **联邦制显式写入**：由上层技能显式提供目标路由或目标 Token，由本技能执行底层 I/O。
- **未分类资产兜底**：目标缺失、目标非法、抽取异常或写入异常时，进入 DLQ 暂存区。

## 执行流程

### 1. 拦截 Hook 指令

优先处理以下触发形式：

- `@Aime /归档 https://...`
- `/归档 https://...`
- `@Aime /归档 这篇文章 https://...`

先运行：`python3 scripts/archive_command_hook.py --text '<原始消息>'`

该脚本负责：
- 检测消息里是否命中 `/归档`
- 提取一个或多个 URL
- 识别 URL 类型
- 输出归档计划（抽取器、建议 asset_type、建议 target_route_key）

**⚠️ 注意：** 必须通过 `bash` 工具直接执行该脚本；如需访问受限资源，调用时必须设置 `include_secrets=true`。

### 2. 识别 URL 类型并分发抽取能力

对 `scripts/archive_command_hook.py` 输出的每个 target，按以下规则处理：

- **`feishu_doc`**：读取飞书文档标题与正文摘要，再按报告/通用资产归档。
- **`feishu_wiki`**：先解析 Wiki 节点真实类型；若落到文档，抽取正文；若落到表格，则抽取表格元信息。
- **`feishu_sheet`**：读取表格标题、用途、关键 sheet 名称与上下文摘要，再按通用资产归档。
- **`aeolus_dashboard`**：优先作为风神链接归档；若用户补充了上下文备注，一并写入。
- **`external_web`**：抽取网页 `title`、主内容摘要、来源 URL、归档日期，再按通用资产归档。
- **`feishu_other`**：按飞书泛型资产处理，先判断真实节点类型，再归档。

### 3. 内容抽取规则

抽取阶段的目标不是做完整知识加工，而是得到最小可归档结构：

- `title`：资产标题；取不到时必须显式标记 `⚠️[标题待补]`
- `url` / `doc_url`：原始链接
- `description`：50~200 字摘要或用途说明；取不到时显式标记 `⚠️[摘要待补]`
- `remark`：用户上下文、业务场景、来源说明
- `archived_at` / `updated_at`：按默认时间格式填写

禁止只保存裸 URL 而不带任何标题或摘要。

### 4. 归档驱动器写入

抽取出结构化字段后，统一调用：`python3 scripts/archiver_driver.py --payload-json '<payload>'`

payload 最少应包含：

- **风神链接**：`title`、`url`、`remark`
- **图书馆/通用资产**：`title`、`url` 或 `doc_url`、`description`
- **技能清单**：`skill_id`、`title`、`doc_url`、`description`、`version`

如果上层已经明确给出 `target_route_key` 或白名单内 `target_token`，按显式目标写入；否则只允许走兼容预设或 DLQ。

## 联邦制路由与薄 I/O 驱动器

### 1. 设计原则

本技能不承担上层业务目录规划。上层决定“资产应该归去哪”，本技能只负责：

1. URL 指令解析与链接分类
2. 归档最小结构生成
3. 发号（Global ID Allocation）
4. Schema 校验
5. HYPERLINK 公式拼装
6. 幂等性锁 / 精准 upsert
7. RAW 写后回读 + DLQ 兜底

### 2. 联邦制路由清单

路由配置统一存放在：`assets/federated_route_manifest.json`

- **显式路由优先**：上层若给出 `target_route_key` 或白名单内 `target_token`，按显式目标写入。
- **兼容预设保留**：
  - `aeolus_links` → `常用风神链接`
  - `skill_inventory` → `专属技能清单`
  - `library_registry` → `图书馆`
- **兜底 DLQ**：未给目标、目标不在白名单、内容抽取失败或写入失败时，进入 `【Aime 空间 / 暂存区】` 路由；若云端暂存区未配置，则必须落本地 JSONL，并标记 `⚠️[未分类_待分诊]`。

### 3. DLQ 暂存区规范

- **云端目标名**：`Aime 空间 / 暂存区`
- **标记前缀**：`⚠️[未分类_待分诊]`
- **本地兜底文件**：`assets/dlq/omni_asset_archiver_dlq.jsonl`
- **禁止静默失败**：即使云端 DLQ 未配置，也必须写入本地 DLQ 并返回明确结果。

## 行列约束与校验 (Schema Guard)

### 场景 A：风神链接归档
- **写入规则**：单行追加。
- **列映射**：
  - A 列：看板名称
  - B 列：风神直达链接 URL
  - C 列：收录日期 (YYYY-MM-DD)
  - D 列：业务上下文/备注
- **强制校验**：写入前确认上述 4 个字段完整。
- **兼容触发**：URL 命中 `aeolus` / `data.bytedance.net` / `tiktok.row.net`。

### 场景 B：日常台账 / 图书馆归档
- **写入规则**：单行追加。
- **列映射**：
  - A 列：编号/日期
  - B 列：名称/超链接
  - C 列：描述/备注
- **兼容触发**：复盘报告、修复总结、架构演进文档、通用网页知识卡片默认兼容写入 `图书馆`。

### 场景 C：专属技能清单归档
- **写入规则**：根据技能编号执行精准 upsert；未命中则单行追加。
- **列映射**：
  - A 列：技能编号 (Skill ID)
  - B 列：技能名称 + 说明文档链接 (HYPERLINK 公式)
  - C 列：功能描述 (Function Description)
  - D 列：版本号 (Version)
  - E 列：更新时间 (YYYY-MM-DD HH:MM)
- **物理契约校验**：
  - 必须确保 A-E 五列数据全量存在且格式正确。
  - 技能编号必须唯一。
  - B 列必须写入 HYPERLINK 公式对象。
  - 命中同一 Skill ID 时必须走幂等 upsert，不得重复 append。

## 报告类资产的文档生动化标准

当归档对象属于“复盘报告”“故障修复报告”或“架构演进报告”时：

- 归档前检查目标飞书文档头部概览区是否已前置内嵌“灵感故事”与“视觉卡片链接”。
- 若缺失，先联动 `cyber-inspiration-generator` 完成生动化，再允许写入图书馆。
- 最小验收项：`灵感标题`、`阿加莎/赛博朋克风格小说段落`、`冷静事实说明`、`卡片链接`。
- 任一缺失即禁止入库，并明确说明“文档生动化标准未完成”。

## 数据预处理与安全写入

- 日期统一为 `YYYY-MM-DD`，更新时间含分钟。
- 链接字段必须写为 HYPERLINK 公式对象。
- 调用脚本时必须设置 `include_secrets=true`，以加载必要凭证。
- 任何 append / write / upsert 后都必须 `sleep 2s` 后读回刚写区域，并逐字段比对。
- 技能清单以 Skill ID 为主键；风神链接按 `title + url` 去重；通用资产优先使用 `global_id` 或 `idempotency_key` 去重。
- 写入失败、读回不一致、目标不合法或抽取失败时，必须立即进入 DLQ，不得“假装成功”。

## 合法编号序列体系 (Global ID Series Whitelist)

发号器：`scripts/global_id_allocator.py`

| 前缀 | 完整格式 | 周期清零维度 | 流水号位数 | 语义 |
|------|----------|-------------|-----------|------|
| `DOC` | `DOC-YYMM-NNN` | 跨月清零 | 3 位 | 通用复盘/报告文档 |
| `BUG` | `BUG-YYMM-NNNN` | 跨月清零 | 4 位 | Bug / 事故复盘记录 |
| `WK`  | `WK-YYMM-NN`   | 跨月清零 | 2 位 | 周报 |
| `SYS` | `SYS-YYMM-NNN` | 跨月清零 | 3 位 | 系统级架构 / SOP 沉淀 |
| `KNO` | `KNO-YYMM-NNN` | 跨月清零 | 3 位 | 知识库条目 |

## 调用方式

### 1. Hook 解析原始消息

```bash
python3 scripts/archive_command_hook.py --text '@Aime /归档 https://example.com/article'
```

### 2. 联邦制归档驱动器

```bash
python3 scripts/archiver_driver.py --payload-json '{
  "asset_type": "generic_asset",
  "title": "某篇文章",
  "url": "https://example.com/article",
  "description": "文章摘要",
  "target_route_key": "library_registry"
}'
```

### 3. 申请编号

```bash
python3 scripts/global_id_allocator.py DOC
```

## 变更记录

- **v6.0**：新增 `@Aime /归档 [链接]` 全局 Hook 能力；新增 `scripts/archive_command_hook.py` 负责 URL 提取、URL 类型识别与归档计划生成；补充飞书文档/Wiki/表格与外部网页的内容抽取分发规则；更新 SKILL.md 触发说明与执行流程。
- **v5.0**：架构升级为联邦制 + 薄 I/O 驱动器；新增 `scripts/archiver_driver.py` 与 `assets/federated_route_manifest.json`；新增 DLQ 暂存区设计与本地 JSONL 兜底；保留风神链接 / 图书馆 / 技能清单三条兼容预设；发号器改为真实飞书表格读写 + RAW 写后回读。
- **v4.2**：新增 `BUG-YYMM-NNNN` 编号序列；发号器抽象出 `CATEGORY_FORMAT_REGISTRY` 支持多前缀；统一所有类目到月维度 YYMM 标准，未注册前缀立即熔断。
- **v4.1**：新增报告类资产的文档生动化标准。
- **v4.0**：更新专属技能清单 Schema，合并名称与链接，新增更新时间。
- **v3.0**：更新专属技能清单归档逻辑，实施 5 列强校验 Schema Guard。
- **v2.0**：升级为事件驱动模式，新增强制行列坐标约束。

## 引用资源

- **Hook 解析器**：`scripts/archive_command_hook.py`
- **联邦路由配置**：`assets/federated_route_manifest.json`
- **归档驱动器**：`scripts/archiver_driver.py`
- **发号器**：`scripts/global_id_allocator.py`
- **本地 DLQ**：`assets/dlq/omni_asset_archiver_dlq.jsonl`
