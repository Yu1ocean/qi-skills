---
name: task-flow-engine
description: 任务追踪与巡检引擎：读取飞书任务台账（任务库）执行 DDL 巡检、休假免打扰与静默顺延，并产出可直接用于私聊/群聊催办分发的告警词典（JSON）。适用于每日催办巡检、负责人路由、法定假期跳过与个人休假免打扰。
author: 于奇楠
metadata:
  version: 2.0.0
  updated_at: "2026-05-04"
---

# Task Flow Engine

## Common Rationalizations（常见借口库）

- “只是读表/算 DDL，不用做输入校验。”
- “state_file 就随便写到一个绝对路径，反正本地文件不重要。”
- “JWT 缺失/接口失败我就当作大家都在休假，先静默掉催办。”

## Red Flags（危险信号）

- 未校验 spreadsheet/token 或 sheet_title 为空就开始读取。
- `state_file` / `output` 允许写到任务目录之外（可能误写污染工作区）。
- 休假拦截器在依赖缺失/JWT 缺失/接口失败时选择 fail-close（导致关键催办被静默）。

## Verification（强制验收清单）

- `scripts/task_patrol.py`：
  - 能输出完整 JSON（含 `grouped_results` 与 `routes.*`）。
  - `--no-state` 开启时不写入本地状态文件。
  - `state_file` 为相对路径时，写入位置在 `user_skills/task-flow-engine/` 目录内；若传入越界绝对路径应直接报错。
- 休假免打扰：
  - 法定休息日命中时：`routes.private/group/unmapped` 被清空（静默顺延），但明细与统计仍保留。
  - 个人休假依赖失败时：fail-open（视为未休假），不阻断催办触达。

本 Skill 是一个“纯任务追踪引擎”，负责对飞书【任务库】做巡检与分发路由：

- 读取 `【任务库】` → 计算 DDL 风险（临近到期/已超期/缺失 DDL/格式异常）
- 基于花名册 `【团队联系方式】` 做负责人身份映射（中文名 → Open ID / 邮箱）
- 输出可直接供上游发送器使用的分发 JSON（私聊催办 / 群聊公开提醒）
- 在巡检分发阶段自动应用“休假免打扰与顺延”拦截器

> ✅ 边界变更（重要）：
> - “双轨写入（dual_write）”已迁移至 `heartbeat-inspector`。
> - 本 Skill 不再负责把增量事件写入台账，只负责**读取任务库并巡检/催办**。

## 适用场景

- 需要对任务台账做每日巡检，并按负责人输出私聊催办 / 群聊公开提醒分包
- 需要在法定休息日自动静默顺延当天催办
- 需要在负责人疑似请假、OOTO、OnLeave 时跳过对应私聊/群聊提醒

## 目录与脚本

- `scripts/task_patrol.py`：读取任务库并输出巡检分发 JSON
- `scripts/run_task_patrol_save.py`：运行巡检并把完整 JSON 保存到本地文件（避免 stdout 截断）
- `task_flow_engine/patrol.py`：DDL 巡检、分流与卡片渲染核心实现
- `task_flow_engine/vacation.py`：法定休息日与个人休假静默顺延拦截器
- `task_flow_engine/lark_sheets_cli.py`：飞书表格读写 CLI 轻封装（用于读取任务库/花名册）
- `README.md`：运行方式、字段说明与背景介绍

## 执行要求

### 1. 先准备鉴权与依赖

运行脚本前，确保：

- 飞书表格读写链路可用
- 若需要调用飞书 freebusy API，运行命令时必须设置 `include_secrets=true`，让脚本读取 `AIME_USER_CLOUD_JWT`
- 若要启用法定假期判断，运行环境需安装 `chinese_calendar`

### 2. 生成巡检分发 JSON

当需要输出私聊/群聊催办分包时，运行：

```bash
cd user_skills/task-flow-engine && python3 scripts/task_patrol.py \
  --spreadsheet "<飞书表格URL或token>" \
  --task-sheet-title "任务库" \
  --roster-sheet-title "团队联系方式" \
  --target-chat "oc_xxx" \
  --state-file ".patrol_state.json"
```

### 3. 保存完整巡检结果（可选）

当 stdout 可能被截断、需要把完整结果落盘时，运行：

```bash
cd user_skills/task-flow-engine && python3 scripts/run_task_patrol_save.py \
  --spreadsheet "<飞书表格URL或token>" \
  --task-sheet-title "任务库" \
  --roster-sheet-title "团队联系方式" \
  --target-chat "oc_xxx" \
  --state-file ".patrol_state.json" \
  --output alerts.json
```

## 休假免打扰规则

巡检脚本默认自动启用以下拦截器：

- 法定休息日：使用 `chinese_calendar` 判断当天是否为法定休息日；命中后，清空当天 `routes.private`、`routes.group`、`routes.unmapped`，实现整天静默顺延
- 个人休假：使用飞书 `freebusy` API 检查负责人当天忙碌时长；命中后，跳过该负责人的私聊催办与相关群聊公开提醒
- fail-open：依赖缺失、JWT 缺失、或飞书接口失败时，一律视为“未休假”，保证催办触达

调试时可使用以下参数：

- `--disable-legal-holiday-guard`：关闭法定休息日静默顺延
- `--disable-personal-leave-guard`：关闭个人休假静默顺延
- `--leave-check-min-busy-hours <小时>`：调整 freebusy 命中的最小忙碌时长阈值，默认 4.0

## 输出约定

巡检输出 JSON 中重点关注：

- `grouped_results`：异常明细，不受休假拦截器影响
- `routes.private`：实际要发送的私聊分包
- `routes.group`：实际要发送的群聊公开提醒分包
- `routes.unmapped`：无法映射负责人时的兜底桶
- `vacation`：本次法定假期 / 个人休假命中与跳过明细
- `state`：状态缓存信息

需要查看更多背景与示例时，读取 `README.md`。
