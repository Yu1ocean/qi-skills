---
name: multi-source-sync
description: 多数据源（风神 Aeolus / 飞书多维表格 Bitable）配置驱动写入飞书电子表格的可复用同步基础设施。支持 JSON 配置声明多个上游、字段归一化、双 Sheet（主库 + 快照）架构、增量 diff、patch 式安全写入、状态追踪、表头锁死、RAW 回捞、源级 value_map 值转写、按 key 去重/Sum 行剔除、field_format 数值格式清洗与轻量交叉质检。适用于把风神 dataQuery/dashboard 链接与 Bitable 表联合刷新到目标 Sheet 的定时或手动任务。
author: yuqinan
version: 2.0
---

# Multi Source Sync (v2.0)

多数据源到飞书电子表格的**配置驱动同步基础设施**。一份 JSON/YAML 配置声明数据源（Aeolus/Bitable）+ 字段映射 + 目标 Sheet，脚本负责拉取、去重/Sum 行剔除、数值格式清洗、增量 diff 计算、Sheet1 patch 写入、Sheet2 快照全量覆盖、更新日期锚点、RAW 回捞、源级 `value_map` 值转写与轻量质检。

## Common Rationalizations（常见借口库 - L1）

以下借口一旦出现，视为“准备越过红线”，必须立刻停下并回到 SOP：

- “我先直接调 `+values-append` 把数据追加进去，比 `+cells-clear` + `+csv-put` 快。”
- “表头列宽和格式已经在 Sheet 里配好了，我就先不校验第一行。”
- “字段映射有一两个字段拿不到，先跳过写空，反正是台账。”
- “RAW 回捞太慢，先返回 records_fetched 就当写入成功了。”
- “K2 那格已经有值了，就不覆盖更新日期了。”
- “Aeolus 拉数超时，我先本地缓存 mock 一份跑通链路。”
- “没有 include_secrets 也应该能跑，先试一下再说。”

## Red Flags（危险信号 - L1）

出现任意一条，必须**熔断**或要求用户确认：

- 未通过 `include_secrets=true` 调用 `bash`。
- 目标 Sheet 表头第一行（`A1:<最右列>1`）出现被清空、被覆盖或被写入非表头值。
- 使用了 `sheets +values-append` 或任何无边界的追加写入。
- 数据源配置里 `field_map` 缺失或非 dict，被自动补全为空 → 直接写入。
- 数据源 records_fetched > 0 但目标 Sheet rows_written = 0，仍返回 SUCCESS。
- 上游 Aeolus 或 Bitable 拉取失败但脚本继续走后续写入。
- 更新日期锚点单元格（默认 K2）与 `results.updated_at` 不一致。
- QA report 里出现 `status=FAIL` 但顶层脚本汇报 SUCCESS。

## Verification（强制验收清单 - L1）

一次同步任务**只有同时满足**以下条件才允许标记 `status=SUCCESS`：

1. `validate_sync_contract()` 副作用前物理校验通过（源类型合法、目标 Sheet token 存在、`field_map` 完整）。
2. 每个数据源实际拉取的行数 `records_fetched` 均已记录，任一源失败时整体熔断。
3. 表头第一行 `A1:<最右列>1` **物理只读**：清空范围严格限定在 `data_range`（默认 `A2:<右下角>`），不触及第 1 行。
4. 幂等写入：先 `+cells-clear --scope content` 清空 `data_range`，再 `+csv-put` 从数据行起始格（默认 `A2`）批量写入。**严禁**使用 `+values-append`。
5. 更新日期单元格（默认 `K2`）已写入 `YYYY-MM-DD`。
6. RAW 回捞：读回 `A1:<最右列>3` + 更新日期单元格，回读值与写入值逐字段一致；不一致立即 raise。
7. QA 报告落盘到 `output/qa_report_YYYYMMDD_HHMMSS.json`，包含 `records_fetched` / `dedup_applied` / `rows_written` / `value_map_applied` / `field_format_applied` / `raw_readback` / `status` / `errors`。
8. 顶层脚本输出结构化 JSON，`status ∈ {SUCCESS, FAIL}`；FAIL 时非零退出码。

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

## 合规默认值 / Defaults（L2）

