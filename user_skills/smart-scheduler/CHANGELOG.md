# Changelog - smart-scheduler

## v2.8.2 (2026-06-30)
- 新增 `约会` / `/约` 触发词路由语义，主进程命中后必须强制路由到 `smart-scheduler`，并注入“先盘后建”合同。
- Stage 2 新增 `explicit_user_pick=pending` 停车锁；未收到用户明确 pick 前，禁止任何日历写入、建会、邀约或通知发送。
- `scripts/render_confirmation_prompt.py` 的 `routing_contract` 新增 `explicit_user_pick` 与 `stage_gate` 字段，把“Stage 2 输出后立即停止”下沉为可执行载荷。
- 已通过 `skill-forge-pipeline-v4` 继承原 Skill ID `261dcc9c-af72-455e-9a6e-b8cea340d9ac` 完成本次正式归档。

## v2.8.0 (2026-06-06)
- `scripts/render_confirmation_prompt.py` 的 matrix 模式输出升级为结构化 Markdown 表格，支持日期、双时区时段、覆盖率与备注列。
- 标准确认载荷新增稳定的 `routing_contract` 结构：`route`、`allow_thread_reply`、`reason`、`user_action`，把 L0 新消息确认收口固化为脚本级合同。
- 重新走 `skill-forge-pipeline-v4` 继承原 Skill ID `261dcc9c-af72-455e-9a6e-b8cea340d9ac` 完成锻造、入库与庆祝闭环。
