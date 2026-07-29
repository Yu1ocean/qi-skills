---
name: bizhi-dashboard-snapshot
description: 自动执行「必招看板」周趋势快照写入的专属技能，内置可执行脚本读取飞书 Sheets 当前快照、左移 W5-W1、从底表 jlfbt6 本地重算 W0 入驻数、写入日期并回捞验证。适用于必招看板每周趋势快照、重复执行幂等保护、避免 COUNTIFS 非空陷阱和 MCP 隐藏列偏移的稳定看板维护任务。
author: 于奇楠 / Aime
---
version: 2.0
# bizhi-dashboard-snapshot

## Common Rationalizations（常见借口库）

- “这次只更新快照，直接写公式就行。”
- “列位置看起来没变，用序号取列不会错。”
- “同一周又跑一次也没关系，左移一下影响不大。”
- “W0 回捞全 0 可能是刷新延迟，先算成功。”

以上说法都会破坏必招看板的周趋势序列。本技能把快照写入固化为可执行脚本，而不是 prompt 约定。

## Red Flags（危险信号）

- 未使用 `lark_sheets` MCP / `lark-cli sheets`，而是裸调 OpenAPI。
- 使用跨 Sheet `COUNTIFS(...,"<>")` 或依赖飞书公式刷新作为唯一统计来源。
- 通过列序号读取底表字段，未按 A1 列字母定位 B/C/Q/V 等列。
- 日期单元格已属于同一 ISO 周时仍默认左移，造成同周重复快照。
- 任一分组失败后中断全部任务，导致其他分组无法写入。

## Verification（强制验收清单）

完成一次快照任务时必须满足：

1. 当前快照区域已通过 MCP 读取。
2. 若不是同一 ISO 周重复执行，W5-W1 已由读取数组第 2-6 列左移写入第 1-5 列。
3. W0 已从底表 `jlfbt6` 的 `5:6379` 行本地重算，而非依赖飞书跨 Sheet `COUNTIFS + "<>"`。
4. W0 标题日期已写入执行当天日期。
5. W0 已回捞，且读回值与本地重算值完全一致。
6. W0 结果非全 0；若全 0，必须标记异常。
7. 任一分组失败只记录该组错误，不中断其他分组，最终汇总各组状态。

## 触发词

- 必招看板快照
- 周趋势快照
- bizhi-dashboard-snapshot
- 看板1执行器
- 必招 6 月入驻数

## Defaults（合规默认值）

- 默认工作簿：`M7x6sla1yh5I2itqefcl7HpqgSe`。
- 默认看板 Sheet：`7JpNIf`；默认底表 Sheet：`jlfbt6`。
- 默认底表行范围：`5:6379`。
- 默认过滤：`B列 = "必招 6 月"` 且 `V列 = "已入驻"`。
- 默认幂等：同一 ISO 周重复执行不左移，仅重算并刷新 W0；只有显式 `--force-shift` 才覆盖。
- 默认校验：写后等待 2 秒并回捞 W0；不一致或全 0 直接标记异常。

## 核心架构 / SOP / 约束条件

### 1. 执行入口

运行脚本时必须通过 `bash` 工具直接执行，并设置 `include_secrets=true`，确保 `lark_sheets` MCP 继承当前用户飞书权限。

```bash
cd user_skills/bizhi-dashboard-snapshot && python3 scripts/run_snapshot.py --json
```

常用参数：

- `--date YYYY-MM-DD`：指定执行日期，默认系统当天日期。
- `--eu-industry-column <列字母>`：当 EU 行业列已确认时显式锁定底表列字母。
- `--force-shift`：强制左移一次；仅在确认需要补跑历史周时使用。
- `--dry-run`：只打印写入动作，不实际写入。
- `--json`：输出结构化 JSON 汇报。

### 2. 三组快照流程

对 US行业、按BD、EU行业三组依次执行：

1. **读取**：用 `lark_sheets` MCP 读取当前快照区域（6列×N行二维数组）。
2. **幂等判断**：读取日期单元格；若日期已属于执行日同一 ISO 周，默认跳过左移，避免重复滚动。
3. **左移**：非重复周时，将数组第 2-6 列写入第 1-5 列位置。
4. **重算 W0**：按标签列逐行从底表本地统计 `B列 = 必招 6 月` 且 `V列 = 已入驻` 的数量。
5. **写入日期**：将执行日写入 W0 标题日期单元格。
6. **回捞验证**：重读 W0 列，与重算值逐项比对；不一致或全 0 即异常。

坐标配置表见 [coordinate-config.md](references/coordinate-config.md)。

### 3. 底表口径

- 工作簿：`M7x6sla1yh5I2itqefcl7HpqgSe`
- 看板 Sheet：`7JpNIf`
- 底表 Sheet：`jlfbt6`
- 底表数据行：`5:6379`
- 固定过滤：`B列 = "必招 6 月"`，`V列 = "已入驻"`
- US行业：`C列 = 行业名称`，匹配 `G16:G22` 行标签。
- 按BD：`Q列 = BD姓名`，匹配 `Z16:Z22` 行标签。
- EU行业：读取 `AH16:AH19` 标签后自动匹配候选底表列；若已确认底表结构，优先传 `--eu-industry-column` 锁死列字母。

### 4. 错误处理

脚本对每个分组独立 `try/except`：

- 单组失败：记录 `errors`，继续执行后续分组。
- 总状态：所有分组 `ok=true` 才返回退出码 0；存在失败则返回退出码 2。
- 输出：始终包含每组标签、重算 W0、回捞 W0、是否同周跳过左移、错误信息。

### 5. 已知陷阱规避

1. **COUNTIFS + `"<>"` 失效**：脚本不写飞书统计公式，全部通过 Python 本地数组计算。
2. **MCP 隐藏列偏移**：脚本用 `B5:B6379`、`C5:C6379`、`Q5:Q6379`、`V5:V6379` 等 A1 字母范围读取，不用可见列序号。
3. **重复执行左移**：默认通过日期单元格判断同一 ISO 周，重复执行不左移；补跑场景才允许显式 `--force-shift`。

## 案例实录 (Best Practice)

- 用户输入：

```text
请运行 bizhi-dashboard-snapshot，执行本周必招看板快照。
```

- 标准动作：

```bash
cd user_skills/bizhi-dashboard-snapshot && python3 scripts/run_snapshot.py --json
```

- 标准判断：

```text
若返回 ok=true：三组 W0 均已回捞验证通过。
若返回 ok=false：查看 results[].errors，定位失败分组；不要把局部失败伪装成全局成功。
```

## 更新日志

- v2.0：彻底绕开 lark-cli sheets（Sheet AI tool API 对大工作簿 5s RPC 超时）。改用 MITM 代理提取 user_access_token + 标准 Lark Sheets V2 REST API 直连读写。坐标基于 2026-07-09 实测重新确认：BD W0 列=AE（原错标 AF），EU W0 列=AR（原错标 AS），标签列分别为 Y/AL（原错标 Z/AH）。底表导出改走 Drive export CSV。
- v1.1：首次正式锻造。固化三组快照写入脚本、坐标配置表、幂等判断、W0 本地重算与 RAW 回捞验证。
