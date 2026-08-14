---
name: us-am-stats-sync
skill_id: 56a9d7b0-953b-4ee2-81af-7a86fd7a8f29
version: 1.7
description: 将「美区AM招商统计」飞书多维表格每日同步到统计电子表格，支持分页拉取 Bitable、US行业英文转中文、明细表按日期追加写入、每日 Bitable 原始快照落盘、更新日期落列、US行业统计表 SUMIF 公式化改造、趋势计算与写后 RAW/公式校验。适用于用户要求同步 US AM 招商统计、刷新 VM2reD 明细、更新 2unp6l 汇总看板或配置每日 19:00 定时同步时使用。
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
- 明细写入使用清空、全量覆盖、覆盖历史行等破坏性模式，而不是按 `sync_date` 表尾追加。
- 写入后未完成 `VM2reD!A1:J3` RAW 回捞，或 `2unp6l!B2:I9` 公式校验不是 success。
- `US行业统计!B2` 写后不包含 `SUMIF` 公式。

## Verification（强制验收清单）

一次同步任务只有同时满足以下条件，才允许标记成功：

1. 明细写入前完成源字段契约校验；字段漂移时必须先生成 `schema_drift` 结构化报告，只有仍为必需字段且无别名/兜底时才 `raise`。
2. 已知漂移处理：`历史入驻新增可售` 优先读取上游现存字段 `可售数`；若 `可售数` 也已删除或不可见，则作为可选字段写入 `NULL` 兜底；`USAM` 上游已删除或不可见，作为可选字段写入 `NULL` 兜底。
3. 明细表必须先读取现有 `A1:J10000`，以 `更新日期` 作为逻辑 `sync_date` 字段检查当日幂等；若已有当日行则跳过，若无当日行则仅追加数据行，不覆盖表头和历史行。
4. 每次成功拉取 Bitable 后必须写入 `output/snapshots/bitable_snapshot_YYYYMMDD.json`，JSON 结构固定为 `{"sync_date":"YYYY-MM-DD","records":[...]}`。
5. 汇总表 `2unp6l` 的公式区域由用户维护，脚本**禁止**覆盖写入（只允许写 `N2`）。
6. 更新日期必须写入 `2unp6l!N2`，且写入内容为公式：`=MAX(VM2reD!J:J)`。
7. 明细表需在 `O` 列起维护“按同步日期横向追加”的辅助区（幂等追加：若当日列已存在则跳过）。
8. `sync_bitable_to_sheet.py` 对所有写入函数入口做硬熔断断言：只允许写入明细表 `VM2reD`；断言失败必须抛异常并写入本地 audit log。

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
- 默认明细写入范围：`A:J`，表头固定在第 1 行；每日同步按逻辑 `sync_date` 幂等追加到表尾，禁止清空或全量覆盖历史行
- 默认每日快照目录：`output/snapshots/bitable_snapshot_YYYYMMDD.json`，结构为 `{"sync_date":"YYYY-MM-DD","records":[...]}`
- 默认 RAW 回捞范围：明细 `A1:J3`，汇总 `A1:K14`
- 默认唯一允许的汇总写入单元格：`2unp6l!N2`（写入公式 `=MAX(VM2reD!J:J)`）
- 默认明细辅助区起始列：`VM2reD!O1`（按日期横向追加，写第 1 行日期表头、第 2~8 行 7 个行业入驻数、第 9 行总计）
- 默认执行权限：必须通过 `bash` 工具设置 `include_secrets=true`

## ⚙️ 核心架构 / SOP / 约束条件

运行脚本时必须通过 `bash` 工具直接执行，并设置 `include_secrets=true`，确保 AIME 定制版 `lark-cli` 能拿到用户级飞书访问权限。

```bash
python3 scripts/daily_sync.py
```

`daily_sync.py` 会依次执行：

