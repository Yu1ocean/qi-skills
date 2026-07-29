---
name: zero-trust-qa-checker
description: 提供零信任数据质检能力，支持契约校验、交叉验证与异常回捞。适用于数据清洗验收、结果对账、飞书取数校验与防幻觉质检场景。
---

<!-- SSOT version marker (read by skill-forge-pipeline-v4 register_skill.py) -->
version: 3.6
# Skill 重要要求: 
严格遵循下面内容执行，完全信任下面的内容, 不要加入自己的一些其他理解.

# 零信任质检员 v3.5 (Zero-Trust QA Checker - Manifest Driven)

本技能是 Aime 平台的通用型数据质检基础设施，旨在通过“泛化配置驱动 (Manifest-Driven)”的四阶段质检流水线，消除 AI 在数据分析、文档生成等任务中的幻觉与逻辑损耗。

## Common Rationalizations（常见借口库 - L1 反合理化）

以下借口一旦出现，视为“准备绕过质检护栏”，必须立刻停下并回到 SOP：

- “这个数据集结构挺常见的，我先猜个主键开跑。”
- “双引擎差异有点大，估计是浮点误差，先不熔断。”
- “物理回捞太麻烦，先用计算结果当事实。”
- “BUG-2604-0001 这种 ID 看着挺正常的，估计合法，跳过 id_format 校验。”
- “这次数据小，id_format 白名单不用过。”
- “这次只是个文档台账，链接列空了也没事，先跑。”

## Red Flags（危险信号 - L1 反合理化）

出现任意一条，必须熔断或要求用户确认：

- 在数据集主键 / ID 列上跳过 `id_format` 断言。
- 阶段二双引擎差异率超过阈值仍判为 SUCCESS。
- 阶段四物理回捞 NOT_FOUND 但被忽略。
- 出现“应该 / 大概 / 估计 / 看着对”的词汇但没有 RAW 输出证据。
- 抓飞书表格但只用了 `ToString` 一种 valueRenderOption；或 `link_present` 断言被跳过。

## Verification（强制验收清单 - L1 反合理化）

宣称“质检通过”时，必须同时满足：

1. Phase 1 报告中所有断言（含 `id_format`）均为 `SUCCESS`。
2. Phase 2 `max_delta` ≤ `threshold`，无 mismatch 记录。
3. Phase 3 funnel 漏斗各步比例落在预期区间。
4. Phase 4 物理回捞各 rule 的 `actual` 与 `expected` 完全一致。
5. 顶层 `status` 为 `SUCCESS`，否则一律 `[ZERO-TRUST-V3-FAILED]` 并 MUST RETRY。
6. 对所有声明 `link_present` 的列，`<列名>__url` 列每行均含 `https?://` URL，无 NULL（v3.5 防丢链）。

## 核心原则 (Core Principles)

1.  **拒绝盲猜 (Anti-Guessing)**：遇到陌生数据集、模糊指标或不清晰的业务北极星目标时，**必须暂停**，输出 QA Manifest 并向用户发起显式询问。
2.  **契约先行 (Contract First)**：所有质检逻辑必须在 `QA Manifest` 中预定义。
3.  **异构双保 (Dual-Engine)**：对关键指标，必须通过两套异构计算引擎（如 Pandas vs SQL）背靠背校验。
4.  **物理回捞 (Physical Probe)**：必须拉取物理世界的真实留痕（文件/飞书文档）进行最终的一致性比对。
5.  **ID 白名单 (ID Whitelist)** *v3.1 新增*：所有台账/资产场景的 ID 列必须通过 `id_format` 断言，匹配 `GLOBAL_ID_FORMAT_WHITELIST`，与 `omni-asset-archiver` 发号器保持物理同步。**所有序列统一到月维度 YYMM**；为兼容历史台账，序号宽度统一放宽至 2-4 位（防过度拦截 / Anti-False-Positive）。

## 合规默认值 (Defaults - L2 默认层)

