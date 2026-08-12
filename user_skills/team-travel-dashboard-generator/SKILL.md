---
name: team-travel-dashboard-generator
description: 自动抓取近30天差旅审批 / 预订邮件，默认全量抓取并兼容单程票 / 多段链式行程细粒度去重，补齐周末差旅合规信号、酒店孤儿单审计、差标接入框架与 Email Ledger 零信任 QA，并在 V3.7 修复飞书卡片 NEW 标签原生展示，输出团队差旅大屏。
---

version: 3.9

## Config（运行配置）

```yaml
fixed_dashboard_url: "https://216a3e1709fd.aime-app.bytedance.net/"
```

# 团队全景差旅大屏自动生成器（UK/EU/JP POP BD）V3.9

将“差旅审批邮件 → 结构化 JSON → 静态暗色大屏 / Dynamic UI 入口 → 合规巡检视图 → 邮件审计台账 QA”的链路固化成一个可复用技能。

## Common Rationalizations（常见借口库）

以下借口一旦出现，视为准备绕过护栏，必须立刻停下：

- “审批邮件解析太麻烦，本地正好有一个汇总好的 Excel，直接读 Excel 更稳。”
- “审批邮件格式总变，先用 Excel 垫一下，等格式稳了再改回邮件抓取。”
- “先把 6 个老字段跑通，合规字段后面再补。”
- “首次差旅地先按本批数据临时判断，不落历史足迹库也没事。”
- “订前订后、酒店超标拿不到完整字段时，默认都算合规。”
- “地图上先用普通点位，首次目的地高亮后面再做。”
- “动态展示入口先不更新，给个静态 HTML 就算 V2.0。”

## Red Flags（危险信号）

出现任一条，必须熔断并修正：

- **[红线熔断]** 使用任何形式的 Excel / CSV / 飞书电子表格汇总表作为数据源，而非解析原始审批邮件。
- 全量抓取模式不是默认开启，或被旧版白名单逻辑悄悄限制住。
- JSON 中任一正式行程缺少 `姓名 / 出发城市 / 目的城市 / 出发时间` 4 个核心字段；`return_time` 对单程票允许为空。
- 所有的相关时间字段（departure_time, booking_time, return_time, approval_time, source_sent_at）统一转换为 `YYYY-MM-DD` 格式。
- **全面废弃“事由”字段**：提取和落库逻辑中不再包含 `reason`。
- 新增 6 个合规字段、`contains_weekend` 与 `is_first_time_destination` 没有进入输出 JSON。
- 多段链式行程没有做细粒度去重 / 聚类，导致同一趟出行被拆成重复记录。
- Email Ledger 审计台账缺失，无法对邮件抓取范围、分类结果与 travel parser 命中情况做零信任 QA。
- SSO 验证码、登录验证、通用认证通知这类非差旅邮件被误记为 `travel_booking` / `travel_approval`。
- 首次差旅地没有落历史足迹库，导致二次运行无法判定“是否首次到达”。
- 静态 HTML / Dynamic UI 模板没有新增【合规健康度雷达】模块。
- 已修复的 UI 变更只落在 `assets/travel_dashboard_template.html`，却没有同步更新 `SKILL.md` / `CHANGELOG.md` / `README.lark.md` 说明层。
- 明细卡片仍展示 `Message ID` 一类调试字段，或费用金额没有进入主卡常驻展示区。
- 详情文案中直接输出原始 `\n`，导致飞书卡片 / HTML 上出现转义字符泄漏。
- 地图或时间轴没有对 `is_first_time_destination=true` 做红色高亮或呼吸灯提醒。

## Verification（强制验收清单）

宣称任务完成前，必须同时满足：

