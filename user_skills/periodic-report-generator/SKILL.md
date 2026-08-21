---
name: periodic-report-generator
description: 生成周期性日报或周报并整理成结构化汇报文档。适用于每日工作日报、周报复盘、固定节奏汇报与自动归档场景。
version: 6.3
---

# 赛博周期性汇报生成器 (periodic-report-generator) V6.3

## Common Rationalizations（常见借口）

以下想法出现时，必须立刻回到本 SOP：

- “这次只是周报，先不写绩效素材池，后面绩效季再补。”
- “素材摘要可以凭印象写，来源报告链接以后再补。”
- “表格只有四列，直接裸调 lark 写进去也没事。”
- “RAW 回捞慢，看到写入成功就算完成。”
- “GMV、实验、决策类型差不多，可以混成一个总结字段。”
- “append 到表尾也能看到，先不改插入位置。”
- “只有断言 B（降序）失败，问题不大，先算完成。”
- “插行接口麻烦，先追加到最后一行，回头人工排序。”
- “三断言太慢，写完看到 ok=true 就收工。”

## Red Flags（危险信号）

出现任意一条，必须熔断或修正后再继续：

- `--write-perf-pool` 已开启，但素材项缺少来源报告链接。
- 写入 `Perf_Material_Pool` 前没有读取并核对 `[日期, 事项类型, 内容摘要, 来源报告链接]` 表头。
- 事项类型不属于 `GMV` / `实验` / `决策`。
- 使用裸 lark 写入绩效素材池，而不是调用 `feishu-doc-writing-guide` 包装器。
- 宣称写入完成，但没有输出 RAW 回捞行号。
- `Daily_Logs` 写入仍在使用 append-to-tail（`+append` / `safe_insert_sheet_row.py` 追加表尾）路径。
- 未在第 2 行执行 `+dim-insert` 物理插行，直接写 A2:C2（会覆盖上一条日报）。
- 未执行写入后三断言（A 置顶 / B 降序 / C 非空）就宣称完成。
- 任一断言失败却继续流程、或把断言降级为 WARNING 静默通过。
- 在真实 `Daily_Logs` 表上做写入实验验证新逻辑（污染线上数据）。

## Verification（强制验收清单）

当宣称周报与绩效素材池同步完成时，必须同时满足：

1. 周报文档已按元数据标头、文档生动化标准和双轨归档要求生成或归档。
2. 仅当 `--write-perf-pool` 显式开启时写入绩效素材池；未开启时保持只生成周报。
3. 绩效素材池写入前已完成 Schema 合同校验，四列字段顺序完全一致。
4. 每条素材均包含日期、事项类型、内容摘要和来源报告链接，且事项类型在允许枚举内。
5. 写入动作通过 `feishu-doc-writing-guide/scripts/safe_insert_sheet_row.py` 完成。
6. 写入后等待 ≥2 秒并 RAW 回捞，输出新写入行号；不一致立即熔断。
7. **降序插入法验收**：`Daily_Logs` 写入必须先在第 2 行 `+dim-insert` 插空行，再写 A2:C2；日志中必须出现 `[DescendingInsert]` 证据，且不得出现任何 append-to-tail 调用。
8. **三断言验收**：写后回读必须输出 `assert_top_row_is_today` / `assert_date_desc` / `assert_no_empty_cells` 三条 PASS 证据（`assert_daily_logs_invariants()` 统一入口）；任一 FAIL 必须 `raise` 熔断并落 DLQ。

本 Skill 专门用于自动化生成数据驱动的极简工作日报与高度结构化的周报，并确保所有记录安全归档至飞书台账。

## 何时使用

1. **工作日报 (Daily)**：当需要快速生成并归档今日工作总结时。
2. **结构化周报 (Weekly)**：每周结束时，进行深度的代码/指令双维复盘。

## 功能指南

### 1. 工作日报 (Daily Log)

- **内容要求**：
  - 字数：约 100 字。
  - 风格：**极简、数据驱动。减少形容词，直接使用数字。**
  - **任务状态汇总表**（强制）：必须包含一个表格，展示任务库（token: `Yl6lwic1EiF2d3kHnzccZinsnLV`）中任务的统计数据：开启 x 个、完成 y 个、暂停 z 个。
  - **前置数据拉取（强制）**：晚 6 点日报生成前，必须先从新任务库 Wiki `https://bytedance.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV?sheet=KmlJhs` 下载最新台账快照，读取 `任务库` 工作表并基于 `完成情况` 列统计开启/完成/暂停数，再回填日报内容中的对应字段或占位符。
  - **核心进展**：量化总结关键进展、Bug 修复数或技术指标。
  - **对工作的建议**（强制）：专门提供一部分关于工作改进或优化的建议模块。
  - **遗留任务提醒**：今天没做完的任务，提醒我是否要继续。
  - **上下文归属**：任务统一归属于“晚6点归档质检与日报生成”。
