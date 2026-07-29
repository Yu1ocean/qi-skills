# Weekly Top3 Patrol — Schedule 工具 Cron 配置

将以下两条配置通过 `schedule` 工具挂载，即可完成全自动巡检闭环。

## Mode A — 周日 16:00 软性催办

```json
{
  "action": "create",
  "name": "weekly-top3-patrol-mode-A",
  "mode": "cron",
  "cron_expression": "0 16 * * 0",
  "message": "@Aime 跑 weekly-top3-patrol Mode A，巡检本周重要三件事未填名单并群内软性催办（@ UK/EU/JP POP BD 群）",
  "stopped_at": "2026-11-21T16:00:00+08:00",
  "target": "main"
}
```

## Mode B — 周一 16:00 硬性收口

```json
{
  "action": "create",
  "name": "weekly-top3-patrol-mode-B",
  "mode": "cron",
  "cron_expression": "0 16 * * 1",
  "message": "@Aime 跑 weekly-top3-patrol Mode B，对未填名单做 freebusy 共同空闲交集查找并自动强插 15min 1on1（与 yuqinan）",
  "stopped_at": "2026-11-21T16:00:00+08:00",
  "target": "main"
}
```

## 运维约定

- **首次部署**：必须先用 `--dry-run` 跑一周，验证未填名单准确性 + 共同空闲计算正确性，再切真实路径。
- **截止时间**：默认 180 天后停止（2026-11-21），到期需用户主动 resume。
- **暂停**：临时停跑用 `schedule action=pause`；不要直接 delete，方便事后排查。
- **节假日**：不做特殊处理（OKR 节奏对齐人）；若用户明确要求跳过特定周，再加 `--skip-week 2026-W30` 这类参数。