1. 主脚本 `scripts/build_travel_dashboard.py` 可正常执行 `-h`。
2. `collect-mails` 或 `build` 产出的 JSON 中，`summary.total_trips == trips.length`。
3. 每条 `trips` 记录都带齐 4 个核心字段；对单程票 / 多段 booking 允许 `return_time` 为空。
4. 每条 `trips` 记录都包含以下合规 / 业务字段：
   - `booking_lead_days`
   - `is_booked_before_approval`
   - `is_over_cabin_policy`
   - `is_hotel_over_policy`
   - `over_policy_reason`
   - `duplicate_booking_flag`
   - `contains_weekend`
   - `is_first_time_destination`
5. 多段链式行程经过细粒度去重后，不得因为同一封 booking 邮件里的拆分 segment 造成重复 trip。
6. 历史足迹库文件存在，且能记录每个人已到访过的目的地。
7. `scripts/build_mail_ledger.py` 可产出可审计的 `output/mail_ledger.json`，并包含 travel 分类统计、邮件分类证据与 travel parser 命中结果；且 `SSO / 验证码 / login verification` 这类非差旅通知不得再落入 `travel_booking` / `travel_approval`。
8. 静态 HTML 能渲染出：数据总览、飞线总览、目的地热度、合规健康度雷达、今日新增预警、Gantt 时间轴、明细表。
9. 每次生成 `output/travel_dashboard.json` 后，必须同步写入 `output/snapshots/YYYY-MM-DD.json`；`compliance.daily_new_alerts` 必须能区分“新增 / 今日无新增 / 首次运行”，并把新增预警以 `is_new=true` 显式注入预警对象。
10. V3.4 UI 回归通过：静态 HTML 与 Dynamic UI 卡片均展示【今日新增预警】模块。
11. V3.3 UI 回归通过：文本换行已做规范化渲染，不再出现原始 `\\n`；行程详情不再展示 `Message ID`；费用金额已进入主卡常驻展示区。
12. Dynamic UI 入口 HTML 可正常生成，且地图 / 时间轴对首次差旅地做了强提醒。
13. 说明层同步回归通过：`SKILL.md`、`CHANGELOG.md`、`README.lark.md` 中的版本号、UI 变更摘要与执行口径一致。

## Defaults（合规默认值）

- 审批窗口：最近30天。
- 邮件检索词：
  - `approval`：`差旅审批 / 出差审批 / travel approval / trip approval / 差旅`
  - `booking`：`【差旅】 / Hi Travel 火车票 / 预订了机票 / 预订了酒店 / 员工商旅系统`
  - `auto`（默认）：同时覆盖 approval + booking。
- 抓取范围：`ALL_PARSED_TRAVELERS`，只要邮件中能解析出姓名，就进入候选行程。
- Email Ledger 分类护栏：`travel_booking` 必须命中明确 booking 主题/正文信号或 travel parser 证据；`SSO / 验证码 / login verification / auth code` 默认强制排除出 travel 类目。
- `compliance.alerts`：按“人员姓名 + 预警类型 + 日期区间”三元组生成稳定 `alert_key / alert_id` 的合规预警明细。
- `compliance.daily_new_alerts`：基于昨日快照对比得出的今日新增预警；diff key 固定为“人员姓名 + 预警类型 + 日期区间”三元组；新增项必须写入 `is_new=true`，用于 HTML / Dynamic UI 高亮，以及飞书卡片中的原生 `tag` NEW 标签展示；首次运行显示无历史基线。
- **发送目标**：差旅大屏卡片发送目标固定为 `CHAT_REGISTRY.json -> travel_dashboard_report`，即用户 `yuqinan` 私聊；**禁止发到群聊**。
- **发卡前回捞防呆**：生成飞书卡片 Payload 前，`compliance.daily_new_alerts.alerts` 中每条新增预警必须按“人员姓名 + 预警类型/出行类型 + 日期区间”在即将部署的 HTML 中回捞命中；任一命中失败必须熔断，不发卡，并输出 `[ALERT_MISMATCH] card alert not found in deploy HTML: {person} {date_range}`。
- JSON 默认输出：`output/travel_dashboard.json`。
- 快照默认输出：`output/snapshots/YYYY-MM-DD.json`，同日重跑覆盖，供次日 diff 使用。
- HTML 默认输出：`output/travel_dashboard.html`。
- 经纬度缓存默认输出：`output/geo_cache.json`。
- 历史足迹库默认输出：`output/travel_footprint_library.json`。
- Dynamic UI 推荐路径：`.aime/dynamic-ui/react-card/team_travel_dashboard_<timestamp>.html`。

