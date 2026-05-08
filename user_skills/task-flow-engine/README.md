# Task Flow Engine（任务追踪与催办巡检）

本仓库提供一组面向飞书任务台账的“巡检 + 分发路由”脚本：

- 读取 `【任务库】`，计算 DDL 风险（临近到期 / 已超期 / 缺失 DDL / 格式异常）
- 从同一份 Spreadsheet 的 `【团队联系方式】` Sheet 读取花名册（中文名 → Open ID / 邮箱）
- 产出告警词典 JSON（包含：异常明细 + 两阶段路由：私聊催办 / 群聊公开提醒）
- 默认启用休假免打扰（法定休息日静默顺延 / 个人休假静默顺延）

> ✅ 边界说明：
> - “双轨写入（dual_write）”已迁移至 `heartbeat-inspector`。
> - 即：任务台账写入由 `heartbeat-inspector` 负责；本仓库只做**读取任务库的巡检与催办分流**。

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
  --target-chat "oc_xxx" \
  --state-file ".patrol_state.json" \
  > /tmp/daily_patrol_alerts.json
```

- `--roster-sheet-title`：用于从同一份 Spreadsheet 内读取花名册（`中文名称` → `Open ID` / `邮箱`）。
- `--target-chat`：仅用于阶段二公开提醒的目标群 **chat_id** 透传。

输出 JSON 中关键字段：

- `grouped_results`：按类别分组后的明细
- `routes.p2p`：**Bot 私聊分发包**（覆盖全部 findings，按负责人聚合）
- `routes.private`：阶段一（<=2 天）私聊催办分包（按负责人路由，兼容原两阶段策略）
- `routes.group`：阶段二（>=3 天异常或 >2 天超期）群聊公开提醒分包
- `routes.unmapped`：无法映射负责人（或负责人为空）的兜底桶（含 message 便于直发）
- `routes.admin`：格式异常 / 缺负责人等兜底信息（建议私聊发给管理员）
- `vacation`：休假免打扰拦截结果（法定休息日静默顺延 / 个人休假静默顺延）
- `state`：状态缓存文件信息（用于连续异常天数升级）

---

### 3）飞书 Bot 私聊分发（P2P）+ 通知日志（Notification Log）

建议两段式执行：**先生成 alerts.json，再做发送**，避免 stdout 截断，且便于重放。

```bash
cd user_skills/task-flow-engine
python3 scripts/run_task_patrol_save.py \
  --spreadsheet "<飞书表格URL或token>" \
  --task-sheet-title "任务库" \
  --roster-sheet-title "团队名单" \
  --state-file ".patrol_state.json" \
  --output alerts.json

# 先演练：只把“将要发给每个人的内容”汇总私聊发给管理员，不触达其他人
python3 scripts/task_patrol_notify.py \
  --alerts-file alerts.json \
  --admin-email yuqinan@bytedance.com \
  --send-to-admin-only

# 确认无误后再全量发送（逐人 P2P + 管理员兜底）
python3 scripts/task_patrol_notify.py \
  --alerts-file alerts.json \
  --admin-email yuqinan@bytedance.com
```

- 发送器默认把 Notification Log 记录到：`notification_logs/notify_<UTC日期>.jsonl`（JSONL，每次发送一条记录）
- 同时会把每次发送的 post payload 落盘到：`notification_payloads/<run_id>/`（便于复盘/重放）

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
