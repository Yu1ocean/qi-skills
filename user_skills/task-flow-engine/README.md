# Task Flow Engine（任务追踪与催办巡检）

本仓库提供一组面向飞书任务台账的“巡检 + 分发路由”脚本：

- 读取 `【任务库】`，计算 DDL 风险（临近到期 / 已超期 / 缺失 DDL / 格式异常）
- 从同一份 Spreadsheet 的 `【团队名单】` Sheet 读取花名册（中文名 → Open ID / 邮箱）
- 产出告警词典 JSON（包含：异常明细 + 两阶段路由：私聊催办 / 群聊公开提醒）
- 默认启用休假免打扰（法定休息日静默顺延 / 个人休假静默顺延）

> ✅ 边界说明：
> - “双轨写入（dual_write）”已迁移至 `heartbeat-inspector`。
> - 即：任务台账写入由 `heartbeat-inspector` 负责；本仓库只做**读取任务库的巡检与催办分流**。
> - TaskFlow 入库确认回执只允许走统一路由引擎 + `reply_message` 入口；禁止手写临时脚本直接发 L1 回复。
> - 非标抽取结果（如带 `suggestion_reply` 的 chat_task）禁止直接写入 `任务库`。

---

## 与 heartbeat-inspector 的配合方式

### 1）先保证任务库已被写入

如果你需要把群聊增量事件写入 `【Aime日志】` 与 `【任务库】`，请在 `heartbeat-inspector` 中启用双轨写入：

```bash
cd user_skills/heartbeat-inspector
python3 scripts/run_inspector.py \
  --heartbeat "HEARTBEAT.md" \
  --state ".heartbeat_state.json" \
  --dlq ".heartbeat_dlq.jsonl" \
  --dual-write-spreadsheet "<飞书表格URL或token>" \
  --dual-write-log-sheet-title "Aime日志" \
  --dual-write-task-sheet-title "任务库"
```

### 2）每日对账巡查（读取任务库，产出告警词典）

```bash
cd user_skills/task-flow-engine
python3 scripts/task_patrol.py \
  --spreadsheet "<飞书表格URL或token>" \
  --task-sheet-title "任务库" \
  --roster-sheet-title "团队名单" \
  --broadcast-usage "task_patrol_broadcast" \
  --group-card-max-items-per-group 3 \
  --state-file ".patrol_state.json"
```

- `--roster-sheet-title`：用于从同一份 Spreadsheet 内读取花名册（`中文名称` → `Open ID` / `邮箱`）。
- `--broadcast-usage`：从工作区根目录 `CHAT_REGISTRY.json` 读取群用途，真实 `chat_id` 只能来自 Chat Registry；旧参数 `--target-chat` 仅作为一致性断言。
- `--group-card-max-items-per-group`：广播卡片采用“先人后事”聚合时，每位负责人在每个类别下最多展开几项任务；超出部分会折叠为“等 X 项”。
- `--group-card-only-changed`：仅展示相对昨日新增/变化的异常（默认关闭）。

输出 JSON 中关键字段：
- `summary.task_counts`：**任务全量状态汇总**（开启 x 个、完成 y 个、暂停 z 个），供日报生成使用
- `grouped_results`：按类别分组后的明细
- `routes.p2p`：**Bot 私聊分发包**（覆盖全部 findings，按负责人聚合）
- `routes.private`：阶段一（<=2 天）私聊催办分包（按负责人路由，兼容原两阶段策略）
- `routes.group`：阶段二（>=3 天异常或 >2 天超期）群聊公开提醒分包
- `routes.group_broadcast`：固定广播群 `oc_b566689fc5704ba70cc0f43fc32f0cc4` 的群卡片分包，卡片正文采用“先人后事”聚合
- `routes.unmapped`：无法映射负责人（或负责人为空）的兜底桶（含 message 便于直发）
- `routes.admin`：格式异常 / 缺负责人等兜底信息（建议私聊发给管理员）
- `vacation`：休假免打扰拦截结果（法定休息日静默顺延 / 个人休假静默顺延）
- `state`：状态缓存文件信息（用于连续异常天数升级）
- `card_state`：广播卡片快照信息（用于“仅展示昨日新增/变化异常”）

---

### 3）飞书 Bot 群广播 + 私聊分发 + 通知日志（Notification Log）

**硬规则（新增）：**
- 真实群播（committed send）**只能**通过 `scripts/run_daily_pipeline.py` 发起；禁止特工把 `run_task_patrol_save.py` + `task_patrol_notify.py` 拆成可重放的 committed 链路。
- `task_patrol_notify.py` 仅用于 dry-run / 管理员预览 / 本地排查；若检测到 committed group broadcast 成功，同一逻辑主题不允许再次执行 committed send。
- 若私聊链路失败，但群播已经成功，发送器默认返回 0 并写入通知日志，避免上层特工误判为“整条链路失败”后重放 committed send。

建议两段式执行仅用于**演练和排查**：先生成 alerts.json，再做 dry-run / 管理员预览，避免 stdout 截断，便于复盘；**不要**把“两段式”当成 committed 群播的正式入口。