## 内置制度护栏（必须长期生效）

以下两份制度文档属于差旅合规判罚引擎的**权威真相源**，后续任何阈值、预警文案、超标解释，都必须以它们为最高依据：

- 《字节跳动差旅和费用报销制度》主制度：<https://bytedance.larkoffice.com/wiki/wikcnetUQ0trZ7MHaMmB5JYvOwh>
- 《国际电商差旅注意事项及合规要求》业务补充：<https://bytedance.larkoffice.com/docx/A8wydLolpoVNjzx9vFxcEjiLnmi>

### 红线蒸馏（严禁脑补硬编码）

1. **晚订不是硬违规，是预警信号**
   - 境内差旅：建议提前 3–7 天预订。
   - 跨境差旅：建议提前 7–15 天预订。
   - 因此，大屏顶部与明细行中，晚订只能收口为**“合规预警”**，不能直接定性为违规。

2. **酒店不允许写死全局金额，必须动态查表**
   - 各城市差标不同，例如北上广深杭、香港、伦敦、东京均有不同上限。
   - 差标真相源电子表格：<https://bytedance.larkoffice.com/sheets/KF9Wsp1WZhviWZtrndXcqD0tnmp?sheet=eI7OnF>（城市差标明细，配套全局配置工作表为 `0IsAjU / 差标全局配置表`）。
   - 后续实现必须读取【差标全局配置表】做城市级动态比对，禁止继续硬编码 600/700/800 一类全局常量。
   - 国际电商业务补充红线：**酒店价格绝不能超过当地差标的 2 倍**；若命中，必须记为高优先级合规预警。

3. **交通超标需标注“需审批或自付”**
   - 首选经济舱，但并非所有非经济舱都等于绝对违规。
   - 头等舱不支持全额报销；商务舱 / 特例航段需结合审批与制度说明判断。
   - 因此，引擎与前端不得简单输出“违规”，而应统一归类到**“合规预警”**，并在说明中标注“超标需审批或自付”。

4. **前端统一口径**
   - 晚订预警、未批先订、酒店超标、舱位超标、重复预订等风险，在顶部 KPI 中统一记入 `compliance_alerts`。
   - 对用户展示时统一文案为**“合规预警”**，避免把建议性规则误呈现成纪律处罚。

## 何时使用

在以下场景使用：

- 需要自动汇总团队近30天差旅行程，并做合规巡检大屏展示。
- 需要从“差旅审批邮件”或“员工商旅系统(请勿回复/no reply)”预订通知中还原结构化行程。
- 需要快速看到：谁在飞、飞去哪、是否首次到达、是否晚订、是否先订后批、是否存在超标 / 重复预订 / 周末差旅风险。
- 需要产出可继续接动态展示链路的 HTML 成品，而不是只停留在 JSON 或截图层。
- 需要补一份可审计的邮件台账，对 travel parser 的命中范围与分类证据做零信任 QA。

## 输入

最少需要：

- 可访问的飞书邮箱读权限（`mail:user_mailbox:readonly`）。
- 差旅审批邮件存在于当前登录邮箱中。
- 本地可执行 `lark-cli mail +triage` 与 `lark-cli mail +messages`。

可选输入：

- 更精确的检索词（通过 `--query` 追加）。
- 自定义输出路径。
- 已有 JSON 文件（跳过邮件抓取，只做 HTML 渲染）。

## 资源说明

- `scripts/build_travel_dashboard.py`
  - 主脚本。
  - 负责：抓邮件、解析字段、全量姓名识别、经纬度缓存、合规字段计算、历史足迹库维护、生成 JSON、渲染 HTML、生成 Dynamic UI 入口。