- **归档流程（零信任安全插入，强制 Schema 合同 + 写后即读）**：
  - 目标台账：`https://bytedance.larkoffice.com/sheets/ECQ0sDwmbhDex9tcUSjlkU7Bgdh`
  - 目标工作表：`Daily_Logs`
  - **前置鉴权（必须）**：先挂载并执行 `bytedcli-auth`，确保后续 MCP 以用户身份穿透权限。
  - **Schema 合同验证（必须先读）**：必须先通过 MCP 下载台账，读取 `Daily_Logs` 的表头（第 1 行），确认存在且按顺序包含：`[编号, 日期, 日报内容]`。
  - **编号列主键生成（必须）**：当表头包含【编号】列时，自动生成主键：`DL-YYYYMMDD`（如当日已存在则追加递增后缀：`DL-YYYYMMDD-02`）。
  - **插入内容（严格三列）**：`[[编号, 日期, 日报内容]]`（日期格式：`YYYY-MM-DD`）。
  - **【规则 1】降序插入法（Descending Insert，治本）**：写入 `Daily_Logs` 时**必须在表头（第 1 行）下方插入新行，严禁追加到表尾**。实现链路固定为两步：
    1. 通过 lark MCP / `lark-cli sheets +dim-insert --position 2 --count 1 --inherit-style after` 在第 2 行物理插入空行；
    2. 通过 `lark-cli sheets +cells-set --range "Daily_Logs!A2:C2"` 把 `[编号, 日期, 日报内容]` 写入置顶行。
    由此最新日报永远置顶、天然维持日期降序。**append-to-tail 路径（`+append` / `safe_insert_sheet_row.py` 表尾追加）已废弃并禁止使用**——它是本次 P1 事故（最新日报被埋到第 108 行）的直接根因。
  - **【规则 2】写入后三断言熔断（治表）**：写入完成后 `sleep ≥2s` 做 RAW 回读，并强制执行三条断言，任意一条失败即 `raise` 熔断报错并落 DLQ，绝不允许静默通过：
    - **断言 A** `assert_top_row_is_today()`：`B2 == 当日日期`（最新行置顶）。
    - **断言 B** `assert_date_desc()`：`B 列（排除表头）严格降序`（无乱序，且不允许出现无法解析的日期单元格）。
    - **断言 C** `assert_no_empty_cells()`：`A2 / B2 / C2 均非空`（无错列 / 半行写入）。
    - 统一入口：`assert_daily_logs_invariants(rows, expected_date)`，返回三条 PASS 证据并原样打印。
  - **写后即读 RAW 原子锁（必须）**：写入后等待 ≥2 秒，通过 `lark-cli sheets +cells-get --include value` 回读 `A1:C{N}`，先逐字段核对置顶行与期望值，再执行上述三断言；任一不一致立即熔断并落 DLQ。
  - **验证禁令**：严禁在真实 `Daily_Logs` 表上做写入实验。验证新逻辑只允许使用 `--dry-run` 或临时影子 Sheet，且用完必须清理。
  - **推荐一键脚本**：直接运行本 Skill 自带的 `scripts/daily_logs_zero_trust_insert.py`（脚本内部会完成：任务库统计预拉取 → 占位符/字段回填 → MCP Schema 回捞 → 主键生成 → 安全插入 → 写后即读校验）。
  - **执行示例（必须 include_secrets=true）**：

    ```bash
    # 1) 执行人身份穿透：先用当前用户 JWT 完成 bytedcli 鉴权
    cd inner_skills/bytedcli-auth && bash scripts/bytedcli_auth.sh

    # 2) 零信任插入（会自动：读 Schema → 生成编号 → 写入 → 写后即读）
    cd user_skills/periodic-report-generator
    python3 scripts/daily_logs_zero_trust_insert.py --date "YYYY-MM-DD" --content "【YYYY-MM-DD】今日……（约 100 字）"

    # 可选：干跑（只读 Schema + 生成编号，不写入）
    python3 scripts/daily_logs_zero_trust_insert.py --dry-run --date "YYYY-MM-DD" --content "noop"
    ```

### 2. 结构化周报 (Weekly Report)

- **必须包含的模块**：
  - **1. 代码层复盘**：本周所有 Repository 的代码变动、逻辑重构及架构演进。
  - **2. 指令层复盘**：Prompt 优化、Skill 迭代及 Agent 交互逻辑的变迁。
  - **3. 【图书馆】资产**：列出本周新增的飞书文档、台账或其它数字化资产链接。
  - **4. 风险应对矩阵**：下周可执行的实验及潜在风险评估。
  - **5. 赛博碎碎念**：一段带有强赛博朋克色彩的第一人称视角感慨。