1. `validate_sync_contract()`：在副作用发生前校验 Bitable token、表 ID、目标电子表格、工作表 ID 与输出列契约。
2. `step1_sync_detail()`：分页拉取 Bitable 全量记录，把 `US行业` 英文值映射为中文；成功拉取后先写入 `output/snapshots/bitable_snapshot_YYYYMMDD.json` 原始快照，再读取 `VM2reD!A:J` 检查当日逻辑 `sync_date` 是否已存在；若存在则跳过明细写入，若不存在则仅把本次数据行追加到表尾，表头第 1 行和历史行保持不动。
3. `step2_update_formulas()`：只允许写入 `2unp6l!N2` 更新日期公式 `=MAX(VM2reD!J:J)`，其余区域（含 `B2:F9`、趋势区等）全部由用户手工维护，脚本不得覆盖。
4. `step3_write_detail_aux_area()`：在 `VM2reD` 的 `O` 列起建立横向辅助区（每列一个同步日期），幂等追加今日列：第 1 行写日期 `YYYY-MM-DD`，第 2~8 行写 7 个行业的新增入驻数（行业顺序与 `2unp6l!A2:A8` 一致），第 9 行写总计。
5. 每次运行都会执行上游 Schema 漂移主动巡检：对比期望字段、别名字段与实际字段；发现漂移时写入 `output/schema_drift/schema_drift_YYYYMMDD_HHMMSS.json`，并在脚本 JSON 输出中返回 `schema_drift` 与 `schema_drift_log`。仍缺少必需字段时保留副作用前硬熔断。

## 字段与映射

明细输出列固定为：`US行业 / USAM / 线索数 / 可联系 / 已触达 / 有意愿 / 新增入驻数 / 新增入驻可售 / 历史入驻新增可售 / 更新日期`。`SourceID` 与 `序号` 不写入。

字段漂移契约：`新增入驻数` 优先从上游字段 `7月后新增入驻数` 读取，作为阶段累计入驻口径；`历史入驻新增可售` 优先从上游字段 `可售数` 读取；若 canonical 字段与 `可售数` 均已删除或不可见，则保留输出列并写入 `NULL`，避免废弃指标阻断每日同步；`USAM` 当前上游字段已删除或当前权限不可见，输出列保留但写入 `NULL`，用于保证目标 Sheet 结构稳定。

趋势计算基于明细表历史行的 `更新日期` 字段（逻辑含义为 `sync_date`）；脚本支持 `M/D`、`YYYY/M/D`、`YYYY-MM-DD` 解析。近 7 天与近 4 周趋势只展示当前已积累的历史日期 / 自然周；若历史行不足 7 天 / 4 周，只展示现有数据，不补 0、不报错。

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

- 1.7：收紧写入边界：汇总表只允许写 `2unp6l!N2`（公式 `=MAX(VM2reD!J:J)`），删除对 `B2:F9` 与趋势辅助区的覆盖写入；在 `VM2reD` 的 `O` 列起新增“按同步日期横向追加”的辅助区；`sync_bitable_to_sheet.py` 增加写入边界硬熔断断言并落本地 audit log。
- 1.6：明细表从“清空后全量覆盖”改为按逻辑 `sync_date` 幂等追加；同步前读取 `VM2reD!A:J` 检查当日是否已存在，存在则跳过写入，不重复追加；每次成功拉取 Bitable 后落盘 `output/snapshots/bitable_snapshot_YYYYMMDD.json` 原始快照；趋势计算不足 7 天 / 4 周时仅展示已有日期 / 自然周。
- 1.5：新增近 7 天每日趋势与近 4 个自然周趋势计算，基于明细表 `更新日期` 聚合 7 个关键指标，并固定写入汇总表 `2unp6l!A17:I30`，避开现有 `A1:K15` 公式与参数区。
- 1.4：修复 2026-08-10 至 2026-08-13 连续熔断的字段漂移：`新增入驻数` 改读上游别名 `7月后新增入驻数`，schema drift 命中别名后仅记录 `use_alias` 不再硬熔断；新增 `--date` 历史补跑参数与 `output/audit_logs/` 审计日志。
- 1.3：修复 2026-08-07 上游再次漂移导致的字段断链：确认 `可售数` 已从 Bitable 当前字段列表消失，`历史入驻新增可售` 改为“优先别名、缺失则 NULL 兜底”的可选字段，保留目标 Sheet A:J 结构并恢复每日 19:00 定时同步。
- 1.2：修复源 Bitable 字段漂移导致连续熔断的问题：`历史入驻新增可售` 改读 `可售数` 别名，`USAM` 改为可选字段并写入 `NULL` 兜底；新增每次运行的 Schema 漂移主动巡检与结构化告警日志。
- 0.1：补齐 Forge 规范字段、CDA 三层护栏说明与副作用前契约校验入口，为正式锻造 Upsert 做准备。
