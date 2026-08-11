# Multi Source Sync (multi-source-sync)

<!-- SSOT version marker (read by skill-forge-pipeline-v4 register_skill.py) -->
version: 2.0

## 📌 技能简介

`multi-source-sync` 是一个**配置驱动**的多数据源到飞书电子表格的同步基础设施。一份 JSON/YAML 配置声明多个上游（风神 Aeolus / 飞书 Bitable）+ 字段映射 + 目标 Sheet，脚本负责拉取、字段归一化、增量 diff、Sheet1 patch 写入、Sheet2 快照全量覆盖、更新日期锚点、RAW 回捞与轻量交叉质检。适用于每周定时同步、多源联合刷新、跨系统台账更新等场景。

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

### 双 Sheet / 增量 Diff（v2.0）

- **Sheet1 主库** `d85fa5`：只做 patch / append，不做全表覆盖。
- **Sheet2 快照** `05FUQ4`：每轮全量覆盖 A:K，作为下轮 diff 基线。
- `L=is_new`：每轮全表清零，仅本轮新增行写 `1`。
- `M=入库时间`：首次进入 v2.0 主库时写今日日期，后续永久保留。
- `removed_shops`：不删行，只把 `shop_status` 标记为 `removed`。

### 写入安全规范（强制实现）

1. **Sheet1 禁止全表覆盖**：仅允许 patch 既有行 / append 新行。
2. **Sheet2 允许全量覆盖**：`A2:K10000` clear 后重写。
3. **M 列永久保护**：已有值绝不覆盖。
4. **更新日期锚点**：`Sheet1!K2 = YYYY-MM-DD`。
5. **RAW 回捞**：回读 `Sheet1 A1:M3`、`Sheet2 A1:K3` 与 `K2`，并在验收时再核 `A1:M600` / `A1:K600`。
6. **严禁 `+values-append`**：代码级 assert 硬拒绝。

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

- **2.0（2026-08-11）**：双 Sheet 架构、增量 diff、状态追踪、`is_new` / `入库时间` 新列、Sheet1 patch-only、Sheet2 snapshot overwrite、QA diff 摘要。
- **1.4（2026-08-11）**：Aeolus 单图表 xlsx 直出修复，行数恢复到 542。
- **1.1（首发）**：多数据源（Aeolus + Bitable）配置驱动同步基础设施；表头锁死 / data_range 幂等清空 / K2 日期锚点 / RAW 回捞 / 轻量交叉质检 + 可选复用 zero-trust-qa-checker。