- **默认执行权限**：`bash` 调用必须设 `include_secrets=true`。
- **默认目标 Sheet 保护规则**：表头第一行只读（`A1:<最右列>1`）。
- **默认数据写入起始格**：`A2`。
- **默认数据清空范围**：`A2:<最右列>10000`（不触及第 1 行）。
- **默认更新日期单元格**：`K2`。
- **默认更新日期格式**：`YYYY-MM-DD`（不是 M/D）。
- **默认 RAW 回捞范围**：`A1:<最右列>3` + 更新日期单元格。
- **默认合并策略**：`UNION-append`（多源结果按 `field_map` 归一化后行拼接，不去重）。
- **默认 QA 报告落盘目录**：`output/qa_report_YYYYMMDD_HHMMSS.json`。
- **默认 Aeolus region 推断**：URL 域名自动推断 CN/SG/VA/MYBD。
- **首个实例默认配置文件**：`resources/example_weekly_friday.json`。

## ⚙️ 核心架构 / SOP / 约束条件

### 目录结构

```
user_skills/multi-source-sync/
├── SKILL.md
├── ASSET_MANIFEST.md            # 资产清单：数据源、产出物、实例配置
├── CHANGELOG.md
├── scripts/
│   ├── sync_main.py             # 入口：读配置 → 拉取 → 合并 → 写入 → 质检
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── aeolus_source.py     # 调用 inner_skills/aeolus-platform-analysis 的 url_query / download_dashboard_data
│   │   └── bitable_source.py    # 调用 lark-cli base +record-list
│   ├── sheet_writer.py          # 表头锁死、data_range 清空、幂等 csv-put、K2 日期、RAW 回捞
│   └── qa_check.py              # 轻量交叉质检 + 可选调用 zero-trust-qa-checker
├── resources/
│   ├── example_weekly_friday.json  # 首个实例配置（VA 风神 → my.larkoffice Sheet）
│   ├── qa_manifest.example.json    # zero-trust-qa-checker 复用示例
│   └── config.schema.json          # JSON Schema
└── output/
    └── qa_report_*.json
```

### 配置文件 Schema（关键字段）

```json
{
  "sources": [
    {
      "id": "va_dq_2507297138",
      "type": "aeolus",
      "url": "https://aeolus-va.tiktok-row.net/pages/dataQuery?...id=2507297138...",
      "region": "VA",
      "download_full": true,
      "filters": [],
      "field_map": { "shop_id": "shop_id", "shop_name": "shop_name" },
      "dedup": { "key": "shop_id", "drop_sum_rows": true },
      "value_map": { "shop_status": { "2": "active" } }
    },
    {
      "id": "bitable_source_1",
      "type": "bitable",
      "base_url": "https://<lark>/base/xxx?table=yyy",
      "filter": null,
      "field_map": { "字段A": "A列" }
    }
  ],
  "target": {
    "sheet_url": "https://<lark>/sheets/xxx",
    "sheet1_id": "d85fa5",
    "sheet2_id": "05FUQ4",
    "header_row": 1,
    "data_start_row": 2,
    "sheet2_data_range": "A2:K10000",
    "sheet2_readback_range": "A1:K3",
    "updated_at_cell": "K2",
    "updated_at_format": "YYYY-MM-DD",
    "columns": ["shop_id","shop_name","US行业","US AM","US Live AM","直播日均GMV","竞拍日均GMV","竞拍渗透","竞拍日均UV","shop_status","更新时间"],
    "extra_columns": {"L": "is_new", "M": "入库时间"},
    "mode": "diff_patch_v2"
  },
  "field_format": {
    "直播日均GMV": "int_round",
    "竞拍日均GMV": "int_round",
    "竞拍日均UV": "int_round",
    "竞拍渗透": "percent_no_decimal"
  },
  "merge_strategy": "union_append",
  "qa": {
    "engine": "builtin",
    "cross_checks": ["records_vs_rows", "field_map_zero_loss", "updated_at_anchor"]
  }
}
```

### 运行方式

```bash
python3 scripts/sync_main.py --config resources/example_weekly_friday.json
python3 scripts/sync_main.py --config <path> --dry-run   # 仅打印执行计划
```

调用时**必须**通过 `bash` 工具设置 `include_secrets=true`。

### 数据源支持

