# Heartbeat 巡检提醒格式模板

updated_at: 2026-06-18

## 设计原则

1. **信息完整优先**：任何视觉强化都不能替代群聊名称、发送人、时间、消息原文摘要和直达链接。
2. **链接直达优先**：每条提醒必须提供群聊/消息跳转入口；底部必须保留任务台账 / 个人工作站链接。
3. **高优显影但不符号堆砌**：预算、DDL、审批、阻塞、逾期等高优关键词可用醒目前缀和加粗，但不把正文抽象成符号。
4. **一条提醒一个信息单元**：便于用户扫读、回查、转发和后续入库。

## 标准模板

```markdown
**🔔 Heartbeat 新增提醒｜{高优标签或普通提醒}**

**【群聊】** [{chat_name}]({jump_link})
**【发送人】** {sender}
**【时间】** {create_time}
**【摘要】** {message_summary}

{priority_note_optional}

**工作站链接**：[{ledger_title}]({ledger_url})
```

## 高优提醒识别

命中以下关键词时，`{高优标签或普通提醒}` 使用：`⚠️ 高优先级`。

- 预算、Budget、费用、金额、审批
- DDL、截止、今天、明天、下班前、逾期、超期
- 阻塞、卡住、风险、升级、escalate

`priority_note_optional` 示例：

```markdown
**⚠️ 高优原因**：命中「预算确认 / DDL」关键词，请优先处理；原文信息已完整保留。
```

## 示例预览

```markdown
**🔔 Heartbeat 新增提醒｜⚠️ 高优先级**

**【群聊】** [POP Fashion 项目推进群](https://applink.feishu.cn/client/chat/chatter/add_by_link?...)
**【发送人】** 张三
**【时间】** 2026-06-18 21:40
**【摘要】** @于奇楠 麻烦今天下班前确认 UK 直播预算口径，明早要进复盘材料。

**⚠️ 高优原因**：命中「预算 / 今天下班前」关键词，请优先处理；原文信息已完整保留。

**工作站链接**：[任务台账 / 个人工作站](https://bytedance.larkoffice.com/wiki/TnNYsLq9phIJwutJGwBl730ygjd)
```