- **【文档生动化标准】（强制）**：当输出属于重要的“复盘报告”“故障修复报告”或“架构演进报告”时，必须在正式写入飞书文档前联动 `cyber-inspiration-generator`，生成一段阿加莎/赛博朋克风格的悬疑剧情文案与对应视觉卡片。
  - **前置嵌入位置**：将“灵感故事”与卡片链接前置插入飞书文档头部概览区，位置必须早于“元数据标头”后的正文主体模块。
  - **最小内容契约**：概览区至少包含 4 项：`灵感标题`、`小说段落（150-200 字）`、`冷静说明（2-3 行）`、`视觉卡片链接`。
  - **触发原则**：只要报告主题涉及复盘、修复或架构演进三类之一，即默认触发；不得因“文档偏技术”而跳过。
  - **失败策略**：若 `cyber-inspiration-generator` 未成功返回故事或卡片链接，则禁止宣称报告已完成，必须向用户明确报告卡点。
- **生成与归档**：
  - 使用 `mcp:lark_create_lark_doc` 生成飞书文档。
  - 必须遵守 `feishu-doc-writing-guide` 的“标题去重”与“元数据标头”规范。
  - 在正文模块写入前，先完成上述“文档生动化标准”的头部嵌入。
  - 双轨归档：创建文档后，将其链接以 `HYPERLINK` 形式插入台账的 `Weekly_Reports`（或 `图书馆`）工作表。
- **绩效素材池同步（可选）**：
  - 触发 flag：周报生成链路收到 `--write-perf-pool` 时启用；未传该 flag 时，不写入绩效素材池，保持原周报生成行为不变。
  - 目标素材区：`https://bytedance.larkoffice.com/sheets/ECQ0sDwmbhDex9tcUSjlkU7Bgdh?sheet=3Mn6co`，工作表 `Perf_Material_Pool`。
  - 固定 Schema：`[日期, 事项类型, 内容摘要, 来源报告链接]`；事项类型仅允许 `GMV` / `实验` / `决策`。
  - 素材抽取口径：只写入每周高亮结论，包括 GMV 增量、实验结论、关键决策；流水账动作、无来源链接的口头判断、未验证数字不得写入。
  - 写入工具：必须通过 `feishu-doc-writing-guide/scripts/safe_insert_sheet_row.py` 包装器写入，禁止裸调 lark 写入。
  - RAW 原子锁：写入后等待 ≥2 秒，通过 `lark-sheets` 直读 `Perf_Material_Pool`，按 `[日期, 事项类型, 内容摘要, 来源报告链接]` 四元组定位新行并输出行号；未命中或字段不一致立即熔断。
  - 推荐脚本：`scripts/weekly_perf_pool_insert.py`。

    ```bash
    cd user_skills/periodic-report-generator
    python3 scripts/weekly_perf_pool_insert.py \
      --write-perf-pool \
      --date "YYYY-MM-DD" \
      --source-report-link "https://bytedance.larkoffice.com/docx/xxx" \
      --items-json '[{"type":"GMV","summary":"本周 GMV 增量结论……","source_report_link":"https://bytedance.larkoffice.com/docx/xxx"}]'
    ```

## 资源与约束

- **执行人身份（必须）**：所有飞书读写前，必须先挂载 `bytedcli-auth` 并通过 `bash(..., include_secrets=true)` 完成用户 JWT 鉴权，否则禁止继续写入。
- **Schema 回捞（必须）**：日报台账写入前，必须先调用 MCP（`mcp:lark_lark_download`）下载台账并读取 `Daily_Logs` 表头完成 Schema 合同校验。
- **安全插入**：调用 `feishu-doc-writing-guide/scripts/safe_insert_sheet_row.py` 时必须设置 `include_secrets=true`。
- **元数据**：所有生成的周报文档必须在最顶端包含元数据标头。
- **生动化依赖**：涉及复盘/修复/架构演进类周报时，必须调用 `cyber-inspiration-generator` 先产出头部故事与视觉卡片，再进入飞书写入。
- **绩效素材池写入（可选）**：仅当 `--write-perf-pool` 显式开启时写入 `Perf_Material_Pool`；每条素材必须带来源报告链接，写入前校验 Schema，写入后 RAW 回捞行号。

## 示例

### 日报示例
> 【2026-04-12】今日完成 3 个核心组件重构，修复 5 个 P1 级 Bug。文档幻觉率从 12% 降至 2.5%。台账写入成功率 100%，累计归档 1 份周报与 12 份日报。

