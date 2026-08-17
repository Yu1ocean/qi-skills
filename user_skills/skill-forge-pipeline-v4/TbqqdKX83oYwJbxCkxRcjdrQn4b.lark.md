# US AM Stats Sync

<figure view-type="Card"><source name="us-am-stats-sync.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZTJiNDc3ZGQ4Zjg3Njk5ZmUyZjVjNWI4MTIxZjVmZmZfZjhkOTI0Yzk1NmJiMzdkY2Y5ZjFkNWI1OGQwYjZjYWNfSUQ6NzY3NDg1NDY5MTE4ODI4MDI1Nl8xNzg2OTQxMzYxOjE3ODY5NDQ5NjFfVjM" mime="application/zip" size="55003" token="Hz3dbyb5Hos3kExWLGQcn8mBnwe"/></figure>

## 📌 技能简介

**当前版本：v2.0**（2026-08-17 更新）

将「美区AM招商统计」飞书多维表格每日同步到统计电子表格，并在 明细(VM2reD) 页维护按同步日期横向追加的辅助区；汇总页(US行业统计/2unp6l)仅维护 N2 更新日期公式。v2.0 起额外固化 **7 日 / 4 周趋势迷你图数据源区契约**与**受保护区域禁写护栏**。

- 目标 Sheet：https://bytedance.larkoffice.com/sheets/XZoSsAwObh72kPtn3DLmWJ4AyWc
- 明细 Tab：`明细`(VM2reD)
- US行业统计 Tab：`US行业统计`(2unp6l)

## 🔑 触发词

- US AM 招商统计同步
- 刷新 VM2reD 明细
- 更新 2unp6l 汇总公式
- 7 日趋势 / 4 周趋势数据区
- 明细 K 列日期标准化

## ⚙️ 核心架构 / SOP / 约束条件

运行：`python3 scripts/daily_sync.py`（需 include_secrets=true）

执行链路：`validate_sync_contract()` → `step1_sync_detail()`（Bitable 分页拉取 + 快照落盘 + 按 sync_date 幂等追加）→ `step2_update_formulas()`（只写 N2）→ `step3_write_detail_aux_area()`（O 列起横向辅助区）→ `step4_verify_trend_matrix()`（v2.0 新增，只读验收）。

### 趋势数据区契约（Trend Matrix Contract, v2.0）

7 日 / 4 周迷你图数据源区由用户手工维护，脚本只做只读校验、禁止写入：

- `明细!K` = 日期(标准化)辅助列，`K2:K200` 为 `=IF($J2="","",IF(ISNUMBER($J2),$J2,IFERROR(DATEVALUE($J2),"")))`，格式 yyyy-mm-dd。原因：`明细!J` 是文本日期（`8/14` 与 `2026-08-15` 混排），无法直接做日期区间比较。**所有趋势日期匹配必须走 K 列，严禁直接对 J 列做区间比较。**
- `US行业统计!B17` = `=IF(ISNUMBER($N$2),$N$2,DATEVALUE($N$2))`，是全部趋势区唯一日期基准锚点。
- 7 日趋势区 `A18:H28`（日口径 → SUMIFS）：`B19:H19` = `=$B$17-6` … `=$B$17`；`A20:A27` = `=A2`…`=A9`（8 分组）；`B20:H27` = `=SUMIFS('明细'!$G:$G,'明细'!$A:$A,$A20,'明细'!$K:$K,B$19)`；第 28 行总计。
- 4 周趋势区 `A30:E40`（周口径 → MAXIFS）：`B31:E31` = `=$B$17-WEEKDAY($B$17,2)+1-7*n`（n=3,2,1,0）；`B32:E39` = `=IFERROR(MAXIFS('明细'!$G:$G,'明细'!$A:$A,$A32,'明细'!$K:$K,">="&B$31,'明细'!$K:$K,"<="&B$31+6),0)`；第 40 行总计。周口径必须用 MAXIFS 取周内最新快照（入驻数为累计单调递增指标，求和会重复累加）。
- `明细!K1`/`L1` 批注记录各行业迷你图区间（K2→B20:H20 … K9→B27:H27；L2→B32:E32 … L9→B39:E39）。迷你图由用户手动创建，脚本不生成。

