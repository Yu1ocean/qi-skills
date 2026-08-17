# US AM Stats Sync

<figure view-type="Card"><source name="us-am-stats-sync.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MDE2MWY4NDRmNGFhYTVkZDhlN2FjNjU3YjI5MWI3YWZfMmY1Njk5MTllM2UyNDMyZDA1M2U1OGQ5ZmI5YzgxN2ZfSUQ6NzY3NDg2MDUwNjI2Mzg4MzAzM18xNzg2OTQyNzE1OjE3ODY5NDYzMTVfVjM" mime="application/zip" size="59857" token="RN3XbRVWeoVN1GxXN4ScbEkEnEg"/></figure>

## 📌 技能简介

**当前版本：v2.2**（2026-08-17 更新）

将「美区AM招商统计」飞书多维表格每日同步到统计电子表格，并在 明细(VM2reD) 页维护按同步日期横向追加的辅助区与 7 日 / 4 周趋势矩阵；汇总页(US行业统计/2unp6l)只保留公式，仅 N2 更新日期公式由脚本写入。

**v2.1 核心约定（最高优先级红线）**：`US行业统计`(2unp6l) **只允许写入 / 修改公式**（必须以 `=` 开头），**绝对禁止任何静态数据值**（标题文本、行业名、「总计」、日期常量、手填数字）；`明细`(VM2reD) 是**所有数据变动的唯一落点**（新增行、字段值、辅助矩阵、趋势矩阵、标题行）。

- 目标 Sheet：https://bytedance.larkoffice.com/sheets/XZoSsAwObh72kPtn3DLmWJ4AyWc
- 明细 Tab：`明细`(VM2reD)
- US行业统计 Tab：`US行业统计`(2unp6l)

## 🔑 触发词

- US AM 招商统计同步
- 刷新 VM2reD 明细
- 更新 2unp6l 汇总公式
- 7 日趋势 / 4 周趋势矩阵
- 明细 K 列日期标准化
- 明细 AA:AH 趋势矩阵

## ⚙️ 核心架构 / SOP / 约束条件

运行：`python3 scripts/daily_sync.py`（需 include_secrets=true）

执行链路：`validate_sync_contract()` → `step1_sync_detail()`（Bitable 分页拉取 + 快照落盘 + 按 sync_date 幂等追加明细 A:J）→ `step2_update_formulas()`（只写 `2unp6l!N2` 更新日期公式）→ `step3_write_detail_aux_area()`（明细 O:Z 按日期横向追加辅助区，落点扫描硬性收敛为 `O1:Z1`）→ `step4_verify_trend_matrix()`（只读验收）。

### 🆕 v2.2 修复：step3 辅助区落点扫描收敛 + 容量边界断言

**故障现场**（2026-08-17 13:10 真实复现）：step1（明细追加 8 行 8/17 快照）与 step2（N2）成功、业务结果正确（汇总总计线索数 1,365 = 上游 Bitable 1365，formula-verify zero-error），但 **step3 硬熔断**：

```
AssertionError: [硬熔断] 明细表写入越界！目标 AB1 解析为 AB:AB；
仅允许 A:J 与 O:Z 辅助区，禁止写 ['K:N', 'AA:AH']
```

**根因**：`step3_write_detail_aux_area()` 通过「扫描 明细!第 1 行、取最后一个非空列 +1」决定当日辅助列落点，旧实现读取范围是 `O1:ZZ10`（扫全行）。v2.1 新增的趋势矩阵占用 `AA1:AH24`，其中 `AA1` 是标题文本「📊 7日趋势数据区…」，于是扫描把 `AA` 当成最后非空列，算出落点 `AB1`，撞上 `AA:AH` 保护区被自己的断言拦下。实际 `明细!O1/P1/Q1` = 08/14、08/15、08/16，正确落点应为 `R1`。

**性质**：这是 v2.1 引入保护区时留下的**自伤（self-inflicted）——断言是对的，扫描逻辑没跟上**。护栏正确拦截了越界写入，避免趋势矩阵被覆盖。

**修法（最小改动）**：

1. 扫描范围**硬性收敛为 `O1:Z1`**（常量 `AUX_AREA_SCAN_RANGE`），并对 CLI 返回列做二次截断（只取 `O:Z` 共 12 列）；落点 = `O:Z` 区间内最后一个非空列 +1。
2. 新增 L3 容量断言 `assert_aux_column_within_capacity()`：落点必须落在 `O:Z`（15\~26）内；一旦越过 `Z`（下一列即趋势矩阵首列 `AA`），立即 `raise` 「辅助区容量 12 列已耗尽」并落 audit log，提示人工决策（迁移辅助区 / 迁到 `AI` 起扩展区 / 弃用改用趋势矩阵）。**禁止**静默溢出到 `AA`，**禁止**静默跳过当日列。

