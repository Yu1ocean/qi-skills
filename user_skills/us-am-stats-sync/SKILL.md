---
name: us-am-stats-sync
skill_id: 56a9d7b0-953b-4ee2-81af-7a86fd7a8f29
version: 1.3
description: 将「美区AM招商统计」飞书多维表格每日同步到统计电子表格，支持分页拉取 Bitable、US行业英文转中文、明细表全量覆盖写入、更新日期落列、US行业统计表 SUMIF 公式化改造与写后 RAW/公式校验。适用于用户要求同步 US AM 招商统计、刷新 VM2reD 明细、更新 2unp6l 汇总看板或配置每日 19:00 定时同步时使用。
author: yuqinan
---

# US AM Stats Sync

## Common Rationalizations（常见借口库）

以下借口一旦出现，必须停止并回到本技能 SOP：

- “只是同步一次数据，可以先不回读。”
- “汇总表已有公式，跳过公式校验也没关系。”
- “字段缺失时先写空值，后面再补。”
- “没有 include_secrets 也可以试一下。”

## Red Flags（危险信号）

出现任意情况时必须熔断，不得继续写入或宣称成功：

- 未通过 `include_secrets=true` 获得 AIME 定制版 `lark-cli` 用户级飞书权限。
- Bitable 源字段缺少任一仍为必需的输出字段，且没有在脚本中显式配置别名映射或可选 NULL 兜底。
- 上游 Schema 发生漂移但脚本没有输出 `schema_drift` 结构化告警日志。
- 目标 Sheet token 或 worksheet id 不等于本技能合规默认值，且用户未明确指定调试目标。
- 写入后未完成 `VM2reD!A1:J3` RAW 回捞，或 `2unp6l!B2:I9` 公式校验不是 success。
- `US行业统计!B2` 写后不包含 `SUMIF` 公式。

## Verification（强制验收清单）

一次同步任务只有同时满足以下条件，才允许标记成功：

1. 明细写入前完成源字段契约校验；字段漂移时必须先生成 `schema_drift` 结构化报告，只有仍为必需字段且无别名/兜底时才 `raise`。
2. 已知漂移处理：`历史入驻新增可售` 优先读取上游现存字段 `可售数`；若 `可售数` 也已删除或不可见，则作为可选字段写入 `NULL` 兜底；`USAM` 上游已删除或不可见，作为可选字段写入 `NULL` 兜底。
3. 汇总表 `B2:F9` 如需写公式，必须写入 `SUMIF` / `SUM` 公式；如已存在 `SUMIF`，仅刷新 `K1:K2` 更新日期。
4. 汇总表写入后回读 `B2` 公式，确认包含 `SUMIF`。
5. 使用 `sheets +formula-verify` 校验 `2unp6l!B2:I9`，状态必须为 `success`。
6. 脚本输出 JSON 审计日志，包含 records_fetched、rows_written、raw_readback 与 formula_verify。

## 使用场景

用于把飞书 Bitable「美区AM招商统计」同步到电子表格 `XZoSsAwObh72kPtn3DLmWJ4AyWc`。核心脚本会把 Bitable 全量记录写入「明细」工作表 `VM2reD`，并确保「US行业统计」工作表 `2unp6l` 使用公式从明细表动态汇总。

## 🔑 触发词

- 核心关键词：
  - US AM 招商统计同步
  - 美区 AM Bitable 同步 Sheet
  - 刷新 VM2reD 明细
  - 更新 2unp6l 汇总公式
- 典型指令示例：
  > 帮我同步 US AM 招商统计到 Sheet。
  > 刷新美区 AM 招商统计明细，并校验 US 行业统计公式。

## 合规默认值 / Defaults

- 默认 Bitable：`MPN9bUhBTaUsgcsrN92m2Oq0yde`
- 默认 Bitable 表：`tblZerjwuSM5rOG3`
- 默认目标电子表格：`XZoSsAwObh72kPtn3DLmWJ4AyWc`
- 默认明细工作表：`VM2reD`
- 默认汇总工作表：`2unp6l`
- 默认明细写入范围：`A:J`，清理上限 `A1:J10000`
- 默认 RAW 回捞范围：明细 `A1:J3`，汇总 `A1:K14`
- 默认公式校验范围：`2unp6l!B2:I9`
- 默认执行权限：必须通过 `bash` 工具设置 `include_secrets=true`