### 周报结构
- 📄 **文档编号**：WK-2604-01 📅 **归档日期**：2026-04-07
---
## 一、代码层复盘
...
## 二、指令层复盘
...

## 更新日志 (Changelog)

### V6.3 (2026-08-21)
- **根因（P1）**：`Daily_Logs` 归档链路长期走 append-to-tail（`safe_insert_sheet_row.py` → `lark-sheets +append`），最新日报被追加到表尾（实测埋到第 108 行）；历史表同时积累列错位、格式不统一、重复编号等脏数据，且无任何写后结构断言，脏写可长期不可见。
- **修复 1（治本 · 降序插入法）**：写入路径改为「第 2 行物理插行 + 写 A2:C2」。新增 `insert_top_blank_row()`（`lark-cli sheets +dim-insert --position 2`）、`write_top_row()`（`+cells-set` 结构化 value 通道）与统一入口 `descending_insert_daily_log()`；彻底移除 `+append` 依赖，最新日报永远置顶。
- **修复 2（治表 · 三断言熔断）**：新增独立可复用断言 `assert_top_row_is_today()` / `assert_date_desc()` / `assert_no_empty_cells()` 及统一入口 `assert_daily_logs_invariants()`，写后 `sleep 2s` RAW 回读（`+cells-get --include value`）后强制执行，任一失败即 `raise` 熔断并落 DLQ。
- **配套**：新增 `read_daily_logs_rows()` RAW 回读器与 `_run_lark_cli()`（非 0 退出 / `ok=false` 即 raise，禁止静默）；`--dry-run` 增强为「模式声明 + 现存表体降序预检」；保留 Schema 合同校验与 `DL-YYYYMMDD` 主键生成能力；`--row-index` 降级为兼容入参。
- **护栏加固**：Common Rationalizations 新增「append 到表尾也能看到」「只有断言 B 失败问题不大」等 4 条；Red Flags 新增「仍在使用 append-to-tail」「未执行三断言就宣称完成」等 6 条；Verification 新增第 7/8 条（降序插入法验收、三断言验收）。

### V6.2 (2026-07-25)
- **新增绩效素材池同步**：周报生成链路支持可选 `--write-perf-pool` flag，将 GMV 增量、实验结论、关键决策写入 `Perf_Material_Pool`。
- **新增固定素材 Schema**：素材池字段为 `[日期, 事项类型, 内容摘要, 来源报告链接]`，事项类型限定为 `GMV` / `实验` / `决策`。
- **新增 RAW 回捞脚本**：提供 `scripts/weekly_perf_pool_insert.py`，通过 `feishu-doc-writing-guide` 包装器写入，并回读行号供 `performance-review-writer` 后续召回。

### V6 (2026-05-22)
- **日报格式升级**：
  - 新增“任务状态汇总表”强制要求，展示开启/完成/暂停任务数。
  - 新增“对工作的建议”强制模块。
  - 明确日报数据来源为任务库 `Yl6lwic1EiF2d3kHnzccZinsnLV`。
  - 任务上下文归属于“晚6点归档质检与日报生成”。
- **能力配套**：联动 `task-flow-engine` 升级后的状态统计输出能力。

### V5 (2026-05-07)
- **新增长期标准**：重要的复盘报告、故障修复报告、架构演进报告，生成飞书文档前必须前置嵌入由 `cyber-inspiration-generator` 产出的灵感故事与视觉卡片。
- **新增执行契约**：明确头部概览区的最小内容契约、失败熔断规则，以及“先生动化、后写正文、再归档”的执行顺序。

### V4 (2026-05-07)
- **修复脏写漏洞**：日报台账写入从 `[[日期, 日报内容]]` 升级为 `[[编号, 日期, 日报内容]]`。
- **Schema 强校验**：写入前强制通过 MCP 回捞 `Daily_Logs` 表头，确保列合同一致。
- **主键自动生成**：当存在【编号】列时，自动生成 `DL-YYYYMMDD`（冲突时追加递增后缀）。
- **RAW 原子锁**：写入后等待 ≥2 秒并读回核对，不一致立即熔断并落 DLQ。
- **新增脚本**：提供 `scripts/daily_logs_zero_trust_insert.py` 一键执行上述全流程。

### V3 (2026-04-26)
- **新增模块**：日报内容要求中增加“遗留任务提醒”模块，提示今日没做完的任务是否要继续。

### V2 (2026-04-12)
- **风格重塑**：将日报风格从“极客幽默”调整为“极简、数据驱动”。
- **量化要求**：强制要求减少形容词，优先使用数字和指标进行描述。