```bash
cd user_skills/task-flow-engine
python3 scripts/run_task_patrol_save.py \
  --spreadsheet "<飞书表格URL或token>" \
  --task-sheet-title "任务库" \
  --roster-sheet-title "团队名单" \
  --broadcast-usage "task_patrol_broadcast" \
  --group-card-max-items-per-group 3 \
  --state-file ".patrol_state.json" \
  --output alerts.json

# 默认 dry-run：生成群广播卡片 + 逐人私聊卡片 payload，并写通知日志，不真实发送
python3 scripts/task_patrol_notify.py \
  --alerts-file alerts.json \
  --admin-email yuqinan@bytedance.com \
  --enable-private-chat

# 管理员预览：只私聊给管理员，不发群
python3 scripts/task_patrol_notify.py \
  --alerts-file alerts.json \
  --admin-email yuqinan@bytedance.com \
  --send-to-admin-only

# 真实群播：统一走单一入口，禁止手工拆解 committed send
python3 scripts/run_daily_pipeline.py \
  --task-spreadsheet "<飞书表格URL或token>" \
  --log-spreadsheet "<通知日志表URL或token>" \
  --task-sheet-title "任务库" \
  --roster-sheet-title "团队名单" \
  --broadcast-usage "task_patrol_broadcast" \
  --admin-email yuqinan@bytedance.com \
  --commit-group-broadcast \
  --confirm-group-broadcast CONFIRM_GROUP_BROADCAST
```

- 群广播目标从工作区根目录 `CHAT_REGISTRY.json` 的用途 `task_patrol_broadcast` 读取；历史 hardcode 的 `oc_b566689fc5704ba70cc0f43fc32f0cc4` 已迁入注册表。
- `task_patrol_notify.py` 默认 dry-run；真实群播必须通过 `scripts/run_daily_pipeline.py` 透传 `--commit-group-broadcast --confirm-group-broadcast CONFIRM_GROUP_BROADCAST`。
- TaskFlow L1 入库回执请改用 `scripts/taskflow_thread_reply.py`，不要再使用临时脚本直接裸调 `lark_im_send_message`。该发送器会基于 `source_message_id` 做幂等防重，并同步写入 `notification_logs/taskflow_ack_<UTC日期>.jsonl` 与 `.aime/log/sent_cards/SENT_CARDS.jsonl`。
- 真实群播前会调用飞书群元信息 pre-flight，并校验 Registry 中配置的 `expected_name_keywords`；群名不匹配或查不到群时直接熔断并写入 Notification Log。
- 开启 `--enable-private-chat` 后，发送器会优先读取 `routes.p2p`（覆盖负责人名下全部异常）；若不存在，则回退到 `routes.private`。
- 私聊接收者优先使用 `open_id`（仅当底层发送脚本支持时）；当前默认回退为 `email`，若两者都不可用则跳过并记录原因。
- 发送器默认把 Notification Log 记录到：`notification_logs/notify_<UTC日期>.jsonl`（JSONL，每次群/私聊尝试各追加一条记录）
- 同时会把每次发送的卡片 payload 落盘到：`notification_payloads/<run_id>/`（便于复盘；已禁止把 committed 群播当作可重放动作）

---

## Chat Registry 迁移步骤

### 迁移已有 hardcode `oc_b566...`

1. 打开工作区根目录 `CHAT_REGISTRY.json`，确认已有用途 `task_patrol_broadcast`。
2. 将历史 hardcode 的 `oc_b566689fc5704ba70cc0f43fc32f0cc4` 写入该用途的 `chat_id`，并补齐 `name`、`lookup_query`、`expected_name_keywords`。
3. 把脚本和定时任务里的 `--target-chat oc_b566...` 改为 `--broadcast-usage task_patrol_broadcast`；如短期兼容必须保留 `--target-chat`，它只会作为断言，值不一致会熔断。
4. 先运行 `python3 scripts/task_patrol_notify.py --alerts-file alerts.json --dry-run` 生成 payload 和日志。
5. 管理员确认后，**只能**运行 `python3 scripts/run_daily_pipeline.py --task-spreadsheet <任务表URL或token> --log-spreadsheet <通知日志表URL或token> --commit-group-broadcast --confirm-group-broadcast CONFIRM_GROUP_BROADCAST` 发起真实群播；发送前会自动拉取群元信息并校验群名关键字，且 committed send 成功后不允许对同一逻辑主题重放。

### 新增一个群用途

1. 在工作区根目录 `CHAT_REGISTRY.json` 的 `chats` 下新增用途 key，例如 `weekly_review_broadcast`。
2. 填写 `chat_id`、可读 `name`、用于搜索群元信息的 `lookup_query`、以及必须出现在真实群名中的 `expected_name_keywords`。
3. 调用巡检或发送脚本时使用 `--broadcast-usage weekly_review_broadcast`。
4. 第一次必须 dry-run 或 `--send-to-admin-only`，确认 payload、日志和群名关键字都正确后，才使用二次确认口令真实群播。

---

## 脚本说明

### A. `scripts/task_patrol.py`

- 输入：读取 `【任务库】` 全表（默认最多 200 行）
- 输出：告警词典 JSON（包含默认分流策略）

---

## 目录结构

```
user_skills/task-flow-engine/
  README.md
  scripts/
    task_patrol.py
    run_task_patrol_save.py
    task_patrol_notify.py
  task_flow_engine/
    __init__.py
    lark_sheets_cli.py
    patrol.py
    vacation.py
```

---

## 鉴权说明（重要）

这些脚本调用的是仓库内置的 `lark-sheets-cli`。

- 若你的运行环境需要 `bytedcli` 鉴权，请先确保鉴权链路可用，再执行脚本。
- 本仓库脚本本身不会自动帮你修复鉴权环境（避免脚本内做“越权兜底”）。
