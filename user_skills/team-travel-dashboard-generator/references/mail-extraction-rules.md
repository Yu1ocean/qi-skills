# 差旅审批 / 预订邮件抽取规则 V2.6

## [红线] 数据源唯一性约束

**严禁任何形式的汇总表替代行为**：本技能的设计核心在于对“原始审批流”的实时捕获。严禁为了“解析方便”或“数据整齐”而将邮件手动汇总到 Excel / CSV / 飞书表格后再进行二次读取。
- **物理隔离**：脚本代码逻辑中严禁包含任何加载本地 `xlsx` / `csv` 汇总表的代码路径。
- **证据链路**：所有生成的 JSON 记录必须保留 `message_id` 或 `thread_id` 作为邮件原始证据。

## 目标

把近 3 个月的差旅审批邮件与商旅预订通知（路线 B），抽成两层字段：

### A. 5 个核心字段
- 姓名
- 出发城市
- 目的城市
- 出发时间
- 返程时间（单程票 / 链式行程允许为空）

### B. 6 个合规字段 + 2 个业务提醒字段
- `booking_lead_days`
- `is_booked_before_approval`
- `is_over_cabin_policy`
- `is_hotel_over_policy`
- `over_policy_reason`
- `duplicate_booking_flag`
- `contains_weekend`
- `is_first_time_destination`（由历史足迹库判定）

## 检索策略

主脚本支持 `approval / booking / auto` 三种模式：
- `approval`：
  - 差旅审批
  - 出差审批
  - travel approval
  - trip approval
  - 差旅
- `booking`：
  - 【差旅】
  - Hi Travel 火车票
  - 预订了机票
  - 预订了酒店
  - 员工商旅系统
- `auto`：同时覆盖 approval + booking。

如果团队邮件标题存在固定前缀，可额外通过 `--query` 追加更精准的词。

## 抓取范围约束

当前版本切换为 `ALL_PARSED_TRAVELERS`：
- 只要邮件标题或正文中能稳定解析出真实姓名，就允许进入候选行程。
- 不再依赖固定 9 人名单，不做名单外丢弃。

## 字段识别优先级

### 1. 标签对识别

优先按「标签: 值」模式识别字段，例如：
- 申请人：于奇楠
- 出发城市：上海
- 目的地：London
- 出发时间：2026-05-12 09:30
- 返程时间：2026-05-15 22:40
- 事由：客户拜访
- 预订时间：2026-05-01 10:00
- 审批通过时间：2026-05-02 18:00
- 舱位：商务舱
- 酒店差标：1200
- 超标原因：合作方指定酒店

### 2. 中英双语兼容

脚本默认同时识别：
- `申请人 / 姓名 / Applicant / Traveler`
- `出发城市 / 出发地 / Departure City / Origin`
- `目的城市 / 目的地 / Destination City / Destination`
- `出发时间 / 开始时间 / Departure Time / Start Time`
- `返程时间 / 结束时间 / Return Time / End Time`
- `事由 / 出差事由 / Reason / Purpose`
- `预订时间 / Booking Time / Booked At`
- `审批通过时间 / Approval Time / Approved At`
- `舱位 / Cabin Class`
- `席别 / Seat Class`
- `酒店单晚 / Hotel Rate`
- `酒店差标 / Hotel Standard / Policy Limit`
- `超标原因 / Exception Reason`

### 3. 路线 B / booking 模板识别

已知样本来自 `员工商旅系统(请勿回复/no reply)`，主题形如：
- `【差旅】某人预订了Hi Travel火车票 ...`
- `【差旅】某人 预订了机票 ...`
- `【差旅】某人预订了酒店 ...`

识别要求：
- 先用主题识别 `train / flight / hotel` 三类模板，再从正文补字段。
- `booking_time` 可直接使用邮件发送时间（`source_sent_at`）。
- `approval_time` 允许为空，拿不到就保持空值，不得回填伪造审批时间。
- `reason` 一律写入结构化占位值 `BOOKING_NOTICE_UNDISCLOSED`，表示“预订通知未披露”，不得伪造业务原因。
- `flight / train` 尽量按往返段合并成单 trip；支持 reverse leg pairing，把 `A->B` 与 `B->A` 合并。
- `hotel` 邮件可以作为同目的地 transport trip 的补充证据 enrich 酒店金额/差标字段，不必强行单独成 trip。

