---
name: script-archive
description: 视频脚本知识归档器，负责聚合多条 video-script 拆解结果与基础元信息，生成可直接写入飞书的案例合集 Docx 内容稿、视频脚本台账 CSV，以及批次级摘要 JSON。适用于爆款案例沉淀、方法论复盘、案例合集出文档、脚本台账持续更新等场景。
---
version: 1.1
# 知识归档（script-archive）

把零散的单条视频拆解结果，压成团队能长期翻出来复用的“案例合集 + 台账 + 方法论总结”。

## Common Rationalizations（常见借口库）

以下借口一旦出现，视为准备绕过飞书归档护栏：

- “先把文档正文写出来，表格台账下次再补。”
- “台账主键先不做，反正后面可以人工去重。”
- “写飞书太麻烦，先给本地 markdown / csv 路径就算归档完成。”
- “拆解结果格式不统一，先复制粘贴成大段文字。”
- “方法论总结先凭印象写，不必回到原始拆解证据。”

## Red Flags（危险信号）

出现任意一条，必须熔断或降级说明：

- 没有读取 `video-script` 结果原始 JSON，就直接写案例合集。
- 只生成 Docx，不生成长期可查询的台账数据文件。
- 写飞书时没有遵守 `feishu-doc-writing-guide` 的 MCP-only / RAW 回读约束。
- 台账里没有主键或 `source_json`，导致后续无法幂等更新。
- 聚合结论与单条拆解证据对不上。

## Verification（强制验收清单）

当你宣称“脚本归档完成”时，必须同时满足：

1. **输入成立**：至少读取 1 条合法的 `video-script` 结果 JSON。
2. **双产物成立**：同时产出 Docx 内容稿和台账 CSV。
3. **方法论可追溯**：总结能回到单条案例或结构化字段。
4. **主键幂等**：台账中每行都有稳定主键。
5. **飞书链路合规**：若执行写入，必须走 MCP + `feishu-doc-writing-guide`。

## 📌 技能简介

`script-archive` 的职责不是“再写一遍总结”，而是把多条拆解结果压缩成可沉淀、可查询、可继续扩展的飞书资产：
- 本地先生成 `.lark.md` 内容稿、台账 CSV 和汇总 JSON。
- 再通过 `lark` MCP + `feishu-doc-writing-guide` 安全落地到 Docx / Sheet / Base。
- 持续维持案例合集与方法论台账的统一 schema。

## 🔑 触发词

- 核心关键词：
  - 爆款案例合集
  - 视频脚本台账
  - 方法论沉淀
  - 多条 video-script 汇总
  - 脚本归档
- 典型指令示例：
  > 把这批 video-script 结果整理成一份飞书案例合集，再配一个视频脚本台账。
  > 帮我把爆款视频拆解结果沉淀成可复用的方法论文档和表格。

## 何时使用

当任务满足以下任一条件时触发：

- 有多条 `video-script` 结果，需要做聚合总结。
- 需要生成“爆款案例合集 / 方法论总结 / 周期复盘”类飞书文档。
- 需要创建或更新“视频脚本台账” Sheet / Base。
- 需要把案例洞察沉淀为长期可查询资产。

## Defaults（合规默认值）

- `DEFAULT_REPORT_FILE = "script_archive_report.lark.md"`
- `DEFAULT_LEDGER_FILE = "video_script_ledger.csv"`
- `DEFAULT_SUMMARY_FILE = "script_archive_summary.json"`
- `DEFAULT_BATCH_ID_PREFIX = "SAR"`
- `DEFAULT_NULL = "NULL"`

## ⚙️ 核心架构 / SOP / 约束条件

### Step 1：读取多条 video-script 结果

输入支持：
- 单个 JSON 文件
- 一个目录下的多个 JSON 文件
- 一个 manifest 文件，内含 `files` 路径列表

每条结果至少应有：
- 视频标识：`video_url` / `source_url`
- 标题或账号基础信息
- 六段式拆解中的大部分字段（视频画像 / 结构拆解 / 高效原因 / 风险与短板 / 可复用方法论 / AB实验建议）

### Step 2：归一化结构

聚合前先统一字段：
- `platform`
- `market`
- `category`
- `account_name`
- `video_title`
- `video_type_tags`
- `hook_summary`
- `methodology_summary`
- `risk_summary`
- `experiment_summary`
- `source_json`

不存在的字段统一写 `NULL`，不要隐式留空。

### Step 3：先本地成包

先在本地生成三类文件：
1. `.lark.md`：飞书案例合集正文稿。
2. `ledger.csv`：视频脚本台账原始数据。
3. `summary.json`：批次摘要、案例数量、方法论聚类等。

### Step 4：再走飞书落地

飞书写入必须按以下顺序：
1. 用 `mcp_lark_create_lark_doc` 创建 Docx，默认 `target_type=personal`。
2. 用 `mcp_lark_create_lark_table` 把 `ledger.csv` 转成飞书表格或 Base。
3. 若更新已有资产，则按 `feishu-doc-writing-guide` 做 RAW 写后即读与幂等校验。

### Step 5：归档口径

文档中至少要包含：
- 本批次方法论结论
- 案例对比
- 可执行实验建议
- 关键视频索引

台账中至少要包含：
- 主键 `record_id`
- 批次号 `batch_id`
- 视频链接 / 标题 / 账号 / 类型
- 方法论摘要 / 风险摘要 / 实验建议
- `source_json`

## Runtime Assertions（运行时断言）

```python

def validate_input_files(files):
    if not files:
        raise ValueError("未提供任何 video-script 结果文件")


def validate_case_payload(case):
    if not (case.get("video_url") or case.get("source_url")):
        raise ValueError("案例缺少视频主键")


def validate_archive_outputs(report_path, ledger_path):
    if not report_path.endswith(".lark.md"):
        raise ValueError("报告主产物必须是 .lark.md")
    if not ledger_path.endswith(".csv"):
        raise ValueError("台账主产物必须是 .csv")
```

## 推荐脚本

```bash
python3 scripts/build_archive_bundle.py \
  --input-dir output/video_script_results \
  --output-dir output/archive_bundle \
  --report-file script_archive_report.lark.md \
  --ledger-file video_script_ledger.csv \
  --summary-file script_archive_summary.json
```

## 关键约束

- 本 skill 负责“归一化 + 成包 + 落地策略”，不是替代 `video-script` 本身。
- 所有飞书写入必须透传 `feishu-doc-writing-guide` 约束。
- 若是新建飞书资产，默认落个人空间；若是更新旧资产，必须明确目标链接。
- 没有证据支撑的跨案例结论，必须降级为“观察到的共同模式”。

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：
  ```text
  我这里有 8 条 video-script 结果，帮我汇成一份爆款案例合集和视频脚本台账。
  ```
- 🤖 标准输出：
  ```text
  已先把 8 条 JSON 归一化，再生成本地 .lark.md 内容稿、ledger.csv 与 summary.json。
  如果需要飞书落地，会继续走 MCP + feishu-doc-writing-guide，把案例合集写成 Docx、台账转成 Sheet/Base，并保留 RAW 回读校验。
  ```

## Changelog

- **v0.1 (2026-06-14)**：首版发布，固化“多案例读取 → 字段归一化 → 报告/台账成包 → 飞书落地约束”的知识归档流程。

## 操作示例

- 读取文档：按需读取本 skill 的 `SKILL.md`。
- 执行脚本：先进入本 skill 根目录，再执行 `python3 scripts/build_archive_bundle.py ...`。
- 若后续要正式写飞书，必须继续调用 `lark` MCP 和 `feishu-doc-writing-guide`。
