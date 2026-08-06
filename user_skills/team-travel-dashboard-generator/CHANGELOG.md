# Changelog

## V3.7 · 2026-08-06
- **飞书卡片 NEW 标签原生化**：`build_travel_card_payload.py` 不再把 `🆕 **NEW**` 拼进单块 markdown 文本，而是把新增预警拆成逐条独立 element，并在左侧使用飞书原生 `tag` 组件承载 NEW。
- **模板改为摘要 + 明细拼装**：`assets/team_travel_dashboard_card_template.json` 只保留摘要与固定大屏入口，新增预警列表在运行时注入，避免继续把 badge 和明细耦合在同一段正文里。
- **说明层同步**：`SKILL.md` 与 `README.lark.md` 升级到 V3.7，明确本次修复只触达卡片展示层，不改 diff 逻辑与快照逻辑。

## V3.6 · 2026-07-29
- **新增预警对象级标记**：快照 diff 改为按“人员姓名 + 预警类型 + 日期区间”三元组生成稳定 `alert_key`，并把 `is_new` 注入到 `compliance.alerts` 与 `compliance.daily_new_alerts.alerts`。
- **HTML / Dynamic UI 高亮**：今日新增预警卡片增加 `🆕 NEW` 角标、橙红渐变底与发光边框，和持续预警做视觉隔离。
- **飞书消息卡片高亮**：`build_travel_card_payload.py` 新增 `DAILY_NEW_ALERT_LINES` 渲染，卡片正文直接列出新增预警 Top 5，均带 `🆕 NEW` 前缀。

## V3.5 · 2026-07-27
- **飞书卡片 Schema 2.0 修复**：新增 `assets/team_travel_dashboard_card_template.json` 与 `scripts/build_travel_card_payload.py`，正式废弃旧版 V1 顶层 `elements` 兜底卡片，统一输出 `schema: 2.0` + `body.elements`，可被 `centralized-transmitter` 创建并发送。
- **发送目标修正**：差旅大屏卡片默认发送目标改为 `CHAT_REGISTRY.json -> travel_dashboard_report`，即 `yuqinan` 私聊；明确禁止复用 `task_patrol_broadcast` 向群聊平铺。
- **目标用途显式入卡**：`scripts/build_travel_card_payload.py` 新增 `chat_registry_usage` 字段与 `--chat-registry-usage` 参数，默认固化为 `travel_dashboard_report`，降低后续发送链路把差旅卡片误判成群播的风险。
- **快照驱动发卡**：卡片从 `output/snapshots/YYYY-MM-DD.json` 读取行程数、合规预警数、今日新增预警与固定大屏链接，避免手写兜底 payload 再次漂移。

## V3.4 · 2026-07-23
- **今日新增预警 diff**：新增 `compliance.alerts` 明细列表，并按 `{person}_{route}_{date}_{rule_type}` 生成稳定唯一 ID，用于快照集合差。
- **快照持久化**：每次 `collect-mails` / `build` 生成 JSON 后，同步写入 `output/snapshots/YYYY-MM-DD.json`，同日重跑幂等覆盖。
- **卡片与 HTML 展示**：静态 HTML 与 Dynamic UI 卡片新增【今日新增预警】模块，支持“新增列表 / 今日无新增预警 ✅ / 首次运行，暂无历史对比 📊”三种状态。
- **回归验证**：用今日已有 `output/travel_dashboard.json` 进行今日 vs 今日模拟 diff，预期新增预警为 0。

## V3.3 · 2026-06-13
- **UI 说明层补档**：将今日已落盘的 `assets/travel_dashboard_template.html` 升级同步补写到 `SKILL.md`、`CHANGELOG.md` 与 `README.lark.md`，修复“代码已变但说明层失语”的断层。
- **换行渲染修复入档**：详情文案中的原始 `\\n` 已纳入正式 UI 行为说明，用户侧应看到正常换行而非转义字符。
- **调试噪音下线**：`Message ID` 从用户可见明细区移除，文档与说明层同步收口为“禁止在用户侧继续展示调试字段”。
- **费用主卡常驻展示**：费用金额从详情区前移到主卡常驻展示区，确保关键成本信息首屏可读。
- **防重演机制落地**：新增“说明层同步闸门”——后续凡是模板改动，必须同步更新 `SKILL.md` / `CHANGELOG.md` / `README.lark.md`，否则不得进入归档流水线。

## V3.2 · 2026-06-11
- **partial hotel 去重改为显式告警**：`deduplicate_records()` 不再对同一人 / 同一入住窗的 `record_status=partial` 酒店记录做字典静默覆盖；命中同一 dedup key 的多封酒店预订邮件会全部保留，并统一打上 `duplicate_booking_flag=true`、`needs_review=true` 与动态 `review_reason`。
- **审计字段补齐**：新增 `review_reason`、`duplicate_candidate_rank`、`duplicate_candidate_count`，用于保留 duplicate partial hotel 的人工核查语义与候选排序信息。
- **回归验证补齐**：以赵月晨 / 上海 / 06-04~06-05 样例回归，确认不再丢失 ¥737.49 酒店记录。

