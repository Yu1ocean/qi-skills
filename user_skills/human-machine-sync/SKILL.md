---
name: human-machine-sync
description: 以本地 Markdown/YAML 为单一真相源（SSOT），对飞书表格执行字段级对账、差异报告与单向同步写入。适用于本地账本 ↔ 飞书镜像台账、配置清单、Decision Registry、技能目录等双轨资产的 audit / sync / patrol 场景。
author: 于奇楠
metadata:
  version: 0.1
---

version: 1.3
# human-machine-sync

## Common Rationalizations（常见借口库）

- “本地和飞书差不多，我先默认没漂移。”
- “MCP 一时不可用，我先静默跳过，等下次再说。”
- “表里少一两列无所谓，我顺手帮它补上就行。”
- “updated 太多了，先全表覆盖最省事。”
- “主键重复应该只是脏数据，我挑一条继续写。”

## Red Flags（危险信号）

- 未先解析本地文件、未校验主键唯一性，就直接读取/写入飞书。
- `field_mapping` 未覆盖 `primary_key`，却继续做 diff。
- 飞书目标不是 sheet，或者 sheet 缺少指定列，却仍继续执行同步。
- 遇到 MCP / lark-cli 失败，没有输出 `⚠️[SYNC_BLOCKED: MCP_UNAVAILABLE]` 就继续跑。
- 把 `sync` 实现成整表覆盖、批量清空或删除 orphan 行。
- 声称“写入成功”，但没有 RAW 回捞校验结果。

## Verification（强制验收清单）

宣称本技能执行完成时，必须同时满足：

1. 本地文件已成功解析为记录列表，且 `primary_key` 唯一。
2. 飞书链接已解析为真实 spreadsheet token，且目标对象确认为 sheet。
3. 已按 `primary_key` 完成字段级分类：`new / updated / orphan / ok`。
4. `audit` 模式不产生任何远端写入。
5. `sync / patrol` 模式仅执行单行覆盖或单行新增，禁止全表覆盖。
6. 每次写入后均执行 RAW 回捞，读回内容与预期一致；不一致即熔断。
7. MCP 不可用时立即输出 `⚠️[SYNC_BLOCKED: MCP_UNAVAILABLE]`，不得静默跳过。
8. 飞书有、本地没有的 orphan 行只告警，不自动删除。

---

## 📌 技能简介

把“本地 Markdown/YAML 文件”当作机器侧 SSOT，把“飞书表格”当作人类侧镜像台账，执行**字段级对账 + 单向同步**。

核心能力：

- 解析 **纯 YAML** 或 **含 YAML 代码块的 Markdown**。
- 读取飞书 sheet，自动选择与 `field_mapping` 最匹配的工作表。
- 按主键输出 `new / updated / orphan / ok` 四类 diff。
- 在 `sync / patrol` 模式下，仅对 `new + updated` 做**单行写入**。
- 写后执行 **RAW 回捞校验**，把“写成功”变成“读回一致”。

---

## 🔑 触发词

- 核心关键词：
  - 人机同步
  - 本地 SSOT
  - 飞书镜像台账
  - 字段级对账
  - drift audit
  - decision registry sync
- 典型指令示例：
  > 用本地文件和飞书表格做一次 audit，对账但不要写回
  > 以本地为准，把新增和更新项同步到飞书
  > 跑一轮 patrol，发现漂移就修复并输出日志

---

## ⚙️ 核心架构 / SOP / 约束条件

### 输入

- `local_path`：本地文件路径；支持两类输入
  - 纯 YAML（`.yaml` / `.yml`）
  - Markdown（`.md`）中使用 ```yaml / ```yml 代码块承载记录
- `feishu_sheet_url`：飞书电子表格 URL、spreadsheet token，或可解析到 sheet 的 wiki 链接
- `primary_key`：主键字段名，如 `id`
- `field_mapping`：本地字段 → 飞书列名映射字典；必须覆盖 `primary_key`
- `mode`：
  - `audit`：只对账，不写入
  - `sync`：把 `new + updated` 单向写入飞书
  - `patrol`：对账 + 自动修复；修复失败时尝试在预留状态列写入 `⚠️[DRIFT_DETECTED]`

### 执行流程

1. **读取本地文件**
   - 解析 YAML 记录块
   - 自动跳过主键中带 `YYYY / NNN / 示例` 等占位符的模板记录
   - 断言 `primary_key` 存在且唯一
2. **读取飞书表格**
   - 通过 `lark-cli` / MCP 解析 wiki 或 spreadsheet token
   - 自动匹配最符合 `field_mapping` 的工作表
3. **字段级对账**
   - 按 `primary_key` 生成 `new / updated / orphan / ok`