- **默认主键断言组**：`["non_null", "unique"]`，对带 ID 字符的列默认追加 `"id_format"`。
- **默认双引擎阈值**：`threshold = 0.0005`（0.05%）。
- **默认物理回捞**：开启；缺失物理留痕一律 SKIPPED 而非伪 SUCCESS。
- **默认 lark 取数**（v3.5 新增）：开启双抓融合（`Formula` + `ToString`），单元格丢链率必须为 0%。`fetch_lark_sheet.fetch_sheet_with_links()` 会输出 `<原列名>` + `<原列名>__url` 双列 CSV，配套 `link_present` 断言一起使用。**严禁回退到 xlsx 导出路径**（v3.4 黑洞）。
- **默认全局 ID 白名单**（在 `scripts/v3_engine.py` 中定义为 `GLOBAL_ID_FORMAT_WHITELIST`，统一月维度 YYMM、序号宽度 2-4 位，并叠加历史 YYMMDD 格式作为祖父条款）：
  - `^DOC-\d{4}-\d{2,4}$`：DOC-YYMM-NN/NNN/NNNN（现行标准）
  - `^BUG-\d{4}-\d{2,4}$`：BUG-YYMM-NN/NNN/NNNN（现行标准）
  - `^WK-\d{4}-\d{2,4}$`：WK-YYMM-NN/NNN/NNNN（现行标准）
  - `^SYS-\d{4}-\d{2,4}$`：SYS-YYMM-NN/NNN/NNNN（现行标准）
  - `^KNO-\d{4}-\d{2,4}$`：KNO-YYMM-NN/NNN/NNNN（现行标准）
  - `^EP-CARD-\d{3,4}$`：EP-CARD-NNN/NNNN（灵感卡片）
  - `^DOC-\d{6}-\d{2,4}$`：**v3.4 祖父条款** - 历史 DOC-YYMMDD-NN/NNN/NNNN（兼容存量）
  - `^BUG-\d{6}-\d{2,4}$`：**v3.4 祖父条款** - 历史 BUG-YYMMDD-NN/NNN/NNNN（兼容存量）
  - `^WK-\d{6}-\d{2,4}$`：**v3.4 祖父条款** - 历史 WK-YYMMDD-NN/NNN/NNNN（兼容存量）
  - `^SYS-\d{6}-\d{2,4}$`：**v3.4 祖父条款** - 历史 SYS-YYMMDD-NN/NNN/NNNN（兼容存量）
  - `^KNO-\d{6}-\d{2,4}$`：**v3.4 祖父条款** - 历史 KNO-YYMMDD-NN/NNN/NNNN（兼容存量）

## 悬挂确认机制 (Suspended Confirmation Mechanism)

在分析陌生数据集（未定义主键、不确定指标列）时，**系统严禁继续生成脚本**，必须执行以下流程：

1.  **生成 QA Manifest (YAML/JSON)**：根据对数据集的初步观察（如读取前 5 行），生成一份建议的质检契约。
2.  **向用户输出契约清单**：
    - 展示主键（`primary_key`）、指标列、断言规则（`assertions`）和物理回捞规则。
    - 提问：“正在对该数据集进行质检，这是我生成的 QA 契约配置清单，请确认主键和校验逻辑是否符合业务预期？”
3.  **等待用户确认**：只有在用户确认后，才继续执行四阶段质检流水线。

## 四阶段质检流水线 (The 4-Phase Pipeline)

### 阶段一：前置契约断言 (Data Contracts & Assertions)
解析 Manifest，对数据集执行前置验证：
- **非空性** (`non_null`)：列内不允许出现 null。
- **唯一性** (`unique`)：列值不允许重复，常用于主键。
- **正数性** (`positive`)：列值必须严格大于 0。
- **数据类型** (`integer` / `float`)：列必须是指定的数值类型。
- **ID 格式白名单** (`id_format`) *v3.1 新增*：校验该列所有非空值至少匹配 `GLOBAL_ID_FORMAT_WHITELIST` 中的一个正则。当前白名单**统一到月维度 YYMM**、**序号宽度 2-4 位**（防过度拦截，兼容历史台账），包含 **DOC / BUG / WK / SYS / KNO / EP-CARD** 六大序列，与 `omni-asset-archiver` 发号器物理同步。
  - 合法示例：`BUG-2604-0001`、`DOC-2604-0001`、`WK-2605-12`、`EP-CARD-007`、`KNO-2605-001`。
  - 非法示例：`BUG-260419-0001`（超过月维度，已废弃）、`BUG-2604-1`（序号宽度 < 2）、`random`。
