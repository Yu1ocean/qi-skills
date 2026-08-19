# 统一发射器技能说明

<figure view-type="Card"><source name="centralized-transmitter.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OGE0YzY2Mzg4OTUxNTE4MjE3MmIyNjA2MzhjZThkNWZfYWE0NGIyMmUxYjVmZThiMzZiZDQzNmI3OWYxZjU2ZGFfSUQ6NzY3NTYyODQ4MTYxMTM2OTQwNF8xNzg3MTIxNTI0OjE3ODcxMjUxMjRfVjM" mime="application/zip" size="19749" token="NkPwbfTPio7kwixXJN3cc2OjnDc"/></figure>

<figure view-type="Card"><source name="centralized-transmitter.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZDA3NGVhZmQxNTQ2MDllODgwMWVlYWU2OTI5NGExNGFfZjI3YTM3ZjhhOGQzMDUyOWI2Nzg2NzNmMTI1NjRlNWJfSUQ6NzY0ODEzMDM5MTM0NTQ5OTM4MV8xNzg3MTIxMDcwOjE3ODcxMjQ2NzBfVjM" mime="application/zip" size="10470" token="RvuJbzHeioYPjxx9ScSc5DwMnvb"/></figure>

## 📌 技能简介

`centralized-transmitter` 是统一发射器技能，用来承接正式飞书消息的中枢发信动作，避免业务子特工直接越权发信。

它把发卡、发 post、资源上传和 webhook 发信收口到同一条链路，并在发送前强制执行 `.ephemeral_pool/` 物理隔离、Task ID 匹配、主题断言与 card receipt 校验。

## 🔑 触发词

- 核心关键词：

  - 统一发射器
  - centralized-transmitter
  - 统一发射权
  - 主题断言
  - `.ephemeral_pool`
- 典型指令示例：

  > 把正式卡片改走统一发射器，不允许业务子特工直接发发信前先做 `.ephemeral_pool` 路径校验和 Task ID 匹配

<callout emoji="💡">
**核心结论：** 这个技能不是“帮忙发消息”的普通工具，而是**中枢统一发射网关**。它的首要职责是**拦截错误发信**，其次才是完成发信。
</callout>

## ⚙️ 核心架构 / SOP / 约束条件

### 能力边界

- 只允许 **Aime 主进程** 或 **专职通信特工** 调用。
- 业务子特工不得绕过本技能直接发送正式交付消息。
- 所有 payload 必须放在 `.ephemeral_pool/`，且文件名必须包含当前 `task_id`。

### 内置护栏

1. **调用权护栏**：必须显式声明 `--caller-role=main|comm-agent`。
2. **路径护栏**：payload 必须是 `.ephemeral_pool/` 下的真实文件，禁止内联 JSON。
3. **Task ID 护栏**：文件名必须命中当前 `task_id`；若 payload 内含 `task_id/taskId/run_id`，也必须一致。
4. **主题护栏**：标题、摘要或正文必须命中当前主任务主题，否则熔断。
5. **卡片回执护栏**：`create_card` 会落盘 receipt；`send interactive` 必须二次验证 receipt。

### 执行流程

1. 主进程生成 payload 到 `.ephemeral_pool/`
2. 先执行 `preflight` 进行本地熔断检查
3. 若为卡片：先 `create_card`，再以 receipt 绑定后的 `card_id` 执行 `send interactive`
4. 若为 post/file/audio/share_chat：直接走统一发送入口
5. 任一护栏失败即退出非 0，禁止伪 ACK

| 阶段 | 动作 | 硬约束 |
|-|-|-|
| Preflight | 校验 payload 路径、任务号、主题、调用者角色 | 失败即熔断，不允许进入真实发信 |
| Create Card | 创建卡片实体并落 receipt | receipt 必须与 task_id / topic 绑定 |
| Send | 发送 interactive 或 post 等消息 | interactive 必须验证 receipt；其他消息必须二次做 payload 断言 |

### 默认值

- payload 目录：`.ephemeral_pool/`
- receipt 后缀：`.card.receipt.json`
- 调用者角色：无默认值，必须显式声明
- 真实发信：必须以 `bash + include_secrets=true` 运行

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：

```Plain Text
把正式飞书卡片都收口到统一发射器，禁止业务子特工直接发送。

```

- 🤖 标准输出：

```Plain Text
1. 先把 card/post payload 落盘到 .ephemeral_pool/，文件名包含 task_id。
2. 主进程调用 centralized-transmitter preflight，先做本地熔断检查。
3. 对卡片先 create_card，再使用 receipt 绑定后的 card_id 执行 interactive send。
4. 若 payload 主题与当前任务不一致，立即熔断，不得真实发送。

```

<callout emoji="⭐">
**发布价值：** 统一发射器把“物理隔离、主题断言、统一发射权”从聊天约定升级成了可执行护栏，后续可以直接复用到所有正式飞书发信链路里。
</callout>