**同类风险提示**：任何「扫描最后非空行/列」的逻辑，只要同一行/列上存在保护区或其他功能区，都必须显式限定扫描窗口，不能依赖「表里只有我这一个功能区」的隐含假设。

### ⚠️ O:Z 辅助区 deprecated 候选评估（v2.2）

`O:Z` 每日横向辅助区与 `AA:AH` 趋势矩阵**存在功能重叠**（都是「按日期的分行业新增入驻数序列」）：

| 维度 | `O:Z` 每日辅助区 | `AA:AH` 趋势矩阵 |
|-|-|-|
| 数据来源 | 脚本每日计算后**静态写入** | 公式 SUMIFS / MAXIFS **动态引用明细** |
| 时间窗口 | 只增不减，历史全留 | **滚动 7 天 / 4 周**，自动跟随锚点 `AB2` |
| 容量 | \*\*仅 12 列**（≈12 个同步日）** | 固定 8 / 5 列，无上限\*\* |
| 维护成本 | 每日写入 + 落点扫描（本次 bug 来源） | **零写入**，明细一变自动重算 |
| 数据一致性 | 静态值可能与明细失配 | 始终同源，可 `+formula-verify` |

**结论**：趋势矩阵严格更优。**建议后续版本弃用 `O:Z` 辅助区**，看板统一取数于 `明细!AA1:AH24`。

**本版本处置**：先修 bug、**不删功能**，仅标注为 **deprecated 候选**（常量 `AUX_AREA_DEPRECATED = True`）。正式移除需人工确认 `O:Z` 是否仍被飞书迷你图或外部引用依赖。

### 趋势矩阵契约（Trend Matrix Contract, v2.1）

趋势矩阵位于 **`明细!AA1:AH24`**，脚本只读校验、禁止写入：

- **日期标准化辅助列**`明细!K`：`=IF($J2="","",IF(ISNUMBER($J2),$J2,IFERROR(DATEVALUE($J2),"")))`，把混排文本日期（`8/14` 与 `2026-08-15`）统一成真日期序列号。铁律：日期匹配必须走 `明细!K`，严禁直接对文本列 `明细!J` 做区间比较。
- **日期基准锚点**`明细!AB2`：`=IF(ISNUMBER('US行业统计'!$N$2),'US行业统计'!$N$2,IFERROR(DATEVALUE('US行业统计'!$N$2),""))`
- **7 日趋势区**`明细!AA1:AH12`：`AB3:AH3` = `$AB$2-6`…`$AB$2`；`AA4:AA11` = `='US行业统计'!$A$2`…`$A$9`；`AB4:AH11` = `SUMIFS('明细'!$G:$G,'明细'!$A:$A,$AA4,'明细'!$K:$K,AB$3)`；第 12 行总计。
- **4 周趋势区**`明细!AA14:AE24`：`AB15:AE15` = `$AB$2-WEEKDAY($AB$2,2)+1-7*n`；`AA16:AA23` = `='US行业统计'!$A$2`…`$A$9`；`AB16:AE23` = `IFERROR(MAXIFS(...,'明细'!$K:$K,">="&AB$15,'明细'!$K:$K,"<="&AB$15+6),0)`；第 24 行总计。
- **口径语义**：日口径用 `SUMIFS`（每日每行业仅一行快照）；周口径用 `MAXIFS` 取周内最新快照（入驻数为累计单调递增指标，求和会重复累加）。
- **迷你图批注**：`US行业统计!K1/L1` 仅加飞书批注（批注不是单元格值，不违反公式-only 约定），映射 `K2 → 明细!AB4:AH4` … `L9 → 明细!AB23:AE23`。

⚠️ **v2.0 坐标已作废**：`US行业统计!A17:B17` / `A18:H28` / `A30:E40` 违反核心约定，已整体清除，禁止再按旧坐标读写。

### ⚠️ 陷阱6（v2.1 新增）：`+cells-set` 批量写入时相对引用会按列自动平移

