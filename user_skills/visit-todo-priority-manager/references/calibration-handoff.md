# calibration-handoff

## 1. 单次人工校准（第 1 段）

用户给出人工调优后的优先级说明时，执行顺序固定为：

1. 保留原始版本
2. 对齐任务键（description + source + owner）
3. 输出 `old_priority -> new_priority` diff
4. 生成校准后版本

不要跳过 diff，避免优先级漂移不可追踪。

## 2. 自动升级（第 2 段）

交给 `task-flow-engine` 的字段最少包括：

- `task_name`
- `owner`
- `ddl`
- `priority`
- `source_doc`
- `status`（若当前没有，需提醒下游补齐）

推荐巡检规则：

- `P1` 且 `DDL <= 3天`
- `status != 已完成`

则自动升级为 `P0`，触发催办提醒。

## 3. diff 输出建议

若输出为文档，可使用四列表：

| 任务键 | 原优先级 | 新优先级 | 变更原因 |
| --- | --- | --- | --- |
| xxx | P2 | P1 | 用户补充了业务影响 |

若输出给系统消费，使用 JSON 数组。
