---
name: task-flow-engine
description: 读取飞书任务台账并生成任务追踪、DDL 巡检与催办结果。适用于 TaskFlow 入库、每日催办巡检、负责人路由和休假免打扰场景。
author: 于奇楠
version: 2.1
metadata:
  version: 2.1.0
  updated_at: "2026-05-19"
---

# Task Flow Engine

## Common Rationalizations（常见借口库）

- “只是读表/算 DDL，不用做输入校验。”
- “state_file 就随便写到一个绝对路径，反正本地文件不重要。”
- “JWT 缺失/接口失败我就当作大家都在休假，先静默掉催办。”

## Red Flags（危险信号）

- 未校验 spreadsheet/token 或 sheet_title 为空就开始读取。
- `state_file` / `output` 允许写到任务目录之外（可能误写污染工作区）。
- 从上下文、历史日志、缓存或 hardcode 直接复用 `chat_id`，绕过 Chat Registry。
- 群播前未执行群元信息拉取与群名关键字 pre-flight。
- 休假拦截器在依赖缺失/JWT 缺失/接口失败时选择 fail-close（导致关键催办被静默）。
- 使用手写临时发信脚本（如 `send_l1_reply.py`）构造 TaskFlow 入库回执，绕过统一路由引擎与 `reply_message` 入口。
- 把带 `suggestion_reply` 的非标抽取结果直接喂给 `heartbeat-inspector/scripts/dual_write.py` 写入 `任务库`。
- 把 `run_task_patrol_save.py` + `task_patrol_notify.py` 拆成 committed send 的正式链路，或在群播成功后对同一逻辑主题再次执行 committed send。

## Verification（强制验收清单）

- `scripts/task_patrol.py`：
  - 能输出完整 JSON（含 `grouped_results` 与 `routes.*`）。
  - `--no-state` 开启时不写入本地状态文件。
  - `state_file` 为相对路径时，写入位置在 `user_skills/task-flow-engine/` 目录内；若传入越界绝对路径应直接报错。
- Chat Registry / 群播治理：
  - `CHAT_REGISTRY.json` 是本 Skill 的 chat_id SSOT；`--target-chat` / `--target-chat-id` 仅允许作为断言，不得作为来源。
  - `scripts/task_patrol_notify.py` 默认只 dry-run；真实群播必须同时传 `--commit-group-broadcast --confirm-group-broadcast CONFIRM_GROUP_BROADCAST`。
  - 真实群播前必须通过飞书群元信息 pre-flight 校验 `chat_id` 与 `expected_name_keywords`，不匹配直接熔断并写 Notification Log。
  - committed send 只能通过 `scripts/run_daily_pipeline.py` 发起；一旦检测到 group broadcast 成功，不允许对同一逻辑主题再次执行 committed send。
- TaskFlow 入库确认回执：
  - 只允许走统一路由引擎 + `reply_message` 入口，禁止手写临时脚本直接发 L1 回执。
  - 主进程命中 TaskFlow 后必须**绝对静默**，只允许派发 `create_task`，禁止发送任何群内过程态确认消息。
  - 执行端必须携带 Feishu 原始 `message_id`（形如 `om_xxx`）；本地 UUID、缓存句柄、历史猜测值一律视为非法输入并熔断。
  - 回执正文必须满足 `projects/路由决策进化机制/taskflow_thread_reply_spec.md` 的最小字段集（单条、单链接、直达 `任务库` sheet）。
- 休假免打扰：
  - 法定休息日命中时：`routes.private/group/unmapped` 被清空（静默顺延），但明细与统计仍保留。
  - 个人休假依赖失败时：fail-open（视为未休假），不阻断催办触达。

本 Skill 是一个“纯任务追踪引擎”，负责对飞书【任务库】做巡检与分发路由：

- 读取 `【任务库】` → 计算 DDL 风险（临近到期/已超期/缺失 DDL/格式异常）
- 基于花名册 `【团队名单】` 做负责人身份映射（中文名 → Open ID / 邮箱）
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
- `CHAT_REGISTRY.json`：工作区级 Chat Registry（所有群聊 chat_id 的 SSOT，位于工作区根目录）
- `task_flow_engine/chat_registry.py`：Chat Registry 读取、用途解析与群名断言逻辑
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
  --roster-sheet-title "团队名单" \
  --broadcast-usage "task_patrol_broadcast" \
  --state-file ".patrol_state.json"
```

### 3. 保存完整巡检结果（可选）

当 stdout 可能被截断、需要把完整结果落盘时，运行：

```bash
cd user_skills/task-flow-engine && python3 scripts/run_task_patrol_save.py \
  --spreadsheet "<飞书表格URL或token>" \
  --task-sheet-title "任务库" \
  --roster-sheet-title "团队名单" \
  --broadcast-usage "task_patrol_broadcast" \
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

## 更新日志 (Changelog)

- **2026-06-18 v2.1.1**：群发卡片模板（`build_minimal_broadcast_card`）强化「📌 重点关注」视觉权重：重点负责人由横向点名升级为逐行 `🚨 **@负责人**｜‼️风险类型×数量`，并对已超期 / 缺失 DDL / 格式异常添加 `‼️` 强提示，让预算确认、DDL 告警等高优先级提醒更像“红色探针”而不是普通列表。
- **2026-05-19 v2.1.0**：群发卡片模板（`build_minimal_broadcast_card`）取消 `###` 三级标题（飞书卡片中字号偏小、与正文区隔不明显，且会让眼睛聚焦在小标题上），改为「正文加粗（`**...**`）+ `hr` 分割线」的扁平结构。`日期`、`📊 巡检统计`、`📌 重点关注`、`🖼️ 异常总览表` 现各自独立为一个 markdown element，由 `{"tag": "hr"}` 分割线分隔，全文字号统一，视觉更简洁、扁平、无层级噪音。函数签名与返回结构（`{"name": "AimeCard", "dsl": {...}}`）保持不变。
- **2026-05-04 v2.0.0**：从 heartbeat-inspector 拆分为纯任务追踪引擎，专注于 DDL 巡检、休假免打扰与私聊/群聊催办分发路由。