- **type=aeolus**：底层调用 `inner_skills/aeolus-platform-analysis/scripts/url_query.py`（或 `download_dashboard_data.py` 当 `download_full=true`）。
  - 支持 dataQuery / dashboard / chart / historyId 四种 URL。
  - Region 从 URL 自动推断（`data.bytedance.net` → CN，`aeolus-sg` → SG，`aeolus-va` / `tiktok-row.net` 带 `-va` / VA 关键字 → VA，`aeolus-mybd` → MYBD）。
  - 支持 `filters`（`aeolus_url_query --filters` 语法）。
  - 支持 `download_full=true`：优先走单图表 `--chart-id <rid>` 的 xlsx 直出链路，绕开 dashboard 路由 403 与 `url_query` 对 pivot cells 的误展开；xlsx 异步下载内置 3 次幂等重试（每次间隔 5s）。若下载失败或返回结果缺少 `field_map` 所需字段，则自动回退 `url_query.py`。
  - 保留 `server_total > fetched_rows` 熔断，防止上游返回截断结果时误写入目标 Sheet。
- **type=bitable**：底层调用 `lark-cli base +record-list`。
  - 支持 `base_url` / `base_token + table_id`（自动解析）。
  - 支持 `view_id`、`filter`（DSL）。
  - 分页 100 条一批。

### 字段映射与合并

- 每个数据源必须配置 `field_map`：`{"上游字段名": "目标列名"}`。
- `value_map` 为可选源级值映射：在该源归一化到 `target.columns` 后，对指定列做值级转写；若 key 写的是上游字段名，会先通过 `field_map` 解析到目标列，再应用如 `{"shop_status": {"2": "active"}}` 的映射。
- `dedup` 为可选源级去重配置：`{"key":"shop_id","drop_sum_rows":true}` 会先剔除 key 为空 / `Sum` / `总计` / `NULL` 的合计行，再按 key 保留首行，确保每个业务主键仅 1 行。
- `field_format` 为可选全局字段格式清洗配置，key 使用目标列名：`int_round` 将数值四舍五入为整数；`percent_no_decimal` 将小数或百分比数值转为无小数百分比字符串（如 `0.689` → `69%`）。
- 目标列顺序由 `target.columns` 唯一决定。
- 多源结果按 `field_map` 归一化到 `target.columns` 后**行拼接**（默认 `union_append`），可在源级 `dedup` 后再合并。
- 缺失字段以空字符串填充；额外字段丢弃并记录警告到 QA 报告。

### 双 Sheet 架构与 Diff 流程（v2.0）

- **Sheet1 主库**：`d85fa5`，append-only + row patch。
  - A:K = 业务列（含 `shop_status` / `更新时间`）
  - L = `is_new`（每轮重置，仅本轮新增行为 `1`）
  - M = `入库时间`（首次进入主库日期，已有值永不覆盖）
- **Sheet2 快照**：`05FUQ4`，每轮全量覆盖 A:K，仅用于与上轮结果做 diff。
- **执行顺序**：
  1. 拉 Aeolus 全量
  2. 读 Sheet2 快照（上轮 `shop_id + shop_status`）
  3. 读 Sheet1 主库（当前 `shop_id + row_index + M列入库时间`）
  4. 计算 `new_shops / removed_shops / status_changes`
  5. patch Sheet1：existing 更新 B:L；new append A:M；removed 仅改 `J=removed`、`L=0`
  6. `Sheet1!K2 = today`
  7. 全量覆盖 Sheet2 A:K
  8. RAW 回捞 + QA diff 摘要落盘

### 写入安全规范（强制实现）

1. **Sheet1 禁止全表覆盖**：只允许单行 / 连续行块 patch 与末尾 append，A1:M1 表头只允许补齐空表头，不允许改写既有表头值。
2. **Sheet2 允许全量覆盖**：`A2:K10000` 先 clear 再一次性写入本轮快照。
3. **`M` 列永久保护**：已有值绝不覆盖；仅当主库已有 shop 的 `M` 为空时，才在首次进入 v2.0 时回填今日日期。
4. **更新日期锚点**：`Sheet1!K2` 每轮强制写入 `YYYY-MM-DD`。
5. **RAW 回捞**：至少回读 `Sheet1 A1:M3`、`Sheet2 A1:K3`、`K2`，且用户验收时再额外回读 `A1:M600` / `A1:K600` 核对总行数。
6. **严禁 `+values-append`**：代码里通过 `assert` 硬拒绝。

### 质检方案（QA）

**结论**：**复用 `zero-trust-qa-checker` 为基础 + 自建轻量交叉质检模块**。