- **现象**：向 `明细!AA16` 写 `='US行业统计'!A2`，落盘后变成 `='US行业统计'!A14`，4 周区行业名错位成参数区「今天 / 目标完成日 / 入驻率」。
- **根因**：同一列内的相对引用会按「该列首个公式单元格」为基准自动偏移；本例同列 `AA4` 已先写公式，引擎按 12 行偏移平移了引用。
- **规范**：跨 Sheet 取固定坐标必须用**绝对引用**`='US行业统计'!$A$2`；写后逐单元格 `+cells-get --include value,formula` 回读核对。

### 受保护区域清单（脚本禁写）

| 受保护区域 | 用途 |
|-|-|
| `明细!K:K` | 日期(标准化)辅助列，趋势矩阵唯一真日期来源 |
| `明细!AA1:AH24` | 趋势矩阵（7 日 SUMIFS + 4 周 MAXIFS，含锚点 AB2） |
| `US行业统计!K:L` | 迷你图批注列（仅批注，不含值） |
| `US行业统计!A12:B16` | 看板参数区（入驻率 B16 等） |

写入边界：明细只允许 `A:J` 与 `O:Z` 辅助区（另预留 `AI` 起扩展区），禁写 `K:N` 与 `AA:AH`；汇总只允许 `N2`，且内容必须以 `=` 开头。⚠️ 辅助区 `O:Z` 容量 12 列 ≈ 12 个同步日，写满后断言会硬熔断而不是覆盖矩阵。

代码层落点：`PROTECTED_RANGES`、`DETAIL_WRITABLE_COLUMN_BLOCKS`、`DETAIL_FORBIDDEN_COLUMN_BLOCKS`（`K:N` + `AA:AH`）、`SUMMARY_ALLOWED_WRITE_CELLS`，断言 `assert_detail_write_range()` / `assert_summary_write_range(target, op, content=...)`。

### 验收护栏

- `assert_detail_date_norm_column_alive()`：`明细!K2` 必须是有效日期序列号，否则判定辅助列断链。
- `assert_trend_anchor_alive()`：`明细!AB2` 有效且 `明细!AB3 == AB2-6`，否则判定锚点漂移。
- `assert_aux_column_within_capacity()`（**v2.2 新增**）：step3 辅助区落点必须落在 `O:Z` 内；算到 `AA` 及其后列即判定为「辅助区扫描范围未收敛」故障，硬熔断。
- `_verify_trend_formulas()`：`US行业统计!B2:I10`、`明细!AA1:AH12`、`明细!AA14:AE24` 三区 `+formula-verify` 必须 `status=success`、`total_errors=0`。
- RAW 回捞：明细 `A1:J3`、趋势矩阵 `明细!AA1:AH24`、汇总核心区 `A1:K16`。
- （**v2.2 新增**）每日同步后必须回读 `明细!O1:Z1`，日期序列必须**连续且无空洞**，且最后一个非空列必须等于当日 sync_date。
- 已验收基线（2026-08-17，v2.2 复跑）：step1 幂等跳过（`rows_appended=0`，明细行数 32 前后不变，`A26:J34` 仍为 8 行 8/17 数据、无重复）；**step3 成功写入 `明细!R1`**（`R1=2026-08-17`，`R2:R9`=0/4/14/88/12/7/29/1，`R10=155`）不再熔断；`明细!O1:Z1` = `2026-08-14, 2026-08-15, 2026-08-16, 2026-08-17` 连续无空洞；7 日区 08/17 列总计 155 与当日快照 1:1，formula-verify 三区 zero-error。

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：`同步 US AM 招商统计，刷新明细和汇总公式，并给我校验结果。`
- 🤖 标准输出：`已完成同步：明细写入 N 行，VM2reD!A1:J3 RAW 回捞通过，US行业统计!B2:I10 公式校验 success，育商行与总计行回读一致，趋势矩阵 明细!AA1:AH24 当日列与最新快照 1:1、formula-verify zero-error，更新日期已刷新为 M/D。全程未向汇总表写入任何静态值。`

<figure view-type="Card"><source name="us-am-stats-sync.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YmIwYTVlZDZmNWQyODRiNGY5ZGUxYzRhMjE3NmZhYTVfMTA0ZTc1YjQ5YWMxMTEzMzBlNmU0OGM1NGE0YWQ5MDhfSUQ6NzY3NDg2NjUyMzE5MzgyMjQ5NF8xNzg2OTQ0MTE2OjE3ODY5NDc3MTZfVjM" mime="application/zip" size="68276" token="SuBwbOupaotA0wxt2xfcX8ZFn56"/></figure>