### 受保护区域清单（脚本禁写）

`明细!K:K`、`US行业统计!A17:B17`、`US行业统计!A18:H28`、`US行业统计!A30:E40`、`US行业统计!K:L`。

写入边界：明细只允许 `A:J` 与 `O` 列起辅助区（**禁写 K:N**）；汇总唯一可写单元格仍只有 **N2**。越界由 `assert_detail_write_range()` / `assert_summary_write_range()` 硬熔断并落 audit log。

### 验收护栏

- `assert_detail_date_norm_column_alive()`：`明细!K2` 必须为有效日期序列号，否则判定辅助列断链。
- `assert_trend_anchor_alive()`：`B17` 有效且 `B19 == $B$17-6`，否则判定趋势区日期锚点漂移。
- `+formula-verify` 对 `B2:I10`、`A18:H28`、`A30:E40` 全部收敛 `status=success` / `total_errors=0`。

## 📖 案例实录 (Best Practice)

- 用户输入：同步 US AM 招商统计到 Sheet，并校验趋势区
- 标准输出：JSON 审计日志 + 明细 `A1:J3` RAW 回捞 + 汇总 `B2:I10` 公式校验 success + 趋势区 `A18:H28` / `A30:E40` 当日列与最新快照 1:1 + formula-verify zero-error

<figure view-type="Card"><source name="us-am-stats-sync.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NzM4YWRjZWRhZjM3NDk1ZDczZGMyNTBjZDVlODIyMjVfNTQxMGEzMjY0ZGQyZDI4ZDFhM2NjOWI4MmU3YzUzNGFfSUQ6NzY3MzcxOTI0MjcxOTg5MDQwMF8xNzg2OTQyNzEzOjE3ODY5NDYzMTNfVjM" mime="application/zip" size="36078" token="RtKrbTB5IoNeYBxLoLRcbzHtn9d"/></figure>

<figure view-type="Card"><source name="us-am-stats-sync.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZmJiMDAzOTEyM2RlMmNjMzk0MjYwY2FkYjI1YzFmOGZfZWNlOTNmMDJhYmM2NmYzZjc2MDQ5YTU4YjZiYTJhZmFfSUQ6NzY3NDgwODg0NDk3OTYwNDQyOF8xNzg2OTQyNzEzOjE3ODY5NDYzMTNfVjM" mime="application/zip" size="44197" token="P1dcbvwwLokDa8xNW47cl4YFnKI"/></figure>

<figure view-type="Card"><source name="us-am-stats-sync.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OWRhNWRhMDc2NjVjZDAyYzIyZWY4ZTBkOGRlNDRmMGRfMjljOWFlZjZlODBkMTMwNjA2MmE3YzAxYjZhOWJiZjBfSUQ6NzY3NDgwODk5NjQ0MTc4NzM1OF8xNzg2OTQyNzEzOjE3ODY5NDYzMTNfVjM" mime="application/zip" size="44197" token="O5vUbpEQ5oZrv9x5aJIcUpG8nng"/></figure>

<figure view-type="Card"><source name="us-am-stats-sync.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OGMzMTRhZjcyOGQxZTJjYTI5OTQwNWFlN2E0OTkzYTFfNjY3NjdjMmFkMGRjZGVhMzZlZDQzOTNkOTIxNDcwODhfSUQ6NzY3NDg0NDA1MjIxMDc5Nzc3M18xNzg2OTQyNzEzOjE3ODY5NDYzMTNfVjM" mime="application/zip" size="46103" token="EgBabTG4OofAnqxIO4OcsZLfnkg"/></figure>

<figure view-type="Card"><source name="us-am-stats-sync.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MDE2MWY4NDRmNGFhYTVkZDhlN2FjNjU3YjI5MWI3YWZfMmY1Njk5MTllM2UyNDMyZDA1M2U1OGQ5ZmI5YzgxN2ZfSUQ6NzY3NDg2MDUwNjI2Mzg4MzAzM18xNzg2OTQyNzE1OjE3ODY5NDYzMTVfVjM" mime="application/zip" size="59857" token="RN3XbRVWeoVN1GxXN4ScbEkEnEg"/></figure>