## ⚙️ 核心架构 / SOP / 约束条件

运行脚本时必须通过 `bash` 工具直接执行，并设置 `include_secrets=true`，确保 AIME 定制版 `lark-cli` 能拿到用户级飞书访问权限。

```bash
python3 scripts/daily_sync.py
```

`daily_sync.py` 会依次执行：

1. `validate_sync_contract()`：在副作用发生前校验 Bitable token、表 ID、目标电子表格、工作表 ID 与输出列契约。
2. `step1_sync_detail()`：分页拉取 Bitable 全量记录，把 `US行业` 英文值映射为中文，按固定列序写入 `VM2reD!A:J`，并在 J 列写入当天 `M/D` 格式更新日期。
3. `step2_update_formulas()`：读取 `2unp6l` 当前内容；如果 `B2` 还不是 `SUMIF` 公式，则把 `B2:F9` 改为从「明细」表汇总的公式；如果已是 `SUMIF`，则跳过公式重写，仅刷新 `K1:K2` 的更新日期。
4. 写入后回读 `VM2reD!A1:J3`、`2unp6l!A1:K14`，并使用 `+formula-verify` 校验 `2unp6l!B2:I9` 为 zero-error。
5. 每次运行都会执行上游 Schema 漂移主动巡检：对比期望字段、别名字段与实际字段；发现漂移时写入 `output/schema_drift/schema_drift_YYYYMMDD_HHMMSS.json`，并在脚本 JSON 输出中返回 `schema_drift` 与 `schema_drift_log`。仍缺少必需字段时保留副作用前硬熔断。

## 字段与映射

明细输出列固定为：`US行业 / USAM / 线索数 / 可联系 / 已触达 / 有意愿 / 新增入驻数 / 新增入驻可售 / 历史入驻新增可售 / 更新日期`。`SourceID` 与 `序号` 不写入。

字段漂移契约：`历史入驻新增可售` 优先从上游字段 `可售数` 读取；若 canonical 字段与 `可售数` 均已删除或不可见，则保留输出列并写入 `NULL`，避免废弃指标阻断每日同步；`USAM` 当前上游字段已删除或当前权限不可见，输出列保留但写入 `NULL`，用于保证目标 Sheet 结构稳定。

行业映射为：`Fashion → 服饰服配`，`FMCG → 快消生活`，`Sports & Lifestyle → 运动潮奢`，`Electronics → 3C家电`，`Home & Textiles → 日用家纺`，`Automotive & Tools → 汽摩工具`，`Furniture & Home Improvements → 家具家装`。

## 单独同步明细

如只需要刷新明细，不改汇总公式，可执行：

```bash
python3 scripts/sync_bitable_to_sheet.py
```

## 定时任务建议

配置每日 19:00 定时运行时，任务指令应调用 `daily_sync.py`，并要求保留脚本输出 JSON 作为审计日志。该任务依赖实时 Bitable 数据，适合作为独立上下文运行。

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：
  ```text
  同步 US AM 招商统计，刷新明细和汇总公式，并给我校验结果。
  ```
- 🤖 标准输出：
  ```text
  已完成同步：明细写入 N 行，VM2reD!A1:J3 RAW 回捞通过，2unp6l!B2:I9 公式校验 success，更新日期已刷新为 M/D。
  ```

## 更新日志 (Changelog)

- 1.3：修复 2026-08-07 上游再次漂移导致的字段断链：确认 `可售数` 已从 Bitable 当前字段列表消失，`历史入驻新增可售` 改为“优先别名、缺失则 NULL 兜底”的可选字段，保留目标 Sheet A:J 结构并恢复每日 19:00 定时同步。
- 1.2：修复源 Bitable 字段漂移导致连续熔断的问题：`历史入驻新增可售` 改读 `可售数` 别名，`USAM` 改为可选字段并写入 `NULL` 兜底；新增每次运行的 Schema 漂移主动巡检与结构化告警日志。
- 0.1：补齐 Forge 规范字段、CDA 三层护栏说明与副作用前契约校验入口，为正式锻造 Upsert 做准备。
