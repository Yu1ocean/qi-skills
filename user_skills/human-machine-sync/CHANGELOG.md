# Changelog - human-machine-sync

## v1.3 (2026-06-20)
- 新增 roster_sync 通知硬切能力：支持在同步脚本内直接产出 `.ephemeral_pool/[TASK_ID]_[TOPIC_SLUG].post.json`，并统一调用 `centralized_transmitter.py preflight` / `send`，彻底替代旧的 `im_send.py send` 私发链路。
- 新增 `--notify-chat-usage / --notify-chat-id` 参数：对群成员/群名单同步场景先按 `CHAT_REGISTRY.json` 做群 preflight（chat_id + 群名关键字断言），避免猜群和错群发送。
- 新增 `--notify-dry-run`：只跑 payload 落盘 + CT preflight，不做真实私发，便于 P0 patch 验证。

## v1.2 (2026-06-13)
- 补充占位模板过滤：Markdown 中若存在 `DEC-YYYYMMDD-NNN` 一类 schema 示例记录，audit / sync / patrol 会自动跳过，不把样例行误判为真实新增。
- `report` 新增 `skipped_placeholders` 字段，显式回显被跳过的模板记录，避免“静默吞掉”示例数据。

## v0.1 (2026-06-13)
- 初始化 `human-machine-sync` 技能骨架，明确本地文件作为 SSOT、飞书表格作为镜像台账的同步定位。
- 新增 `scripts/human_machine_sync.py`，支持 Markdown YAML 代码块 / 纯 YAML 解析、字段级 diff、`audit|sync|patrol` 三种模式，以及单行写入后的 RAW 回捞校验。
- 补充 Decision Registry 首个集成场景映射文件 `assets/decision_registry_field_mapping.json`，用于首轮 audit 验证。