## V3.1 · 2026-06-11
- **S1 止血：酒店孤儿单不再静默消失**：booking 酒店记录在无法匹配交通行程时，改为保留为 `record_status=partial` + `travel_context_missing=true` 的可审计记录。
- **S2 差标接入框架落地**：主脚本新增 `--hotel-policy-table`，酒店差标判定优先级固定为 `policy_table > mail_extract > email_fallback > unknown`，并补齐 `hotel_policy_decision_source / policy_match_level / policy_rule_id / needs_review / hotel_policy_severity` 字段。
- **S3 可运营审计补齐**：输出 payload 升级为 `3.1`，新增 `audit.booking_pipeline`、`record_status_breakdown`、`partial_trips`、`travel_context_missing_count` 等观测字段，便于统计 enrich 成功与 partial 保留规模；同时拆分 `hotel_partial_candidate_retained / hotel_partial_retained / hotel_partial_gap_after_dedup`，显式区分候选层与展示层口径。
- **历史差标痕迹补位**：差标真相源已确认落在飞书表 `https://bytedance.larkoffice.com/sheets/KF9Wsp1WZhviWZtrndXcqD0tnmp?sheet=eI7OnF`，并已将 `城市差标明细` 的 182 条规则回填为本地 `output/hotel_policy_rules.json`；全局配置工作表为 `sheet=0IsAjU`。

## V2.7 · 2026-06-10
- **官方模板定稿**：将 `published/travel-dashboard-live/index.html` 同步为 `assets/travel_dashboard_template.html`，作为 V2.7 标准静态大屏模板。
- **城市热度网络图坐标归一化**：节点坐标系从像素绝对值切换为 `[0,1]` 比例坐标，适配不同容器尺寸，降低错位与漂移风险。
- **网络图交互增强**：开启 `roam: 'scale'`，支持滚轮缩放，便于查看高密度城市节点。
- **裁切问题修复**：移除 `.network-panel` 的 `overflow:hidden` 裁切影响，通过专属覆写保障网络图完整可视。

## V2.6 · 2026-06-08
- **周末差旅合规口径补齐**：`contains_weekend` 正式进入合规健康度雷达与 `compliance_alerts` 汇总口径，用于识别跨周末出行带来的合规关注点。
- **多段行程细粒度去重说明补齐**：明确 booking 多段链式行程需要先做 segment 粒度去重，再做 trip 聚类，避免同一趟出行被重复入库。
- **Email Logger 零信任 QA 落地**：新增 `scripts/build_mail_ledger.py` 审计链路，输出 `output/mail_ledger.json`，用于 travel parser 命中范围复核、邮件分类证据回溯与跨技能 QA。
- **技能迭代入库修复**：配套修复技能台账日期写入链路，`updated_at` 不再以纯文本落入飞书表格，避免本技能升级时再次出现日期格式漂移。
- **文档同步**：README / SKILL / 输出契约统一升级到 V2.6，补齐全量抓取、周末差旅、细粒度去重与审计台账说明。

## V2.3 · 2026-06-06
- **精简数据格式**：彻底删除“事由”（reason）字段的提取、落库与展示逻辑，降低业务信噪比。
- **时间格式归一化**：提取逻辑中所有的相关时间字段（departure_time, booking_time, return_time, approval_time, source_sent_at）统一切换为仅保留日期格式（YYYY-MM-DD）。
- **UI 适配**：同步更新静态大屏与 Dynamic UI 模板，移除事由列及相关图表，适配新版精简数据流。
- **文档同步**：更新 Skill 说明、输出契约与抽取规则文档，明确新的数据格式要求。

## V2.2 · 2026-06-06
- 移除 `NAME_SET` 白名单硬编码，切换为 `ALL_PARSED_TRAVELERS` 全量抓取模式：只要邮件中能解析出姓名，就进入候选行程。
- 放宽 booking 行程入库校验：单程票 / 多段链式行程允许 `return_time` 为空，避免被正式 trip 校验误刷掉。
- booking 姓名提取从“白名单命中”改为“通用姓名提取”，兼容截图中这类仅凭真实姓名出现的预订通知。
- 输出 JSON 的 `filters` 从 `allowed_names` 改为 `capture_scope`，与全量抓取模式对齐。

## V2.1 · 2026-06-06
- 新增路线 B / booking 通道，主脚本支持 `approval / booking / auto` 三种模式，默认 `auto`。
- 新增 booking 查询词与模板识别，兼容“员工商旅系统(请勿回复/no reply)”的火车票 / 机票 / 酒店通知。
- booking 模板改为零信任取值：`booking_time` 可用邮件发送时间，`approval_time` 允许为空，`reason` 统一使用 `BOOKING_NOTICE_UNDISCLOSED` 占位。
- 支持 round-trip flight 合并、reverse leg pairing（`A->B` + `B->A`）以及 hotel 对 transport trip 的 enrich。
- `normalize_city` 新增常见车站 / 机场别名收敛，如 `上海虹桥 / 深圳北 / 杭州东 / 南通西`。
- 输出契约与规则文档升级到 V2.1，明确 booking 通道、unknown/null 指标语义与证据链约束。

## V2.0 · 2026-06-06
- 新增 6 个合规字段：`booking_lead_days`、`is_booked_before_approval`、`is_over_cabin_policy`、`is_hotel_over_policy`、`over_policy_reason`、`duplicate_booking_flag`。
- 新增业务字段：`is_first_time_destination`。
- 引入历史足迹库 `output/travel_footprint_library.json`，支持跨轮运行判定首次差旅地。
- 静态大屏与 Dynamic UI 模板新增【合规健康度雷达】模块。
- 地图与 Gantt 时间轴新增“首次差旅地”红色高亮 / 呼吸灯提醒。
- 输出契约升级为 V2.0，并补充卡片 Payload 交付约束。

## V1.1 · 2026-06-06
- 首版差旅大屏能力上线。
- 支持差旅审批邮件抓取、结构化抽取、经纬度解析、静态 HTML 大屏与 Dynamic UI 入口产出。
