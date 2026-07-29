# HEARTBEAT (Advanced)

```json
{
  "version": 1,
  "targets": [
    {
      "id": "mentions_global_aime_qinan",
      "type": "feishu_mentions_global",
      "title": "全局群聊 @Aime / @于奇楠",
      "relative_time": "last_6_hours",
      "page_size": 50,
      "watch_mentions": [
        "Aime",
        "于奇楠",
        "yuqinan@bytedance.com"
      ]
    }
  ]
}
```

- 逻辑：抓取上述对象被提及（Mentioned）或指定群聊（feishu_chat）的增量消息，并进行巡检与同步。