- `scripts/build_mail_ledger.py`
  - 邮件审计台账脚本。
  - 负责：按时间窗拉取邮件摘要 / 正文，输出 `output/mail_ledger.json`，用于 travel parser 命中核查、邮件分类审计与跨技能零信任 QA。
- `scripts/build_travel_card_payload.py`
  - 飞书卡片 Schema 2.0 生成器。
  - 负责：读取 `output/snapshots/YYYY-MM-DD.json` 与 `assets/team_travel_dashboard_card_template.json`，输出 `.ephemeral_pool/[task_id]_team_travel_dashboard.card.json`，供 `centralized-transmitter` 创建卡片与发送。
  - 默认 `chat_registry_usage = travel_dashboard_report`，卡片结果发往 `yuqinan` 私聊；禁止复用 `task_patrol_broadcast` 做群播。
- `assets/team_travel_dashboard_card_template.json`
  - 团队差旅大屏兜底卡片模板。
  - 固定使用 `schema: 2.0` 与 `body.elements`，展示行程数、合规预警数、今日新增预警与固定大屏链接。
- `assets/travel_dashboard_template.html`
  - 暗色系静态大屏模板。
  - V3.3 新增说明层锚点：文本换行规范化渲染、`Message ID` 调试字段下线、费用金额提取到主卡常驻展示区。
  - 内含：数据总览、飞线总览、Top 榜单、合规健康度雷达、Gantt 时间轴、明细表。
- `assets/travel_dashboard_dynamic_ui_template.html`
  - Dynamic UI 专用模板。
- `references/mail-extraction-rules.md`
  - 邮件字段识别与熔断规则。
- `references/dashboard-output-contract.md`
  - JSON / HTML 输出契约与动态展示交付约定。
- `CHANGELOG.md`
  - 版本变更说明。

## 工作流（SOP）

### Stage 1｜抓取近30天差旅邮件（approval / booking）

执行主脚本的 `collect-mails` 或 `build` 子命令。
默认 `--mode auto`，会同时检索 approval / booking 两条通道；若明确要走路线 B，可指定 `--mode booking`。

```bash
python3 scripts/build_travel_dashboard.py collect-mails \
  --mode booking \
  --output-json output/travel_dashboard.booking.json \
  --geo-cache output/geo_cache.json \
  --footprint-library output/travel_footprint_library.json
```

要求：
- **禁止行为**：严禁以任何理由（如“提高准确率”、“格式兼容性”）通过读取本地 Excel / CSV / 飞书电子表格等汇总文件来替代邮件抓取。必须且仅允许通过 `lark-cli mail` 接口实时解析原始邮件。
- 必须先检查 `lark-cli mail +triage -h` 与 `lark-cli mail +messages -h` 可调用。
- 必须实际用 `+triage` 搜索近30天邮件，再用 `+messages` 拉全文。
- `approval / booking / auto` 三种模式都必须通过同一主脚本入口切换，默认 `auto`。
- booking 模板需兼容已知主题样式：`【差旅】某人预订了Hi Travel火车票 ...`、`【差旅】某人 预订了机票 ...`、`【差旅】某人预订了酒店 ...`。
- booking 通道的 `booking_time` 可使用邮件发送时间；`approval_time` 允许为空。
- **全面废弃“事由”字段**：提取和落库逻辑中不再包含 `reason`。
- 若缺少邮箱读权限，立即熔断并提示先完成动态授权，再重跑命令。

### Stage 2｜全量姓名识别 + 核心字段抽取

只要邮件里能稳定解析出姓名，就允许进入候选行程，不再做固定名单过滤。

抽取字段：
- 姓名
- 出发城市
- 目的城市
- 出发时间
- 返程时间（单程票 / 多段链式行程允许为空）

