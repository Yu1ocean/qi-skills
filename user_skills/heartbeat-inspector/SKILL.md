---
name: heartbeat-inspector
description: 读取工作区根目录的 HEARTBEAT.md 作为巡检清单（支持群聊名称与全局@我模式），通过飞书 IM 与飞书表格等数据源抓取最新状态并与本地快照做增量对比（Diff）；对群聊增量执行结构化提取（chat_task 等），并可选将增量事件双轨写入任务台账（Aime日志 + 任务库）。适用于日常信息巡检、避免漏看群消息/表格变更、增量任务落盘，以及异常兜底与可追溯归档。
metadata:
  version: 2.3.0
  updated_at: "2026-05-04"
---

# Heartbeat Inspector

## Common Rationalizations（常见借口库）

- “先把告警结果输出，回头再补快照更新 / DLQ。”
- “这次拉不到数据（403/超时），我就多试几次直到成功。”
- “配置文件格式不规范也没关系，我猜一下用户想要什么。”

## Red Flags（危险信号）

- 未读到 `HEARTBEAT.md` 就继续执行巡检。
- 获取飞书数据失败后进入无限重试。
- 未做 Diff 就把全量数据当成“新增”告警。
- 产生副作用（写快照 / 写 DLQ / 写任务台账）之前没有做输入结构校验与路径断言。
- 仅凭群聊名称匹配到多个群时“随便挑一个继续跑”。（必须熔断到 DLQ）

## Verification（强制验收清单）

- `scripts/run_inspector.py` 在以下场景下行为符合预期：
  - 有增量：输出告警（一行一条，便于原子化发送）+ 覆盖写入 `.heartbeat_state.json`。
  - 无增量：默认静默（不输出告警）。
  - 403/超时/命令缺失/群名歧义：写入 `.heartbeat_dlq.jsonl`，且不无限重试。
- 快照 / DLQ 只写在工作区根目录（防止误写到其他路径）。

---

## 📌 技能简介

按 `HEARTBEAT.md` 定义的清单执行信息巡检：

拉取最新状态 → 与本地快照做 Diff → 仅对新增内容产生告警 →（可选）结构化提取任务并双轨写入任务台账 → 写入快照与 DLQ。

### 更新日志（Changelog）

#### 2026-05-04

- **内置双轨写入**：将“双轨写入（dual_write）”从 `task-flow-engine` 迁移到 `heartbeat-inspector`，在 `run_inspector.py` 完成 JSON 事件提取后可直接落盘写入 `【Aime日志】` 与 `【任务库】`。

#### 2026-05-01

- **群聊任务提取 v2.0**：对新增群聊消息执行 LLM 结构化抽取，输出 JSON（支持【】锚点高优识别：若原文含【任务名】则最高优判定为任务并直接继承原话；否则按规范兜底提炼并补齐【】；原文 100% 保真；负责人穷尽提取；缺失信息自动生成 `suggestion_reply`）。
- **人机协同 v2.2**：新增三条协同护栏：
  - **Ack-Lock**：若未在时间窗口内检测到责任人认领（收到/1/OK/表情等），在任务结构中标记 `[⚠️待接单/未响应]`。
  - **State-Triggers**：识别 `/done`、`/阻塞`、`/延期至xxx` 等魔法词，输出 `task_status_update` JSON 行。
  - **Relative Time Anchoring**：基于消息 `create_time` 将“下班前/明早”等翻译为绝对时间（`YYYY-MM-DD HH:MM`）；无法锚定则触发 `suggestion_reply`。
- **取消 140 字截断**：群聊增量输出从“截断告警文案”升级为“结构化 JSON 行”，字段 `text` 为完整原文（换行以 `\n` 保留）。

#### 2026-04-30

- 支持 **直接使用群聊名称**（`chat_name` / `巡检群：xxx`）。
- 支持 **全局群聊只看 @ 我** 的增量信息（`feishu_mentions_global` / `模式：全局群聊只看@我的消息`）。

## 🔑 触发词

- 核心关键词：
  - heartbeat
  - 巡检
  - 信息巡检
  - 未读消息
  - 增量对比 / diff
  - @我 / 提及
  - 双轨写入 / 落盘 / 写任务库
- 典型指令示例：
  > 按 HEARTBEAT.md 巡检一下，有新增就告诉我
  > 开启全局@我巡检模式
  > 巡检后把 chat_task 写入任务台账（Aime日志 + 任务库）

## ⚙️ 核心架构 / SOP / 约束条件

### 输入与文件约定（合规默认值 / L2）

