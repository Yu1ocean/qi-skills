# 邮件记录器输出契约 V1.0

## 目标

为差旅大屏复核提供一份**全量邮件底账**，把“邮件原始证据”与“分类结果”沉淀为可复用 JSON，供后续审核技能拿来对比两条技能产出。

## JSON 结构

```json
{
  "version": "1.0",
  "generated_at": "2026-06-08 00:50:00",
  "mailbox": "me",
  "filters": {
    "months": 3,
    "max_messages": 200,
    "start_time": "",
    "end_time": "",
    "folders": ["INBOX"],
    "excluded_folders": ["SENT", "DRAFT", "SCHEDULED", "TRASH", "SPAM"],
    "scope_note": "当前版本默认扫 INBOX；如后续补齐 folder read scope，可升级为多文件夹全量 sweep。"
  },
  "summary": {
    "total_messages": 200,
    "travel_related_messages": 18,
    "non_travel_messages": 182,
    "categories": {
      "tiktok_notification": 120,
      "travel_booking": 10,
      "travel_approval": 8
    },
    "folders": {
      "INBOX": 200
    },
    "top_senders": [
      {"sender": "notification@service.tiktok.com", "count": 120}
    ]
  },
  "messages": [
    {
      "message_id": "xxx",
      "thread_id": "xxx",
      "folder": "INBOX",
      "subject": "【差旅】于奇楠预订了机票",
      "sender": "员工商旅系统(请勿回复)",
      "sender_email": "noreply@example.com",
      "sent_at": "2026-06-07",
      "labels": ["UNREAD", "IMPORTANT"],
      "primary_category": "travel_booking",
      "secondary_categories": ["finance_expense"],
      "category_scores": {"travel_booking": 8, "finance_expense": 2},
      "classification_evidence": ["travel_parser:booking", "kw:【差旅】"],
      "is_travel_related": true,
      "travel_channel": "booking",
      "travel_record_count": 1,
      "travel_people": ["于奇楠"],
      "travel_routes": ["上海->London"],
      "security_level": "",
      "raw_excerpt": "..."
    }
  ]
}
```

## 分类口径

### 一级分类
- `travel_booking`
- `travel_approval`
- `travel_other`
- `finance_expense`
- `calendar_invite`
- `workspace_collaboration`
- `tiktok_notification`
- `system_alert`
- `hr_admin`
- `marketing_subscription`
- `general_other`

### 差旅识别规则
1. 优先复用 `build_travel_dashboard.py` 里的差旅解析器做真识别。
2. 如果能抽出差旅行程，则直接打成 `travel_booking` 或 `travel_approval`。
3. 如果只命中差旅关键词、但抽不出结构化行程，则降级为 `travel_other`。

## 审核 Skill 建议对账字段

后续复核两条技能产出时，至少对比这几组字段：

1. **覆盖率**
   - `summary.total_messages`
   - `summary.travel_related_messages`

2. **邮件证据命中**
   - `messages[].message_id`
   - `messages[].thread_id`
   - `messages[].primary_category`

3. **差旅抽取映射**
   - `messages[].travel_record_count`
   - `messages[].travel_people`
   - `messages[].travel_routes`

4. **分类稳定性**
   - `messages[].category_scores`
   - `messages[].classification_evidence`

## 当前已知边界

1. 当前环境缺少 `mail:user_mailbox.folder:read` scope，暂时不能自动枚举所有自定义文件夹。
2. 因此 V1 默认扫 `INBOX`，后续若 scope 开通，再升级为 `INBOX + ARCHIVED + custom folders` 的全量 sweep。
3. 若某些邮件详情拉取失败，仍保留摘要级底账，不伪造正文。