要求：
- 字段缺失即丢弃当前邮件，不得以空值混入正式结果。
- 对 booking 单程票 / 多段链式行程，`return_time` 允许为空；但 `姓名 / 出发城市 / 目的城市 / 出发时间` 必须存在。
- `normalize_city` 需兼容常见站点 / 机场后缀，例如 `上海虹桥 / 深圳北 / 杭州东 / 南通西` 应收敛到城市名。
- 识别规则优先参考 `references/mail-extraction-rules.md`。

### Stage 3｜合规字段计算 + 首次差旅地判定

新增 8 个字段：
- `booking_lead_days`
- `is_booked_before_approval`
- `is_over_cabin_policy`
- `is_hotel_over_policy`
- `over_policy_reason`
- `duplicate_booking_flag`
- `contains_weekend`
- `is_first_time_destination`

要求：
- `booking_lead_days` 由 `booking_time` 与 `departure_time` 推导。
- `is_booked_before_approval` 由 `booking_time` / `approval_time` 或正文关键词判定；若 booking 通道缺少审批证据，可保持 `null`。
- `is_over_cabin_policy`、`is_hotel_over_policy` 与 `over_policy_reason` 由正文字段 + 规则推导；拿不到证据时保持 `null / unknown` 可解释状态。
- `duplicate_booking_flag` 需结合相同人员、相近时间窗、相同目的地做检测。
- `contains_weekend` 需基于实际出发 / 返程区间判定，并进入合规健康度雷达与 `compliance_alerts` 聚合口径。
- `is_first_time_destination` 必须基于历史足迹库判定，不能只看当前批次。
- round-trip flight 尽量合并成单 trip；支持 reverse leg pairing，把 `A->B` 与 `B->A` 合并；hotel 邮件可作为补充证据 enrich transport trip，不必强行单独成 trip。
- 多段链式行程需先按 segment 粒度去重，再按 trip 聚类，避免一封 booking 邮件被重复入库。

### Stage 4｜经纬度解析 / 缓存

主脚本会对出发城市与目的城市做经纬度解析，并把结果缓存到 JSON 文件中。

要求：
- 目的地坐标解析是硬要求。
- 默认走脚本内置 geocoder，并把解析结果缓存到 `output/geo_cache.json`。
- 同一城市重复出现时优先命中缓存，不重复请求。
- 若个别城市无法解析，必须显式留空，不得伪造坐标。

### Stage 5｜生成结构化 JSON

主脚本最终产出的 JSON 必须满足 `references/dashboard-output-contract.md` 的结构契约。

推荐命令：

```bash
python3 scripts/build_travel_dashboard.py build \
  --mode auto \
  --output-json output/travel_dashboard.json \
  --output-html output/travel_dashboard.html \
  --geo-cache output/geo_cache.json \
  --footprint-library output/travel_footprint_library.json
```

要求：
- `generated_at`、`departure_time`、`return_time`、`booking_time`、`approval_time`、`source_sent_at` 统一输出为日期文本，避免前端与 QA 侧再做二次格式猜测。
- `compliance.metrics` 中必须包含 `contains_weekend` 健康度口径。
- `trips` 中若来自多段 booking 聚类，需保留稳定的 `trip_cluster_index` 以便前端渲染与 QA 复核。

### Stage 5.5｜生成 Email Ledger 审计台账（零信任 QA）

在需要做抓取范围复核、邮件分类审计或跨技能 QA 时，执行辅助脚本：

```bash
python3 scripts/build_mail_ledger.py \
  --months 1 \
  --output-json output/mail_ledger.json
```

要求：
- 邮件台账必须覆盖原始邮件摘要 + travel 分类证据，不能只保留聚合统计。
- 需要保留 `message_id / thread_id / subject / sender / sent_at / primary_category / classification_evidence / travel_record_count` 等审计字段。
- travel parser 命中与 fallback 分类都要可回溯，方便定位漏抓 / 误抓根因。
- `travel_booking` 不能再靠通用 `noreply / no-reply` 发送人单独命中；必须具备 booking 主题/正文硬信号或 parser 证据。
- `SSO / 验证码 / verification code / login verification / auth code` 这类认证邮件默认归入非 travel 类别，并在 evidence 中保留 guard 轨迹。

