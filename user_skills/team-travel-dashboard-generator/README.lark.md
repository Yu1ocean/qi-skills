## 📌 技能简介
将 UK/EU/JP POP BD 团队的差旅审批邮件与商旅预订通知自动沉淀为结构化差旅资产：默认全量抓取可识别姓名的邮件，兼容单程票 / 多段链式行程，输出带【合规健康度雷达】、【今日新增预警】、飞书原生 NEW 标签优先展示与 lark_md 降级兜底、发卡前 HTML 回捞防呆、费用主卡常驻展示与强提醒特效的差旅大屏 V3.9，并补充 `output/mail_ledger.json` 作为 Email Logger 零信任 QA 审计台账。适用于团队差旅巡检、周会大屏、跨区域拜访排期复盘与合规风险扫描场景。

## 🔑 触发词
- 核心关键词：
  - 差旅大屏 V3.9
  - 今日新增预警
  - 差旅审批邮件
  - booking 差旅大屏
  - 周末差旅预警
  - Email Ledger QA
  - travel dashboard
- 典型指令示例：
  > 抓近 3 个月差旅审批 / 预订邮件，给 UK/EU/JP POP BD 团队做一个自动化差旅大屏，并补齐周末差旅预警。
  > 升级团队差旅大屏，兼容多段链式行程去重，并额外产出一份可审计的邮件台账做 QA。

## ⚙️ 核心架构 / SOP / 约束条件
- **核心链路**：飞书邮箱检索 → 全量姓名识别 → 核心字段抽取 → 多段行程细粒度去重 / trip 聚类 → 合规字段计算 → 历史足迹库判定首次差旅地 → 经纬度解析与缓存 → JSON 结构化 → 静态暗色大屏 HTML → Dynamic UI 入口文件 → Email Ledger 审计台账。
- **邮件抓取**：通过 `lark-cli mail +triage` 搜近 3 个月审批邮件 / 预订邮件，再用 `lark-cli mail +messages` 拉取正文。
- **抓取范围**：默认 `ALL_PARSED_TRAVELERS`，只要邮件中能稳定解析出姓名，就允许进入候选行程；不再依赖固定 9 人名单。
- **字段硬约束**：每条正式记录必须带齐 `姓名 / 出发城市 / 目的城市 / 出发时间` 四项；单程票 / 多段 booking 允许 `return_time` 为空；`reason` 字段已废弃，不再提取、不再展示。
- **时间格式约束**：`departure_time / return_time / booking_time / approval_time / source_sent_at` 统一归一为 `YYYY-MM-DD` 文本格式，减少前端与 QA 侧的二次解析歧义。
- **合规字段**：除 `booking_lead_days / is_booked_before_approval / is_over_cabin_policy / is_hotel_over_policy / over_policy_reason / duplicate_booking_flag / is_first_time_destination` 外，新增 `contains_weekend` 进入合规健康度雷达与 `compliance_alerts` 汇总口径。
- **今日新增预警**：每次生成 JSON 后写入 `output/snapshots/YYYY-MM-DD.json`，并基于昨日快照对 `compliance.alerts` 做集合差；唯一键为“人员姓名 + 预警类型 + 日期区间”三元组，新增项会写入 `is_new=true`。静态 HTML / Dynamic UI 继续使用 `🆕 NEW` 文案高亮，飞书卡片优先使用原生 `tag` NEW 标签展示；若卡片服务返回 `not support tag`，则用 `--new-label-style lark_md` 降级为 `**🆕 NEW**` 加粗文本。
- **飞书卡片模板**：`assets/team_travel_dashboard_card_template.json` 为官方兜底卡片模板，必须使用 `schema: 2.0` 与 `body.elements`；通过 `scripts/build_travel_card_payload.py` 从快照生成 `.ephemeral_pool/[task_id]_team_travel_dashboard.card.json` 后，再交由 `centralized-transmitter` 创建与发送。V3.8 起新增预警会被拆成逐条独立 element：默认左侧使用原生 `tag` 组件展示 NEW，兼容降级时改为 `lark_md` 加粗文本。V3.9 起发卡前必须通过 `--deploy-html` 回捞即将部署的 HTML，确保每条新增预警按 person + rule_type/trip type + date_range 命中，否则以 `[ALERT_MISMATCH]` 熔断。
- **发送目标约束**：差旅大屏卡片默认走 `CHAT_REGISTRY.json -> travel_dashboard_report`，即 `yuqinan` 的 p2p 私聊；禁止复用 `task_patrol_broadcast` 向群聊广播。
- **QA 审计链路**：`scripts/build_mail_ledger.py` 会额外输出 `output/mail_ledger.json`，保留 `message_id / thread_id / sent_at / primary_category / classification_evidence / travel_record_count` 等字段，供 travel parser 命中复核与跨技能零信任 QA。
- **模板约束**：大屏必须包含数据总览、飞线总览、目的地热度、合规健康度雷达、今日新增预警、Gantt 时间轴、明细表；首次差旅地需在地图 / 时间轴上做红色强提醒；V3.4 起静态 HTML 与 Dynamic UI 卡片均展示【今日新增预警】；V3.3 起行程详情中的原始 `\\n` 必须转为正常换行，`Message ID` 调试字段禁止继续出现在用户侧，费用金额需进入主卡常驻展示区。
- **动态展示衔接**：本技能负责生成最终 HTML 与 Dynamic UI 入口文件；结果或链接需额外组装成卡片 Payload，落盘到 `.ephemeral_pool/`，由主进程统一发射。
- **说明层同步闸门**：凡是修改 `assets/travel_dashboard_template.html` 或 `assets/travel_dashboard_dynamic_ui_template.html`，必须在同一轮提交中同步更新 `SKILL.md`、`CHANGELOG.md`、`README.lark.md` 三份说明文件；若模板 diff 存在而说明层无 diff，则视为发版失败，不进入归档流水线。

## 📖 案例实录 (Best Practice)
- 🧑‍💻 用户输入：
  ```text
  升级差旅大屏，兼容 booking 多段链式行程去重，并补一份邮件台账做零信任 QA。
  ```
- 🤖 标准输出：
  ```text
  产物 1：output/travel_dashboard.json
  - 近 3 个月差旅结构化数据
  - trips 数组包含核心字段、合规字段、contains_weekend、trip_cluster_index、首次差旅地标记与来源邮件信息

  产物 2：output/travel_dashboard.html
  - 暗色差旅大屏 V3.3
  - 包含数据总览、飞线总览、目的地热度、合规健康度雷达、Gantt 时间轴、明细表
  - 费用金额前移到主卡常驻展示区，详情文案换行为正常渲染，`Message ID` 不再对用户展示

  产物 3：output/travel_dashboard.dynamic.html
  - Dynamic UI 入口文件
  - 首次差旅地在地图 / 时间轴做红色高亮与呼吸提醒

  产物 4：output/travel_footprint_library.json
  - 历史足迹库
  - 支持跨轮运行判定首次到达

  产物 5：output/mail_ledger.json
  - 可审计的邮件台账
  - 供 travel parser 命中复核与跨技能零信任 QA
  ```

## 这次交付内容
- 升级技能目录：`user_skills/team-travel-dashboard-generator/`
- 主脚本：`scripts/build_travel_dashboard.py`
- 审计脚本：`scripts/build_mail_ledger.py`
- 静态模板：`assets/travel_dashboard_template.html`
- Dynamic UI 模板：`assets/travel_dashboard_dynamic_ui_template.html`
- 规则文档：`references/mail-extraction-rules.md`
- 输出契约：`references/dashboard-output-contract.md`
- 版本日志：`CHANGELOG.md`
