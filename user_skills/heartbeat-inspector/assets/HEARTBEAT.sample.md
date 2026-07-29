# HEARTBEAT.md（样例）

下面给出两种配置写法。

---

## 写法 A：推荐 JSON（功能最全）

```json
{
  "version": 1,
  "targets": [
    {
      "id": "chat_project_a",
      "type": "feishu_chat",
      "title": "项目A沟通群",
      "chat_name": "项目A沟通群",
      "relative_time": "last_6_hours",
      "page_size": 50
    },
    {
      "id": "mentions_me_global",
      "type": "feishu_mentions_global",
      "title": "全局@我",
      "relative_time": "last_6_hours",
      "page_size": 50
    }
  ]
}
```

---

## 写法 B：简写（更易写）

```md
- 巡检群：项目A沟通群
- 模式：全局群聊只看@我的消息
```