### Stage 6｜将 JSON 注入静态模板 / Dynamic UI 模板

若已经有 JSON，可只执行渲染：

```bash
python3 scripts/build_travel_dashboard.py render-html \
  --input-json output/travel_dashboard.json \
  --template assets/travel_dashboard_template.html \
  --output-html output/travel_dashboard.html
```

```bash
python3 scripts/build_travel_dashboard.py render-dynamic-ui \
  --input-json output/travel_dashboard.json \
  --template assets/travel_dashboard_dynamic_ui_template.html \
  --output-html output/travel_dashboard.dynamic.html
```

模板特征：
- 暗色标杆大屏风格。
- 顶部数据总览卡。
- ECharts 飞线总览。
- 目的地热度榜单。
- 合规健康度雷达。
- Gantt 差旅时间轴。
- 首次差旅地强提醒（地图红色高亮 / 时间轴呼吸灯）。
- 明细表。

### Stage 7.5｜说明层同步闸门（防代码领先文档）

凡是触达 `assets/travel_dashboard_template.html` 或 `assets/travel_dashboard_dynamic_ui_template.html` 的 UI 迭代，必须在同一轮提交中同步完成下面 4 个动作：

1. **变更三联单同步**：同时更新 `SKILL.md`、`CHANGELOG.md`、`README.lark.md`，确保版本号、标题与 UI 摘要一致。
2. **用户侧口径回归**：至少逐项核对 3 个用户可见锚点——文本换行是否已把原始 `\\n` 渲染为正常换行、`Message ID` 是否彻底下线、费用金额是否进入主卡常驻展示区。
3. **版本闸门**：若模板文件发生变化但说明层三个文件没有任何 diff，视为说明层断链，禁止进入归档流水线。
4. **发版证据回填**：在 `CHANGELOG.md` 中记录本次 UI 改动与验收口径，在 `README.lark.md` 中沉淀用户视角的结果描述，避免后续只剩代码痕迹没有使用说明。

推荐在发版前执行以下最小自检：

```bash
cd user_skills/team-travel-dashboard-generator && git diff -- assets/travel_dashboard_template.html SKILL.md CHANGELOG.md README.lark.md
```

若 diff 中只有模板文件而没有说明层文件，必须立刻熔断并补齐说明层。 

### Stage 8｜接入动态展示链路

若需要把 HTML 交给动态展示体系：

1. 先把最终 HTML 复制到动态展示目录，例如：

```bash
python3 scripts/build_travel_dashboard.py materialize-dynamic-ui \
  --input-html output/travel_dashboard.dynamic.html \
  --output-html ../../.aime/dynamic-ui/react-card/team_travel_dashboard_$(date +%s).html
```

2. 再按上层流程决定是否接入进一步展示链路。

注意：
- 本 skill 负责产出最终 HTML 成品和动态展示入口文件。
- 本次升级还要求把最新结果或链接打包成卡片 Payload，落盘到 `.ephemeral_pool/`，供主进程统一发射。

## 失败熔断与补救

- **邮箱权限缺失**：停止抓取，提示先完成飞书邮箱读权限授权，再重跑主命令。
- **字段抽取率低**：对照 `references/mail-extraction-rules.md` 补充 `FIELD_ALIASES` 或 booking 模板正则，优先修复姓名识别 / 路线拼装，而不是回退白名单。
- **合规字段缺证据**：保持 `null / 待人工复核` 这类可解释状态，不要编造金额、审批时间。
- **历史足迹库缺失**：立即初始化 `output/travel_footprint_library.json`，再继续计算首次差旅地。
- **HTML 渲染异常**：先验证模板中仍存在 `__TRAVEL_DASHBOARD_DATA__` 占位符，再检查 JSON 是否符合输出契约。
- **Email Ledger 误判**：若发现 `SSO / 验证码 / auth code` 仍被打进 travel 类目，优先检查 sender-only 命中、booking 硬信号护栏与 `classification_evidence` 是否保留了 `guard:*` 轨迹。