### 4. 时间解析

支持以下常见格式：
- `2026-05-12 09:30`
- `2026/05/12 09:30`
- `2026年05月12日 09:30`
- `2026-05-12`

统一输出为 `YYYY-MM-DD HH:MM`。

### 5. 城市归一化

`normalize_city` 需要兼容常见站点 / 机场后缀，至少覆盖：
- `上海虹桥 -> 上海`
- `深圳北 -> 深圳`
- `杭州东 -> 杭州`
- `南通西 -> 南通`

对无法可靠收敛的地点，不要编造城市名；宁可保持空值并让该条记录在校验阶段被丢弃。

## 合规字段判定规则

1. `booking_lead_days`
   - 使用 `booking_time` 与 `departure_time` 的差值（天）计算。
   - booking 通道若只识别到邮件发送时间，也允许直接用该发送时间作为 `booking_time`。
2. `is_booked_before_approval`
   - 优先比较 `booking_time < approval_time`。
   - 若正文明确出现“先订后批 / 审批前预订”等关键词，也判定为 `true`。
   - 若 booking 通道没有审批时间证据，则保持 `null`，不要默认 `false`。
3. `is_over_cabin_policy`
   - 优先识别显式字段；若出现“商务舱 / 头等舱 / 超级经济舱 / 商务座 / 一等座”等关键词，也判定为超标风险。
4. `is_hotel_over_policy`
   - 优先识别显式字段；若已拿到酒店单晚与差标金额，则以金额比较判定。
5. `over_policy_reason`
   - 优先读取正文显式字段。
   - 若正文只出现关键词，则归一化到常见桶：合理安置 / 健康原因 / 无经济舱(标准房) / 合作方指定 / 不可抗力。
6. `duplicate_booking_flag`
   - 同一人员、相同目的地、相近出发时间窗（48h 内）或行程区间重叠时，标记为重复预订风险。
7. `is_first_time_destination`
   - 不从单封邮件直接抽取。
   - 必须读取历史足迹库，判断该人员此前是否到过该目的地。

## 熔断规则

满足任一条件，当前邮件不得入库：
1. 姓名无法稳定解析。
2. `姓名 / 出发城市 / 目的城市 / 出发时间` 任一缺失。
3. 时间字段无法解析。
4. 出发城市或目的城市为空。

## 零信任补充约束

- 未在邮件中明确披露的字段，一律不要编造。
- 提取逻辑中所有的相关时间字段（departure_time, booking_time, return_time, approval_time, source_sent_at）必须统一转换为 `YYYY-MM-DD` 格式。
- **全面废弃“事由”字段**：提取和落库逻辑中不再包含 `reason`。
- 合规指标拿不到证据时，保持 `null / unknown / 待人工复核` 的可解释状态。
- hotel 只能补充已有 transport trip 的证据链，不能为了凑齐数据强造一条独立 trip。
- 多段 booking 需先做 segment 粒度去重，再做 trip 聚类；同一封邮件内相同路线 / 时间的 segment 不得重复入库。
- `contains_weekend` 必须基于完整出发 / 返程区间判定，不能只看单个出发日期。
- 如需做零信任 QA，必须额外运行 `scripts/build_mail_ledger.py`，保留 travel parser 命中范围与分类证据回溯。

## 调试建议

如果发现抽取率偏低：
1. 先把 `source_subject` 和 `raw_excerpt` 输出到本地 JSON 查看原始结构。
2. 对比邮件里的真实字段标签，补充 `FIELD_ALIASES`。
3. 若邮件正文是强结构表格，可优先增强「标签对识别」而不是回退到白名单过滤。
4. 若首次差旅地判定异常，先检查 `output/travel_footprint_library.json` 是否成功落盘并持续更新。
