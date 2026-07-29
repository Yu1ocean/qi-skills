# HEARTBEAT.md 配置规范（Heartbeat Inspector）

Heartbeat Inspector 默认从工作区根目录读取 `HEARTBEAT.md`。

本配置支持两种写法：

- **推荐：JSON 代码块（稳定、可扩展）**
- **简写：面向人类的 Markdown 列表（更好写，但能力更有限）**

---

## A. 推荐写法：JSON 代码块（推荐）

在 `HEARTBEAT.md` 中放置一个 fenced code block：

```json
{
  "version": 1,
  "targets": [
    {
      "id": "chat_project",
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
    },
    {
      "id": "sheet_metrics",
      "type": "lark_sheet_range",
      "title": "指标表",
      "document_url": "https://bytedance.larkoffice.com/sheets/xxxxx",
      "sheet_name": "Sheet1",
      "range": "A1:Z200"
    }
  ]
}
```

### 字段说明

- `version`：整数，当前只支持 `1`。
- `targets`：数组，至少 1 项。

### target（通用字段）

- `id`：字符串，稳定唯一（用于快照 key）。建议手工填。
- `type`：字符串，当前支持：
  - `feishu_chat`：飞书群聊消息巡检
  - `feishu_mentions_global`：全局群聊，仅巡检“@我”的消息
  - `lark_sheet_range`：飞书表格范围巡检
- `title`：可选，展示名称。

### feishu_chat

- `chat_id`：可选，形如 `oc_...`。
- `chat_name`：可选，群聊名称（**支持直接写群名**）。
- `relative_time`：可选，默认 `last_6_hours`。
- `page_size`：可选，默认 `50`，范围建议 1-50。

> 备注：若只提供 `chat_name`，脚本会先按名称搜索群聊解析 `chat_id`。

### feishu_mentions_global

- `relative_time`：可选，默认 `last_6_hours`。
- `page_size`：可选，默认 `50`。

> 备注：该模式会在全局范围筛选“明确 @ 当前用户”的群聊消息，减少噪音。

### lark_sheet_range

- `document_url`：必填，飞书表格链接（/sheets/ 或 /sheet/）。
- `sheet_name`：必填，工作表名称。
- `range`：必填，Excel A1 范围，如 `A1:Z200`。

---

## B. 简写写法：Markdown 列表（可选）

当不想写 JSON 时，可以使用简写。脚本会从文本中识别关键行。

示例：

```md
# 我的巡检清单

- 巡检群：项目A沟通群
- 巡检群：项目B沟通群
- 模式：全局群聊只看@我的消息
```

规则说明：

- `巡检群：xxx` 会自动生成一个 `feishu_chat` target，并使用 `chat_name=xxx`。
- `模式：全局群聊只看@我的消息` 会生成一个 `feishu_mentions_global` target。

---

## 常见错误

- 没有 json 代码块，且简写也无法解析：脚本会报错并提示修复。
- `id` 重复：会导致快照覆盖，脚本会强断言阻止。
- `chat_name` 命中多个群聊且无法判断：脚本会把该条写入 DLQ，并跳过该 target（避免误巡检）。