4. **模式分支**
   - `audit`：仅输出 diff 报告
   - `sync`：对 `new + updated` 做单行写入
   - `patrol`：同 `sync`，若写后校验失败，尝试把 `⚠️[DRIFT_DETECTED]` 写入 `同步状态 / sync_status / 巡检状态` 之一（若目标表存在该列）
5. **写后回捞校验**
   - 每次写入后等待 2 秒
   - 读回刚写行，逐字段比对
6. **输出同步日志**
   - 汇总统计、diff 列表、成功写入、失败写入

### 约束条件

- 所有飞书操作必须走 **MCP / lark-cli**，不得裸调 OpenAPI。
- 若任务需要私聊结果通知，禁止直接调用 `im_send.py send`、`feishu-im-send` 或 `lark-im +messages-send`；必须改走：`.ephemeral_pool/[TASK_ID]_[TOPIC_SLUG].post.json` → `centralized_transmitter.py preflight` → `centralized_transmitter.py send --caller-role=comm-agent`。
- 涉及群成员/群名单同步时，发送前必须先按 `CHAT_REGISTRY.json` 做群 preflight（chat_id + 群名关键字断言），禁止猜群或绕过断言。
- 主键唯一性强制校验；冲突时立即熔断。
- 本地为 SSOT：若本地与飞书冲突，`sync / patrol` 以本地值覆盖同主键行。
- orphan 行只报警，不删除。
- `sync / patrol` 只允许**单行覆盖/单行新增**，禁止全表覆盖。
- MCP 不可用时，必须立即输出：`⚠️[SYNC_BLOCKED: MCP_UNAVAILABLE]`。

### 边界条件

- 飞书表格不存在指定列 → 报错并提示人工创建，不自动新增列。
- 本地文件解析失败 → 报错退出，不写入飞书。
- Markdown 中若含“Schema 示例 / 模板占位记录”，会按主键占位符自动跳过，不计入真实 diff。
- wiki 链接若解析后不是 sheet → 报错退出。
- `field_mapping` 未包含 `primary_key` → 报错退出。
- 多个工作表与 `field_mapping` 命中分数并列 → 报错退出，请人工收窄目标表。

### 推荐执行方式

> 涉及飞书读取/写入时，必须通过 `bash` 工具执行，并设置 `include_secrets=true`。

```bash
cd user_skills/human-machine-sync

# 1) 只对账，不写入
python3 scripts/human_machine_sync.py \
  --local-path memory/topics/decision-registry.md \
  --feishu-sheet-url "https://bytedance.larkoffice.com/wiki/PnnDwYr13imUyVkVPshc46ICnVh" \
  --primary-key id \
  --field-mapping assets/decision_registry_field_mapping.json \
  --mode audit \
  --report-out output/decision_registry_audit.json

# 2) 单向同步写入
python3 scripts/human_machine_sync.py \
  --local-path path/to/local.md \
  --feishu-sheet-url "https://bytedance.larkoffice.com/sheets/xxxxx" \
  --primary-key id \
  --field-mapping path/to/mapping.json \
  --mode sync \
  --report-out output/sync_report.json

# 3) roster_sync / 成员名单同步（dry-run，含群 preflight + CT payload）
python3 scripts/human_machine_sync.py \
  --local-path path/to/local.md \
  --feishu-sheet-url "https://bytedance.larkoffice.com/sheets/xxxxx" \
  --primary-key id \
  --field-mapping path/to/mapping.json \
  --mode sync \
  --notify-receiver-id "yuqinan@bytedance.com" \
  --notify-task-id roster_sync_demo_20260620 \
  --notify-topic "团队名单同步完成 UK/EU/JP POP BD" \
  --notify-topic-slug team_list_sync \
  --notify-chat-usage task_patrol_broadcast \
  --notify-dry-run \
  --report-out output/roster_sync_dry_run.json
```

### Defaults（合规默认值）

- 默认同步方向：**本地 → 飞书**
- 默认对账粒度：`field_mapping` 中声明的字段
- 默认报告格式：JSON
- 默认写后回捞：开启
- 默认 orphan 处理：仅告警，不删除
- 默认 drift 标记列候选：`同步状态 / sync_status / 巡检状态`

### 产物清单

- [主执行脚本](scripts/human_machine_sync.py)：主执行入口
- [Decision Registry 映射样例](assets/decision_registry_field_mapping.json)：首批集成场景字段映射
- `CHANGELOG.md`：版本变更记录

---

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：
  ```text
  用 Decision Registry 跑一轮 audit，只对账不写入。
  ```
- 🤖 标准输出：
  ```text
  1. 解析 memory/topics/decision-registry.md 中的 YAML 记录块。
  2. 读取飞书 Decision Registry 台账，按 ID 对齐字段。
  3. 输出 new / updated / orphan / ok 统计与逐条 diff。
  4. 不执行任何写入。
  ```