- **`zero-trust-qa-checker` 复用**：适合对目标 Sheet 数据做契约断言（`non_null` / `unique` / `positive` / `link_present` 等），配套 `resources/qa_manifest.example.json` 提供最小可运行示例。写入完成后**如果**用户配置 `qa.engine=zero_trust`，脚本会自动调用其 `v3_engine.py`。
- **自建 `scripts/qa_check.py`**：覆盖 zero-trust 未覆盖的"多源合并交叉校验"缺口：
  - `records_vs_rows`：Σ(records_fetched) 与转换后的 `expected_after_transform` / `rows_written` 一致性校验；启用 dedup 时以去重后目标行数为准。
  - `field_map_zero_loss`：每个源的 `field_map` 映射到目标列时字段不丢失（除已知丢弃字段外全部命中）。
  - `updated_at_anchor`：目标 `updated_at_cell` 存在且格式正确。
- **QA 报告输出**：`output/qa_report_YYYYMMDD_HHMMSS.json`，包含每源 `records_fetched`、`dedup_applied`、`value_map_applied`、`field_format_applied`、`rows_written`、`raw_readback` diff、`cross_checks` 结果、`status` (`PASS`/`WARN`/`FAIL`)、`errors[]`。

### 依赖 Skill

- **写入通道**：底层通过 `lark-cli sheets +cells-clear` / `+csv-put` / `+csv-get`（AIME 定制版），严格遵循 `feishu-doc-writing-guide` 的 RAW 原子锁与幂等 upsert 规范。
- **Aeolus 取数**：调用 `inner_skills/aeolus-platform-analysis` 的 `url_query.py` / `download_dashboard_data.py`。
- **Bitable 取数**：调用 `lark-cli base +record-list`（`inner_skills/managing-lark-bitable-data`）。
- **可选质检**：调用 `user_skills/zero-trust-qa-checker/scripts/v3_engine.py`。

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：
  ```text
  跑一下每周五数据更新，把 VA 风神那个 dataQuery 刷到 my.larkoffice 的 Sheet。
  ```
- 🤖 标准输出：
  ```text
  已完成同步：
  - 数据源 [va_dq_2507297138](aeolus/VA): records_fetched=350
  - dedup(shop_id): 原始 350 行 → 剔除 Sum/空 7 行 → 去重后 49 行
  - 目标 Sheet [my.larkoffice/KRIUslDgdh7WvYtXK8ZmhOCcyOb]:
      - data_range=A2:J10000 已清空
      - rows_written=49
      - K2 = 2026-08-10
      - value_map(shop_status): 49 行 `2 → active`
      - field_format: F/G/I 整数化，H 百分比无小数
  - RAW 回捞 A1:K3 通过
  - QA report → output/qa_report_20260810_162341.json (status=PASS)
  ```

## 更新日志 (Changelog)

- **2.0（2026-08-11）**：双 Sheet 架构 + 增量 diff + 状态追踪；Sheet1 改为 patch/append，Sheet2 改为全量快照；新增 `is_new` / `入库时间` 两列；`removed_shops` 不删行，仅将 `shop_status` 标为 `removed`；QA 报告新增 diff 摘要。
- **1.4（2026-08-11）**：Aeolus 单图表 xlsx 直出修复；`scripts/sources/aeolus_source.py` 改走 `--chart-id <rid>` 单图表下载链路，绕开 dashboard 403 与 `url_query` 对 pivot cells 的误展开；pivot_table 数据抽取结果从 49 行恢复到 542 行；xlsx 异步下载增加 3 次幂等重试（5s 间隔）；继续保留 `server_total > fetched_rows` 熔断。
- **1.3（2026-08-10）**：去重 + 数值格式清洗 + J1 表头写入授权；`scripts/sync_main.py` 新增 `dedup`（按 `shop_id` 去重 + 剔 Sum/空行）与 `apply_field_format()`（`int_round` / `percent_no_decimal`）；`resources/example_weekly_friday.json` 新增 `dedup`、`field_format`、`target.columns` 中 J 列 = `shop_status`；QA 报告扩展 `dedup_applied` / `field_format_applied`。
- **1.2（2026-08-10）**：数据源热更新 + `value_map` 支持；首个实例 URL 切换到 `id=2507297138`；新增源级值转写（示例：`shop_status: {"2": "active"}`）；`scripts/sync_main.py` 在归一化后应用 `value_map`；Aeolus 下载结果缺字段时自动回退 `url_query` 继续取数。
- **1.1（首发）**：多数据源（Aeolus + Bitable）配置驱动同步基础设施；表头锁死 / data_range 幂等清空 / K2 日期锚点 / RAW 回捞 / 轻量交叉质检 + 可选复用 zero-trust-qa-checker；首个实例：每周五 VA dataQuery → my.larkoffice Sheet KRIUslDgdh7WvYtXK8ZmhOCcyOb（sheet=d85fa5）。
