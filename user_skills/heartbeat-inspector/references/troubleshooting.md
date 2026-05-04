# 故障与兜底（Heartbeat Inspector）

## 403 / 无权限

- 单次运行中不允许无限重试。
- 脚本会把错误写入 `.heartbeat_dlq.jsonl`，并继续处理其他 target。

## bytedcli 不存在

- 环境若缺少 `bytedcli`，`bytedcli-auth` 会失败。
- Heartbeat Inspector 会将该错误记入 DLQ，并继续执行后续步骤（不无限重试）。

## 群名歧义（同名群 / 多结果）

- 当 `chat_name` 搜索命中多个群聊且无法确定目标时，脚本会写入 DLQ 并跳过该 target。
- 建议改用 `chat_id`，或把群名写得更精确。

## 全局@我模式无结果

- 确认飞书 OAuth / 用户身份 token 正常。
- 可尝试加大 `relative_time`（例如 `last_3_days`）或调整 page_size。

## 解析 xlsx 失败

- 优先检查运行环境是否存在 `openpyxl`。
- 若仍失败，会进入 DLQ。