- 配置文件：工作区根目录 `HEARTBEAT.md`（默认）
- 快照文件：工作区根目录 `.heartbeat_state.json`（默认）
- 死信队列：工作区根目录 `.heartbeat_dlq.jsonl`（默认）
- 默认抓取窗口：`relative_time=last_24_hours`（用于飞书消息抓取）
- 默认抓取条数：`page_size=50`
- 默认行为：**无增量静默退出**（不打扰用户）

### 运行流程（SOP）

1. **加载配置**：读取 `HEARTBEAT.md`（支持 JSON 代码块 + 简写列表），详见 `references/heartbeat_md_spec.md`。
2. **鉴权准备**：尝试执行 `inner_skills/bytedcli-auth/scripts/bytedcli_auth.sh`。
   - 若环境缺少 bytedcli 或鉴权失败：记录进 DLQ，不允许无限重试。
3. **定向数据抓取**：
   - 飞书群聊：
     - 若配置中提供 `chat_id`：直接拉取消息。
     - 若只提供 `chat_name`（群名）：先按名称搜索群聊解析 `chat_id`，再拉取消息。
   - 全局@我：跨群聊筛选“明确 @ 当前用户”的消息，降低噪音。
   - 飞书表格：执行 `inner_skills/lark/mcp_lark_lark_download.py` 下载为 xlsx 并解析指定 range。
4. **增量对比（Diff Engine）**：
   - 只输出“纯增量 / 新消息 / 新卡点”。
   - 禁止把全量当增量。
5. **群聊任务提取（LLM / v2.0）**（仅对群聊相关 target 生效）：
   - 对 `feishu_chat` / `feishu_mentions_global` 的增量消息调用 `scripts/chat_task_extractor.py` 进行结构化抽取。
   - 输出为 **JSON 行**（一行一个 JSON，便于上层原子化发送/入库/去重）。主要类型：
     - `chat_message_new`：群聊新增消息（字段 `text` 为完整原文）
     - `mention_message_new`：全局@我新增消息（字段 `text` 为完整原文）
     - `chat_task`：识别出的任务（字段 `task.task_name` 强制为 `【动词+事项+时间节点】`；若缺失关键信息则包含 `task.suggestion_reply`）
     - `task_status_update`：识别出的状态更新（如 /done /延期 等）
6. **双轨落盘（可选）**：当运行参数提供 `--dual-write-spreadsheet` 时，内部调用 `scripts/dual_write.py` 的核心逻辑，将 JSON 事件写入：
   - `【Aime日志】`：全量审计
   - `【任务库】`：仅 chat_task
7. **智能触达**：
   - 有增量：输出 JSON 行；上层调用方按行原子化发送即可。
   - 无增量：静默退出（可用 `--verbose` 输出日志）。
8. **异常兜底**：403/超时/命令缺失/群名歧义/LLM 抽取失败等异常写入 DLQ（`.heartbeat_dlq.jsonl`），单次运行每个 target 最多重试 1 次，严禁死循环。

### 三层防御护栏（CDA / L1+L2+L3）

- **L1 认知层**：本 SKILL.md 顶部的 Common Rationalizations / Red Flags / Verification。
- **L2 默认层**：默认路径（HEARTBEAT.md / 快照 / DLQ）、默认拉取窗口与条数、默认“无增量静默”。
- **L3 断言层**：脚本中所有副作用发生前都执行 `validate_*()` / `assert_*()`：
  - 校验配置 schema（必须有 version/targets；每个 target 必须有 id/type）。
  - 校验文件路径必须位于工作区根目录（防误写）。
  - 群名解析出现多结果：写入 DLQ 并跳过该 target（不允许猜）。

### 推荐执行方式

```bash
# ⚠️ 必须用 bash 工具执行，且 include_secrets=true（飞书读取/写入需要 token）
cd user_skills/heartbeat-inspector

# 1) 纯巡检（默认不写入任务台账）
python3 scripts/run_inspector.py \
  --heartbeat "HEARTBEAT.md" \
  --state ".heartbeat_state.json" \
  --dlq ".heartbeat_dlq.jsonl"

# 2) 巡检 + 双轨写入（落盘到 Aime日志 + 任务库）
python3 scripts/run_inspector.py \
  --heartbeat "HEARTBEAT.md" \
  --state ".heartbeat_state.json" \
  --dlq ".heartbeat_dlq.jsonl" \
  --dual-write-spreadsheet "<飞书表格URL或token>" \
  --dual-write-log-sheet-title "Aime日志" \
  --dual-write-task-sheet-title "任务库"
```

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：
  ```text
  按 HEARTBEAT.md 巡检一下：只要有新增消息/新卡点就告诉我
  ```
- 🤖 标准输出（按行原子化）：
  ```text
  {"type":"chat_message_new",...}
  {"type":"chat_task",...}
  {"type":"task_status_update",...}
  ```
