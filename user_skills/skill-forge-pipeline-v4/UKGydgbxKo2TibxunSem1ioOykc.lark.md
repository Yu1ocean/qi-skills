<title>multi-source-sync (v1.1) 技能说明</title>

# Multi Source Sync (multi-source-sync)

<!-- SSOT version marker (read by skill-forge-pipeline-v4 register_skill.py) -->

version: 1.1

## 📌 技能简介

`multi-source-sync` 是一个**配置驱动**的多数据源到飞书电子表格的同步基础设施。一份 JSON/YAML 配置声明多个上游（风神 Aeolus / 飞书 Bitable）+ 字段映射 + 目标 Sheet，脚本负责拉取、字段归一化、行拼接、幂等物理写入、更新日期锚点、RAW 回捞与轻量交叉质检。适用于每周定时同步、多源联合刷新、跨系统台账更新等场景。

## 🔑 触发词

- 核心关键词：

  - 多数据源同步
  - 风神看板到飞书表格
  - Bitable 到 Sheet 合并写入
  - 每周五定时数据同步
  - 配置驱动数据管道
- 典型指令示例：

  > 用 multi-source-sync 把这个风神链接的数据同步到我那张飞书表格里。  
  > 帮我把风神 A 看板 + Bitable B 表联合刷新到 Sheet C。  
  > 跑一下每周五数据更新配置。

## ⚙️ 核心架构 / SOP / 约束条件

### 目录结构

```
user_skills/multi-source-sync/
├── SKILL.md
├── ASSET_MANIFEST.md
├── CHANGELOG.md
├── scripts/
│   ├── sync_main.py
│   ├── sources/
│   │   ├── aeolus_source.py
│   │   └── bitable_source.py
│   ├── sheet_writer.py
│   └── qa_check.py
├── resources/
│   ├── example_weekly_friday.json
│   ├── qa_manifest.example.json
│   └── config.schema.json
└── output/
    └── qa_report_*.json
```

### 配置文件 Schema（关键字段）

- `sources[]`：数据源数组，每个源含 `id` / `type` (`aeolus` | `bitable`) / URL 或 token / `field_map`。
- `target`：目标 Sheet，含 `sheet_url` / `columns` / `data_range` / `updated_at_cell` / `updated_at_format`。
- `merge_strategy`：`union_append`（默认，不去重）或 `union_dedup`。
- `qa.engine`：`builtin`（默认）/ `zero_trust` / `both`。

### 运行方式

```bash
# 执行同步（bash 必须 include_secrets=true）
python3 scripts/sync_main.py --config resources/example_weekly_friday.json

# Dry-run，仅打印执行计划
python3 scripts/sync_main.py --config <path> --dry-run
```

### 数据源支持

- **type=aeolus**：底层调用 `inner_skills/aeolus-platform-analysis/scripts/url_query.py`（或 `download_dashboard_data.py` 当 `download_full=true`）。

  - 支持 dataQuery / dashboard / chart / historyId 四种 URL。
  - Region 从 URL 自动推断（CN / SG / VA / MYBD）。
  - 支持 `filters`（`aeolus_url_query --filters` 语法）。
  - 支持 `download_full=true`：走 `download_dashboard_data.py` 拿完整 CSV，规避 1000 行 hard limit。
- **type=bitable**：底层调用 `lark-cli base +record-list`。

  - 支持 `base_url` / `base_token + table_id`（自动解析）。
  - 支持 `view_id`、`filter`（DSL）。
  - 分页 100 条一批。

### 写入安全规范（强制实现）

1. **表头第一行锁死**：`A1:<最右列>1` 只读，非空且列数匹配 `target.columns` 长度；不匹配熔断。
2. **范围清空**：`+cells-clear --scope content --range data_range`，范围严格从 `data_start_row`（默认 2）开始。
3. **幂等 csv-put**：`+csv-put --start-cell A2` 一次性平铺全部数据行。
4. **更新日期锚点**：写完数据后写入 `updated_at_cell`（默认 K2）为 `YYYY-MM-DD`。
5. **RAW 回捞**：`sleep 2s` → 读回 `A1:<最右列>3` + 更新日期单元格，逐字段与预期比对。
6. **严禁 `+values-append`**：代码里通过 `assert` 硬拒绝。

