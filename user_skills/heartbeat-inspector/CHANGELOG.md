# Changelog - heartbeat-inspector

## 2.7.1 (2026-07-10)

- 修复 `feishu_mentions_global` 403：弃用被平台拦截的 `fsopen.bytedance.net/open-apis/search/v2/message` 旧链路，改走 `lark-cli im +messages-search --is-at-me --as user` 受支持路由。
- 移除对 `self_open_id` 解析的硬依赖：全局 @我巡检改为直接按当前用户上下文检索，降低鉴权与用户信息 schema 变化带来的脆弱性。
- 补充回归测试：新增 `relative_time -> ISO time window` 与 `lark-cli messages-search` 调用链断言。

## 2.7 (2026-06-28)

- `mentions_global.chat_id` 断链修复：当全局 @ 我搜索结果缺失 `chat_id` 但携带群名时，新增唯一性群名回查，恢复 `chat_id`、群聊直达链接与群名。
- 零信任兜底：群名回查失败或歧义时写入 `.heartbeat_dlq.jsonl`，不猜测、不静默污染；补充缺失 `chat_id` 的回归测试。

## 2.6 (2026-06-22)

- 花名册英文名兜底补丁：`scripts/dual_write.py` 在通过群成员 API 动态补齐 `团队名单` 时，若成员 `name` 为空串，会自动回退使用 `zh_name` 作为 `英文名/花名` 列值，避免再写入 `⚠️[数据断链_待自愈]` 一类占位异常。
- 动态花名册回归测试升级：补充 `name="" + zh_name 有值` 的测试用例，并验证 `英文名/花名` 列会被真实写入。

## 2.4.1 (2026-06-06)

- 零信任过滤：`feishu_mentions_global` 在 Diff 之后、告警/抽取之前新增程序化噪音过滤，默认滤除 `@all/@_all/@所有人/<at id=all>` 与系统广播类消息。
- 快照前滚不受影响：即使某条增量被判定为噪音，也会继续推进 `last_seen_message_id`，避免同一批广播被重复巡检。
- 回归测试：补充 `@all` / 系统广播过滤测试，并验证正常 @我 消息与状态更新链路不受影响。

## 2.4.0 (2026-05-17)

- 路由约束补丁：结构化 JSON 行交给上层后，正式发送前必须先经过 `route_manifest.yaml` / `_routing_engine.py` 判定。
- 默认路由声明：上层发送默认走 `L0_FLAT` 新消息，禁止隐式 Thread 继承；仅 manifest 白名单（如 `taskflow_ack`）允许 `L1_THREAD_REPLY`。
- 新增 `scripts/routing_policy_hint.py`：用于本地演练或测试阶段输出默认路由建议，线上真实发送仍以 manifest / engine 为准。

## 2.3.0 (2026-05-04)

- 内置双轨写入（dual_write）：将增量 JSON 事件（chat_task 等）直接写入任务台账：`【Aime日志】`（全量审计） + `【任务库】`（仅 chat_task）。
- 双轨写入默认启用 bytedcli-auth 鉴权，并尝试执行 RAW 写后即读校验（如底层 CLI 无法提供 updatedRange，会显式写入 DLQ 作为告警线索）。

## 2.2.0 (2026-05-01)

- Ack-Lock：自动追踪任务是否被责任人认领；未响应则标记 `[⚠️待接单/未响应]`。
- State-Triggers：识别 `/done`、`/阻塞`、`/延期至...` 等魔法词，输出 `status_update` 结构用于状态同步。
- Relative Time Anchoring：基于消息绝对时间戳将“下班前/明早”等转为 `YYYY-MM-DD HH:MM`；无法锚定触发提醒。

## 2.1.1 (2026-05-01)

- 【】锚点高优识别：解析新消息时若原文包含【任务名称】短语，则最高优判定为任务，并直接继承该【...】原话作为任务名（不改写）。
- 逆向提醒联动：信息不全时的 `suggestion_reply` 增加“建议使用【任务名称】格式明确指出待办”。

## 2.1.0 (2026-05-01)

- 群聊任务提取 v2.0：对新增群聊消息进行结构化抽取输出 JSON（原文 100% 保真；负责人穷尽提取；缺失信息生成 `suggestion_reply`）。
- 取消 140 字截断：群聊增量输出升级为 JSON 行，`text` 字段保留完整原文（含换行）。

## 2.0.0 (2026-04-30)

- 支持群聊名称解析 chat_id。
- 支持全局@我巡检模式。