## 更新日志

- **V3.9**：新增飞书卡片发卡前 HTML 回捞防呆校验。
  - `build_travel_card_payload.py` 新增 `--deploy-html` 参数，默认回捞 `output/travel_dashboard.html`。
  - 卡片 `daily_new_alerts` 中每条新增预警必须能在即将部署的 HTML 中按“person + rule_type/trip type + date_range”命中。
  - 任一命中失败时输出 `[ALERT_MISMATCH] card alert not found in deploy HTML: {person} {date_range}` 并熔断，不生成/发送错位卡片。
- **V3.8**：新增飞书卡片 NEW 标签 lark_md 兼容降级。
  - V3.7 仍优先构造飞书原生 `tag` 组件，保持新版客户端的视觉表达。
  - 当创建卡片链路返回 `not support tag` 等组件兼容错误时，可用 `--new-label-style lark_md` 生成兼容 payload，把 NEW 渲染为 `**🆕 NEW**` 加粗文本。
  - 降级模式仍保持每条新增预警独立 element，不改快照 diff、邮件抓取、HTML 或 Dynamic UI 逻辑。
- **V3.7**：修复飞书卡片 NEW 标签静默降级问题。
  - `build_travel_card_payload.py` 改为逐条新增预警独立 element 渲染，NEW 使用飞书原生 `tag` 组件展示。
  - `assets/team_travel_dashboard_card_template.json` 回退为摘要模板，新增预警明细改为运行时动态注入，避免再把 badge 混在 markdown 正文里。
  - 本次仅修改卡片展示层；diff 逻辑、快照逻辑与 `is_new` 计算保持不变。
- **V3.6**：新增预警对象级 `is_new` 标记与 UI 高亮。
  - 快照 diff key 改为“人员姓名 + 预警类型 + 日期区间”三元组，生成稳定 `alert_key / alert_id`。
  - `compliance.alerts` 与 `compliance.daily_new_alerts.alerts` 中的新增项均带 `is_new=true`。
  - 静态 HTML 与 Dynamic UI 继续使用 `🆕 NEW` 文案高亮；飞书消息卡片在 V3.7 起切换为原生 `tag` NEW 标签，避免客户端把伪 badge 静默降级为普通正文。
- **V3.3**：补齐 UI 升级说明层，并加入“说明层同步闸门”。
  - `assets/travel_dashboard_template.html` 的文本详情渲染改为规范换行，用户侧不再暴露原始 `\\n`。
  - 明细视图移除 `Message ID` 调试字段，减少非业务噪音。
  - 费用金额抽取到主卡常驻展示区，关键成本信息无需展开明细即可首屏读取。
  - `SKILL.md` / `CHANGELOG.md` / `README.lark.md` 同步补齐版本与 UI 说明，并把“模板变更必须联动说明层”固化为发版闸门。
- **V3.2**：duplicate partial hotel 去重改为显式告警，保留所有疑似重复酒店孤儿单。
  - `deduplicate_records()` 不再对同一人 / 同一入住窗的 `record_status=partial` 酒店记录做字典静默覆盖。
  - 命中同一 dedup key 的多封酒店预订邮件会全部保留，并统一打上 `duplicate_booking_flag=true`、`needs_review=true` 与动态 `review_reason`。
  - 新增 `review_reason`、`duplicate_candidate_rank`、`duplicate_candidate_count`，用于保留人工核查语义与候选排序信息。
  - 以赵月晨 / 上海 / 06-04~06-05 样例回归，确认不再丢失 ¥737.49 酒店记录。