### 质检方案（QA）

**结论**：**复用 `zero-trust-qa-checker` 为基础 + 自建轻量交叉质检模块**。

- `zero-trust-qa-checker` 复用：适合对目标 Sheet 数据做契约断言。当 `qa.engine=zero_trust` 或 `both` 时，脚本自动调用 `v3_engine.py`。
- 自建 `scripts/qa_check.py`：覆盖多源合并交叉校验缺口：

  - `records_vs_rows`：Σ(records_fetched) == rows_written。
  - `field_map_zero_loss`：字段映射零损失。
  - `updated_at_anchor`：更新日期单元格存在且格式正确。
- QA 报告输出：`output/qa_report_YYYYMMDD_HHMMSS.json`。

### 依赖 Skill

- **写入通道**：`lark-cli sheets +cells-clear` / `+csv-put` / `+csv-get`，遵循 `feishu-doc-writing-guide` RAW 原子锁。
- **Aeolus 取数**：`inner_skills/aeolus-platform-analysis`。
- **Bitable 取数**：`lark-cli base +record-list`（`inner_skills/managing-lark-bitable-data`）。
- **可选质检**：`user_skills/zero-trust-qa-checker/scripts/v3_engine.py`。

### CDA-Guardrails 三层护栏

- **L1 反合理化三件套**：`SKILL.md` 顶部 `Common Rationalizations` / `Red Flags` / `Verification`。
- **L2 合规默认值**：`Defaults` 章节 + `DEFAULT_*` 常量。
- **L3 运行时物理熔断**：`validate_sync_contract()` / `validate_header_lock()` / `sheet_writer.write_all` 副作用前 `assert` + `raise`。
- 高风险技能，`cda_guardrails_selfcheck.py --risk auto` 结果为 `PASSED`。

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：

  ```text
  跑一下每周五数据更新，把 VA 风神那个 dataQuery 刷到 my.larkoffice 的 Sheet。
  ```
- 🤖 标准输出：

  ```text
  已完成同步：
  - 数据源 [va_dq_2503254957](aeolus/VA): records_fetched=50
  - 目标 Sheet [my.larkoffice/KRIUslDgdh7WvYtXK8ZmhOCcyOb]:
      - data_range=A2:J10000 已清空
      - rows_written=50
      - K2 = 2026-08-07
  - RAW 回捞 A1:J3 通过
  - QA report → output/qa_report_20260807_144500.json (status=PASS)
  ```

## 更新日志 (Changelog)

- **1.1（首发）**：多数据源（Aeolus + Bitable）配置驱动同步基础设施；表头锁死 / data_range 幂等清空 / K2 日期锚点 / RAW 回捞 / 轻量交叉质检 + 可选复用 zero-trust-qa-checker；首个实例：每周五 VA dataQuery → my.larkoffice Sheet KRIUslDgdh7WvYtXK8ZmhOCcyOb（sheet=d85fa5）。

<figure view-type="Card"><source name="multi-source-sync.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NmJiOWI5YTViMGQ5YTk4ZTI3NjU3ZGZlYzA5NzYzZWJfMGIxYzk0MjAxNjMwZjM3OGUwYjMwYjRhYmRjZmNjMzBfSUQ6NzY3MTE4MTg2ODQ3MDk5NzA0N18xNzg2NDMwNzEyOjE3ODY0MzQzMTJfVjM" mime="application/zip" size="29694" token="QwRMbVaGDoO0osxRXWkmG6MCydc"/></figure>

<figure view-type="Card"><source name="multi-source-sync.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NmRlZDcyNzYwOGUyY2FjODFlNzE1MGZmMzkzNmY2YzJfNTNhYmY0MDU4ZWNhM2NmNDFjMjllNTYyOTE4M2UyMmFfSUQ6NzY3MjY2MTcxMjcwODg4MjAzNl8xNzg2NDMwNzcwOjE3ODY0MzQzNzBfVjM" mime="application/zip" size="46891" token="QV8sbnu8iol4Xyxbx0Lm16GRyNe"/></figure>