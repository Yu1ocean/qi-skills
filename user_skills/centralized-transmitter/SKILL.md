---
name: centralized-transmitter
description: 统一封装飞书消息发射的中枢网关，支持卡片创建、消息发送、资源上传与 webhook 发信，并内置 .ephemeral_pool 路径校验、Task ID 匹配、主题断言和统一发射权熔断。适用于主进程统一发信、专职通信特工投递正式卡片、隔离发送链路治理或防止业务子特工越权发信的场景。
author: Aime
---

version: 1.2
# 统一发射器（centralized-transmitter）

本技能提供统一、可审计、可熔断的飞书发信网关。

## 权限声明

**此为中枢统一发射网关，仅允许 Aime 主进程或专职通信特工调用，严禁业务子特工越权调用。**

## Common Rationalizations（常见借口）

- “先直接发，回头再补 `.ephemeral_pool/` 命名。”
- “这个 card_id 看起来能用，我就不校验来源回执了。”
- “payload 里没带主题摘要也没关系，先发出去再说。”
- “业务子特工顺手发一下更快，不必走统一发射器。”
- “Task ID 只是参考字段，文件名不一致也能凑合。”

## Red Flags（危险信号）

- payload 不在 `.ephemeral_pool/` 下。
- payload 仍使用 `card.json` / `post.json` / `payload.json` 等静态文件名。
- payload 文件名不包含当前 `task_id`。
- payload 内部 `task_id` / `taskId` / `run_id` 与本轮任务不匹配。
- payload 标题、摘要、正文都未命中当前主题关键词。
- 调用方没有显式声明 `--caller-role=main|comm-agent`。
- 交互式卡片发送未找到由本技能创建的 card receipt。

## Verification（强制验收清单）

1. **调用权验证**：调用前必须带 `--caller-role=main|comm-agent`，否则立即熔断。
2. **路径验证**：payload 必须是 `.ephemeral_pool/` 下的真实文件路径，禁止内联 JSON。
3. **文件名验证**：payload 文件名必须包含当前 `task_id`，且不得使用静态文件名。
4. **Task ID 验证**：若 payload 内部包含 `task_id` / `taskId` / `run_id`，必须与当前任务一致。
5. **主题断言**：payload 标题/摘要/正文提取出的文本必须命中当前 `--topic`。
6. **卡片回执验证**：`create_card` 成功后必须在 `.ephemeral_pool/` 写入回执；后续 `send interactive` 只能发送带回执的 `card_id`。
7. **业务失败探测**：飞书接口返回 `code/status/error` 异常时必须退出非 0，禁止伪 ACK。

## Defaults（合规默认值）

- 调用者角色：无默认值，必须显式声明 `main` 或 `comm-agent`
- payload 目录：`.ephemeral_pool/`
- 交互式卡片回执：`[TASK_ID]_<card_id>.card.receipt.json`
- 允许的发信载荷后缀：
  - 卡片：`.card.json`
  - 富文本：`.post.json`
  - 其他消息：`.payload.json`
- 执行方式：通过 `bash` 直接运行脚本；如需真实发信或上传，必须设置 `include_secrets=true`

## 核心工作流

### 1. 创建卡片实体

对卡片 payload 先做零信任校验，再创建卡片实体，并把 `card_id` 回执写入 `.ephemeral_pool/`。

```bash
cd <skill-root> && python3 scripts/centralized_transmitter.py create_card "/workspace/.../.ephemeral_pool/[task_123]_topic.card.json" --task-id=task_123 --topic="统一发射器上线通知" --caller-role=main
```

### 2. 发送交互式卡片

发送 `interactive` 时只接受 `card_id`，并强制读取本技能在上一步生成的回执文件，确认 `card_id ↔ task_id ↔ topic` 三者一致后再发送。

```bash
cd <skill-root> && python3 scripts/centralized_transmitter.py send "yuqinan@bytedance.com" interactive 7371713483664506900 --id-type=email --task-id=task_123 --topic="统一发射器上线通知" --caller-role=comm-agent
```

### 3. 发送 post / file / audio / share_chat

非 `interactive` 消息一律要求传 payload 文件路径，由脚本完成路径校验、Task ID 校验与主题断言。

```bash
cd <skill-root> && python3 scripts/centralized_transmitter.py send "yuqinan@bytedance.com" post "/workspace/.../.ephemeral_pool/[task_123]_topic.post.json" --id-type=email --task-id=task_123 --topic="统一发射器上线通知" --caller-role=comm-agent
```

### 4. 上传资源

上传图片/文件前仍需走角色验证；该命令不涉及 payload 主题断言。

```bash
cd <skill-root> && python3 scripts/centralized_transmitter.py upload "/workspace/path/to/file.png" image --caller-role=comm-agent
```

### 5. Webhook 发卡

Webhook 发卡同样要求卡片 payload 位于 `.ephemeral_pool/`，并通过 Task ID 与主题断言。

```bash
cd <skill-root> && python3 scripts/centralized_transmitter.py webhook "https://open.feishu.cn/xxx" "/workspace/.../.ephemeral_pool/[task_123]_topic.card.json" --task-id=task_123 --topic="统一发射器上线通知" --caller-role=main
```

### 6. 预检（推荐在主进程编排阶段先跑）

只做本地校验，不触发真实发信。适合在发射前先做物理熔断检查。

```bash
cd <skill-root> && python3 scripts/centralized_transmitter.py preflight "/workspace/.../.ephemeral_pool/[task_123]_topic.post.json" --task-id=task_123 --topic="统一发射器上线通知" --caller-role=main
```

## 资源说明

- `scripts/centralized_transmitter.py`：统一发射主入口，封装 create_card / send / upload / webhook / preflight。
- `scripts/_payload_guard.py`：零信任护栏，负责角色验证、路径校验、Task ID 校验与主题断言。

## 关键约束

- 不要在脚本外部绕过回执机制直接复用历史 `card_id`。
- 不要把业务 payload 放到根目录或静态文件名下。
- 不要省略 `--task-id`、`--topic`、`--caller-role`。
- 不要把“主进程统一发射权”下放给业务子特工。
- 遇到 guardrail 报错时，先修 payload 和任务上下文，不要改成直接裸发。
- **v1.2 新增兼容桥**：当 `.post.json` 命中“旧版差旅大盘摘要 payload”（仅含 `title/summary/content`，不符合飞书 `post` 官方 schema）时，发送阶段会自动物化同 task_id 的 `.card.json`、创建 card receipt，并改走 `interactive` 发射，避免 `230001 invalid message content` 再次出现。

## 来源说明

本技能的发信主能力基于既有飞书发信链路在 **2026-06-06** 完成了本地自包含迁移，并新增以下中枢级护栏：

1. `.ephemeral_pool/` 物理隔离强校验
2. `task_id` 文件名与 payload 元数据双重比对
3. 主题断言熔断
4. `card_id` 回执绑定与二次发送校验
5. 调用者角色强约束（仅主进程 / 通信特工）

## 测试建议

- 先用 `preflight` 验证 payload，再执行真实发信。
- 真实发信、上传资源、Webhook 调用时，必须通过 `bash` 直接执行，并设置 `include_secrets=true`。
- 若只需检查脚本可用性，可执行 `python3 scripts/centralized_transmitter.py preflight ...` 作为本地验证。
