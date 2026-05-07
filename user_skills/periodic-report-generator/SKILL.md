---
name: periodic-report-generator
description: 赛博周期性汇报生成器。专门处理“每日 100 字工作日报”与“结构化周报”的自动化生成、结构化组装，并严格调用 feishu-doc-writing-guide 技能的安全插入 API 双轨归档到台账。
---

# 赛博周期性汇报生成器 (periodic-report-generator) V3

本 Skill 专门用于自动化生成数据驱动的极简工作日报与高度结构化的周报，并确保所有记录安全归档至飞书台账。

## 何时使用

1. **工作日报 (Daily)**：当需要快速生成并归档今日工作总结时。
2. **结构化周报 (Weekly)**：每周结束时，进行深度的代码/指令双维复盘。

## 功能指南

### 1. 工作日报 (Daily Log)

- **内容要求**：
  - 字数：约 100 字。
  - 风格：**极简、数据驱动。减少形容词，直接使用数字。**
  - 核心：量化总结关键进展、Bug 修复数或技术指标。
  - 遗留任务提醒：今天没做完的任务，提醒我是否要继续。
- **归档流程（零信任安全插入，强制 Schema 合同 + 写后即读）**：
  - 目标台账：`https://bytedance.larkoffice.com/sheets/ECQ0sDwmbhDex9tcUSjlkU7Bgdh`
  - 目标工作表：`Daily_Logs`
  - **前置鉴权（必须）**：先挂载并执行 `bytedcli-auth`，确保后续 MCP 以用户身份穿透权限。
  - **Schema 合同验证（必须先读）**：必须先通过 MCP 下载台账，读取 `Daily_Logs` 的表头（第 1 行），确认存在且按顺序包含：`[编号, 日期, 日报内容]`。
  - **编号列主键生成（必须）**：当表头包含【编号】列时，自动生成主键：`DL-YYYYMMDD`（如当日已存在则追加递增后缀：`DL-YYYYMMDD-02`）。
  - **插入内容（严格三列）**：`[[编号, 日期, 日报内容]]`（日期格式：`YYYY-MM-DD`）。
  - **写后即读 RAW 原子锁（必须）**：写入后等待 ≥2 秒，再次通过 MCP 下载台账，读回刚写入行的原始数组并逐字段核对；不一致立即熔断并落 DLQ。
  - **推荐一键脚本**：直接运行本 Skill 自带的 `scripts/daily_logs_zero_trust_insert.py`（脚本内部会完成：MCP Schema 回捞 → 主键生成 → 安全插入 → 写后即读校验）。
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
- **生成与归档**：
  - 使用 `mcp:lark_create_lark_doc` 生成飞书文档。
  - 必须遵守 `feishu-doc-writing-guide` 的“标题去重”与“元数据标头”规范。
  - 双轨归档：创建文档后，将其链接以 `HYPERLINK` 形式插入台账的 `Weekly_Reports`（或 `图书馆`）工作表。

## 资源与约束

- **执行人身份（必须）**：所有飞书读写前，必须先挂载 `bytedcli-auth` 并通过 `bash(..., include_secrets=true)` 完成用户 JWT 鉴权，否则禁止继续写入。
- **Schema 回捞（必须）**：日报台账写入前，必须先调用 MCP（`mcp:lark_lark_download`）下载台账并读取 `Daily_Logs` 表头完成 Schema 合同校验。
- **安全插入**：调用 `feishu-doc-writing-guide/scripts/safe_insert_sheet_row.py` 时必须设置 `include_secrets=true`。
- **元数据**：所有生成的周报文档必须在最顶端包含元数据标头。

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