- **V3.1**：酒店孤儿单保留、差标接入框架与 booking pipeline 审计观测落地。
  - booking 酒店记录在无法匹配交通行程时，改为保留为 `record_status=partial` + `travel_context_missing=true` 的可审计记录。
  - 主脚本新增 `--hotel-policy-table`，酒店差标判定优先级固定为 `policy_table > mail_extract > email_fallback > unknown`。
  - 补齐 `hotel_policy_decision_source / policy_match_level / policy_rule_id / needs_review / hotel_policy_severity` 字段。
  - 输出 payload 升级为 `3.1`，新增 `audit.booking_pipeline`、`record_status_breakdown`、`partial_trips`、`travel_context_missing_count` 等观测字段。
  - 差标真相源确认落在飞书表 `https://bytedance.larkoffice.com/sheets/KF9Wsp1WZhviWZtrndXcqD0tnmp?sheet=eI7OnF`，并已将 `城市差标明细` 的 182 条规则回填为本地 `output/hotel_policy_rules.json`；全局配置工作表为 `sheet=0IsAjU`。
- **V2.8**：补齐 Email Ledger 分类护栏，修复 SSO / 验证码类非差旅邮件误判。
  - `travel_booking` 不再接受通用 `noreply / no-reply` 单独作为命中依据。
  - 新增 `SSO / 验证码 / verification code / login verification / auth code` 非差旅认证邮件熔断规则。
  - `classification_evidence` 中保留 `guard:*` 轨迹，便于复盘误判被拦截的原因。
- **V2.7**：定稿静态大屏模板，修复城市热度网络图渲染稳定性。
  - 将城市热度网络图节点坐标系从像素绝对值归一化为 `[0,1]` 比例坐标，避免不同容器尺寸下节点漂移。
  - 开启 `roam: 'scale'`，支持滚轮缩放查看网络细节。
  - 移除 `.network-panel` 区域的 `overflow:hidden` 裁切影响，通过专属覆写保证网络图完整显示。
- **V2.6**：补齐周末差旅合规口径、Email Ledger 零信任 QA 与多段链式行程细粒度去重说明。
  - 新增 `contains_weekend` 进入合规健康度雷达与 `compliance_alerts` 汇总口径。
  - 新增 `scripts/build_mail_ledger.py` 的审计台账工作流，用于 travel parser 命中复核与跨技能 QA。
  - 明确多段 booking 需先做 segment 去重，再做 trip 聚类，避免重复入库。
- **V2.3**：全面废弃 `reason` 字段，并将所有相关时间字段统一归一为 `YYYY-MM-DD`。
- **V2.2**：切换为 `ALL_PARSED_TRAVELERS` 全量抓取模式，兼容单程票 / 多段链式行程入库。
- **V2.1**：支持路线 B / booking 通道，兼容“员工商旅系统(请勿回复/no reply)”预订通知；新增 `approval / booking / auto` 模式、booking 查询词、reverse leg pairing、hotel enrich 与车站/机场城市归一化。
- **V2.0**：新增 6 个合规指标、历史足迹库与首次差旅地强提醒；静态 HTML / Dynamic UI 模板加入【合规健康度雷达】。
- **V1.1**：首版大屏生成能力上线，完成差旅审批邮件抓取、结构化抽取、地图 / Gantt 可视化与动态展示入口产出。

## 最佳实践

### 用户输入

```text
升级差旅大屏，加入合规字段和首次差旅地强提醒。
```

### 标准执行

1. 跑 `build` 子命令抓邮件并生成 `output/travel_dashboard.json`。
2. 同步生成 `output/travel_dashboard.html`、`output/travel_dashboard.dynamic.html`。
3. 更新 `output/travel_footprint_library.json`。
4. 把 Dynamic UI 入口或结果组装为卡片 Payload，落盘到 `.ephemeral_pool/`。

### 标准输出

- 结构化 JSON：近30天差旅行程数据 + 合规字段 + 周末差旅标记 + 首次差旅地标记。
- 暗色静态大屏 HTML：可直接打开查看。
- Dynamic UI 入口 HTML：可继续接展示链路。
- 历史足迹库：支持后续运行持续判定首次到达。
- Email Ledger 审计台账：供 travel parser 命中复核与零信任 QA。
- 卡片 Payload：供主进程统一发射。