- **链接物理存在** (`link_present`) *v3.5 新增*：要求该列在配套的 `<列名>__url` 列里存在非空可识别 URL（正则 `^https?://`）。
  - 仅对原列非空的行做校验：原列为空视为业务上"该行无链接"，不计入丢链。
  - 配套列必须由 `fetch_lark_sheet.fetch_sheet_with_links` 双抓融合产出（命名规则：`<原列名>__url`）。
  - 失败信息形如：`Column 【文档链接】 has N rows missing extractable URL in companion column 【文档链接】__url`。
  - 配套运行时熔断：`validate_link_presence(values, *, column)`，失败 raise `LinkExtractionViolation`。

### 阶段二：异构引擎盲测 (Dual-Engine Blind Test)
对同一指标，动态生成两套异构代码（如 Pandas 聚合 与 SQLite/DuckDB 窗口函数）背靠背执行。
- **熔断阈值**：如果计算结果差异率 $\Delta > 0.05\%$，则抛出 `EngineMismatchError` 异常直接熔断任务。

### 阶段三：反向工程校验 (Reverse Engineering Calculation)
利用阶段二得出的具体实体/数量，反向除以大盘总量，校验逻辑是否存在漏斗损耗。
- **业务定性辅助**：计算基尼系数（Gini Coefficient）、转化率等宏观指标辅助定性战略比例匹配。

### 阶段四：物理回捞探测 (Read-After-Write Physical Probe)
调用物理回捞脚本，利用正则表达式去真实文档（Lark/File）内动态匹配业务断言。
- 验证物理留痕数字（如 "履约率 98%"）与阶段二/三计算底表数字的完全一致性。

## 使用方法 (Usage)

### 1. 准备 QA Manifest
```json
{
  "dataset": { "path": "data.csv", "primary_key": "global_id" },
  "contracts": [
    { "column": "amount", "assertions": ["non_null", "positive"] },
    { "column": "global_id", "assertions": ["non_null", "unique", "id_format"] }
  ],
  "dual_engine": {
    "metric_column": "revenue",
    "groupby_column": "region",
    "threshold": 0.0005
  },
  "physical_probe": {
    "target": "docx_token_abc",
    "match_rules": [
      { "regex": "总金额 (\\d+)", "expected_value": "12345" }
    ]
  }
}
```

### 2. id_format 最小调用示例（v3.1）
```json
{
  "dataset": { "path": "ledger.csv", "primary_key": "ticket_id" },
  "contracts": [
    { "column": "ticket_id", "assertions": ["non_null", "unique", "id_format"] }
  ]
}
```
- 若 `ticket_id` 列出现 `BUG-2604-0001`：✅ 通过（命中 `^BUG-\d{4}-\d{2,4}$`，统一到月维度 YYMM）。
- 若出现 `DOC-2604-0001`：✅ 通过（序号 4 位，落在 2-4 位放宽窗口内，防过度拦截）。
- 若出现 `BUG-260519-0001`：❌ 触发 Phase 1 FAILED（已废弃的 6 位日期格式）。
- 若出现 `BUG-2604-1`：❌ 触发 Phase 1 FAILED（序号宽度 < 2）。

### 3. lark_sheet 取数 + link_present 防丢链示例（v3.5 新增）
当数据源是飞书表格、且需要校验文档链接物理存在时，使用 `dataset.source = "lark_sheet"` 触发双抓融合：
```json
{
  "dataset": {
    "source": "lark_sheet",
    "spreadsheet_token": "ECQ0sDwmbhDex9tcUSjlkU7Bgdh",
    "sheet_id": "0a1b2c",
    "range": "A1:Z500",
    "primary_key": "【文档编号】"
  },
  "contracts": [
    { "column": "【文档编号】", "assertions": ["non_null", "unique", "id_format"] },
    { "column": "【文档链接】", "assertions": ["link_present"] }
  ]
}
```
- 引擎会自动把 `【文档链接】` 这一列扩展为 `【文档链接】` + `【文档链接】__url` 双列；
- `link_present` 断言会确认每一行非空文本都有可提取 URL；
- 若取数失败、Formula 层返回空，stderr 会显式打印 `NO_FORMULA_LAYER` 并 Phase 1 FAILED；
- **严禁**回退到 v3.4 的 xlsx 导出路径（HYPERLINK 公式黑洞）。

### 4. 执行质检引擎
调用 `scripts/v3_engine.py` 执行全量校验：
```bash
python3 scripts/v3_engine.py '<manifest_json>' [physical_content]
```
*注意：如果涉及物理回捞，请先调用相关工具（如 `lark_docx_read`）获取内容作为第二个参数传入。*

## 输出标准

