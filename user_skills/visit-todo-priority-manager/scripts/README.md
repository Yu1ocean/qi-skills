# visit-todo-priority-manager scripts

## 1. `todo_priority_guard.py`

用途：
- 校验输入链接是否为飞书 `wiki` / `docx`
- 校验 To-Do 行字段完整性与优先级枚举
- 检查 Owner 是否残留 `@bytedance.com` 邮箱
- 识别并标准化常见 DDL 表达，输出 `normalized_ddl` 与 `ddl_days`
- 按规则识别应升级的 P1 条目

CLI 示例：
```bash
python todo_priority_guard.py --input rows.json
python todo_priority_guard.py --doc-urls '["https://bytedance.larkoffice.com/docx/xxxx"]'
```

---

## 2. `priority_diff.py`

用途：
- 对原始版 todo_rows 与人工校准版做任务级 diff
- 优先用 `task_key` 匹配；缺失时退化为 `(owner, description[:30])`
- 输出 `old_priority -> new_priority + change_reason`
- 统计未变更条目数、未匹配条目数
- 支持 JSON / Markdown 两种输出格式

CLI 示例：
```bash
python priority_diff.py --original original.json --calibrated calibrated.json --format markdown
python priority_diff.py --original original.json --calibrated calibrated.json --format json
```

---

## 3. `escalation_checker.py`

用途：
- 读取 todo_rows 并执行升级规则：`DDL <= 阈值天数 && 未完成 && priority == P1 -> P0`
- 支持 `--dry-run` 仅列出应升级条目
- 支持 `--threshold` 自定义升级阈值（默认 3 天）
- 非 dry-run 模式下会回写原文件中的 priority

CLI 示例：
```bash
python escalation_checker.py --input rows.json --dry-run
python escalation_checker.py --input rows.json --threshold 5
```