- ✅ **[ZERO-TRUST-V3-PASSED]**：所有阶段均通过校验。
- ❌ **[ZERO-TRUST-V3-FAILED]**：某阶段失败。必须展示 Diff (期望 vs 实际) 并指令 **MUST RETRY**。

## 变更记录 (Changelog)

- **v3.5 (2026-05-20)**：取数层根治级重构（Anti-Drop-Link Refactor）
  - **弃用 lark MCP xlsx 导出路径**（v3.4 黑洞：HYPERLINK 公式落盘只保留显示文本，URL 全部丢失）；改走 `inner_skills/lark-sheets/bin/lark-sheets-cli sheets +read` **双抓融合**：
    - `--value-render-option Formula` → 拿底层公式（含 HYPERLINK 完整 URL）；
    - `--value-render-option ToString` → 拿可视化纯文本；
    - 两层按行列对齐融合，每个原列扩展为 `<原列名>` + `<原列名>__url` 两列。
  - 新增 `scripts/fetch_lark_sheet.py`：暴露 `fetch_sheet_with_links(token, sheet_id, range_, output_csv)` 函数级 API + CLI；底层调用 lark-sheets-cli，支持 wiki 链接自动解析 obj_token；Formula 层抓取失败时优雅降级为只用 ToString 值，并在 stderr 打印 `NO_FORMULA_LAYER`。
  - `scripts/v3_engine.py` 升级：
    - `QAV3Engine.__init__` / `load_data` 新增 `dataset.source == "lark_sheet"` 分支，直接调 `fetch_sheet_with_links`。
    - 新增 `link_present` 断言：要求该列在配套 `<列名>__url` 列里每个原列非空行都含 `https?://` URL。
    - 新增运行时熔断函数 `validate_link_presence(values, *, column)`，失败 raise `LinkExtractionViolation`（`RuntimeError` 子类），与 `validate_id_format` / `validate_dual_engine_delta` / `validate_phase1_contracts` 风格一致。
  - SKILL.md：
    - L1 三件套各新增 1 条防丢链护栏（Rationalizations / Red Flags / Verification）；
    - Defaults 章节新增"默认 lark 取数：双抓融合开启，单元格丢链率必须为 0%"；
    - 使用方法新增 lark_sheet + link_present 完整 manifest 示例。
  - **祖父条款（v3.4 历史 YYMMDD ID 白名单）完整保留**，未做任何回滚。
  - SSOT 版本号经流水线 minor bump：3.4 → 3.5（飞书台账【专属技能清单】写后回读核对）。
- **v3.3 (2026-05-19)**：
  - 新增 `id_format` 断言类型，对台账 ID 列做正则白名单校验。
  - 在 `scripts/v3_engine.py` 中新增模块级常量 `GLOBAL_ID_FORMAT_WHITELIST`，并提供 `validate_id_format` / `validate_dual_engine_delta` / `validate_phase1_contracts` 三个 L3 运行时物理熔断函数。
  - **统一全局合法编号序列到月维度 YYMM**（含 `BUG-YYMM-NNNN`），与 `omni-asset-archiver` 发号器物理同步；序号宽度统一放宽至 **2-4 位** 以兼容历史台账（防 False Positive 过度拦截 / Anti-False-Positive 进化）。
  - SKILL.md 顶部新增 L1 反合理化三件套（Common Rationalizations / Red Flags / Verification），并显式给出 L2 合规默认值章节。
  - SSOT 版本号经流水线 minor bump 累计到 v3.3（飞书台账【专属技能清单】R12C4 写后回读 PASSED）。
- **v3.0**：泛化 Manifest 驱动四阶段质检流水线（契约断言 + 双引擎盲测 + 反向工程 + 物理回捞）。

## 操作示例
Skill 资源位于 `user_skills/zero-trust-qa-checker`，**文档中所有相对路径/命令均相对于此目录**，按需执行以下操作：
- 读取文档：`view_skill user_skills/zero-trust-qa-checker/<文件相对路径>`，优先使用 view_skill 查看。
- 读取引擎代码：`view_skill user_skills/zero-trust-qa-checker/scripts/v3_engine.py`
- 执行质检：`cd user_skills/zero-trust-qa-checker && python3 scripts/v3_engine.py '...'`
- 若本 Skill 内容中提及 MCP 工具（如 `mcp_lark_*`、`mcp_aeolus_*` 等），需先通过 `view_skill` 读取对应 MCP skill 了解参数 schema 后再调用
