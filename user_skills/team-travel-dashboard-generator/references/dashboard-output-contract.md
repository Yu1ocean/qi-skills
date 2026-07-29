# 差旅大屏输出契约 V3.0

## JSON 契约

主脚本 `collect-mails` 或 `build` 产出的 JSON 结构如下：

```json
{
  "version": "3.0",
  "generated_at": "2026-06-08",
  "filters": {
    "months": 3,
    "mode": "auto",
    "query_terms": ["差旅审批", "【差旅】"],
    "capture_scope": "ALL_PARSED_TRAVELERS"
  },
  "summary": {
    "total_trips": 12,
    "active_people": 6,
    "ongoing_trips": 2,
    "unique_destinations": 7,
    "first_time_destinations": 3,
    "compliance_alerts": 5,
    "timeline_start": "2026-03-10",
    "timeline_end": "2026-06-01"
  },
  "rankings": {
    "departure_cities": [{"name": "上海", "value": 4}],
    "destination_cities": [{"name": "London", "value": 3, "first_time_count": 1}]
  },
  "compliance": {
    "metrics": {
      "booking_lead_days": {"known_count": 10, "avg_days": 6.3, "late_booking_count": 2, "healthy_rate": 80.0},
      "is_booked_before_approval": {"known_count": 9, "violation_count": 1, "healthy_rate": 88.9},
      "is_over_cabin_policy": {"known_count": 8, "violation_count": 1, "healthy_rate": 87.5},
      "is_hotel_over_policy": {"known_count": 6, "violation_count": 2, "healthy_rate": 66.7},
      "duplicate_booking_flag": {"known_count": 12, "violation_count": 1, "healthy_rate": 91.7},
      "contains_weekend": {"known_count": 12, "violation_count": 2, "healthy_rate": 83.3},
      "is_first_time_destination": {"known_count": 12, "first_time_count": 3, "attention_rate": 25.0}
    },
    "radar": [
      {"name": "提前预订", "field": "booking_lead_days", "value": 80.0},
      {"name": "周末差旅", "field": "contains_weekend", "value": 83.3}
    ],
    "alert_count": 5
  },
  "footprint_library": {
    "path": "output/travel_footprint_library.json"
  },
  "people": ["于奇楠"],
  "trips": [
    {
      "name": "于奇楠",
      "departure_city": "上海",
      "destination_city": "London",
      "departure_time": "2026-05-12",
      "return_time": "2026-05-15",
      "booking_time": "2026-05-01",
      "approval_time": "2026-05-02",
      "booking_lead_days": 11.0,
      "is_booked_before_approval": true,
      "is_over_cabin_policy": false,
      "is_hotel_over_policy": false,
      "over_policy_reason": "",
      "duplicate_booking_flag": false,
      "needs_review": false,
      "review_reason": "",
      "contains_weekend": false,
      "is_first_time_destination": true,
      "trip_cluster_index": 1,
      "departure_coord": {"lat": 31.2, "lon": 121.4},
      "destination_coord": {"lat": 51.5, "lon": -0.1},
      "source_message_id": "xxx"
    }
  ]
}
```

### 路线 B / booking 补充约束

- `filters.mode` 必须回显本次运行的 `approval / booking / auto` 之一。
- booking 记录的 `booking_time` 可以等于邮件发送时间；`approval_time` 允许为空字符串。
- round-trip flight / train 应尽量合并为单条 trip；允许通过 reverse leg pairing 把 `A->B` 与 `B->A` 合并。
- hotel 证据应优先 enrich transport trip；若无法可靠匹配 transport trip，必须保留为 `record_status=partial` 的酒店孤儿单，并打上 `travel_context_missing=true`，禁止静默丢弃。
- 若同一人 + 同一入住窗（`name + departure_city + destination_city + departure_time + return_time`）命中多封 `record_status=partial` 酒店预订邮件，去重层不得静默覆盖：必须保留全部候选，并统一打上 `duplicate_booking_flag=true`、`needs_review=true` 与动态 `review_reason`，说明“同一入住窗存在多封酒店预订邮件，需商旅后台人工核查”。
- 多段 booking 需先做 segment 粒度去重，再做 trip 聚类；同一趟出行不得因链式拆分被重复入库。
- `trip_cluster_index` 应稳定可复现，便于前端渲染与 QA 复核。
- 证据链建议保留 `source_channel`、`booking_template_type` 与 `source_message_ids`；至少要能回溯到原始邮件。
- 合规健康度在证据缺失时允许为 `null`，用来表达 `unknown`，不得用伪造值充数。
- 酒店差标判断优先级固定为：`policy_table > mail_extract > email_fallback > unknown`；所有酒店记录建议带 `hotel_policy_decision_source / policy_match_level / policy_rule_id / needs_review` 审计字段。
- 审计层与展示层必须分口径：`hotel_partial_candidate_retained` 表示邮件候选层保留的酒店孤儿单数量，`hotel_partial_retained` 表示最终 trip 去重后的 partial 数量，`hotel_partial_gap_after_dedup` 表示两层差值。
- 所有 trip 建议显式带 `needs_review` 与 `review_reason` 字段；当 partial hotel 命中重复预订待核查场景时，可额外带 `duplicate_candidate_rank / duplicate_candidate_count` 审计字段。

## Email Ledger 审计台账契约

默认文件：`output/mail_ledger.json`

用途：
- 复核邮件抓取时间窗内的真实命中范围。
- 为 travel parser 命中、fallback 规则与邮件分类结果提供证据回溯。
- 支撑跨技能零信任 QA，快速定位漏抓 / 误抓根因。

最少字段：
- `version`（当前为 `1.1`）
- `qa.purpose`
- `qa.travel_dashboard_skill_version`
- `message_id`
- `thread_id`
- `subject`
- `sender`
- `sender_email`
- `sent_at`
- `primary_category`
- `classification_evidence`
- `is_travel_related`
- `travel_channel`
- `travel_record_count`

## 历史足迹库契约

默认文件：`output/travel_footprint_library.json`

用途：
- 维护每个人已到访过的目的地集合。
- 支撑 `is_first_time_destination` 的跨轮运行判定。
- 至少保留 `first_seen_at`、`last_seen_at`、`count`、`source_message_ids` 等信息。

## HTML 结构

静态模板必须包含 6 个模块：
1. **数据总览**：6 张核心指标卡。
2. **ECharts 飞线总览**：基于出发城市与目的城市经纬度做飞线渲染。
3. **目的地热度**：Top 榜单，并对含首次差旅地的城市做特殊着色。
4. **合规健康度雷达**：展示 booking、审批、舱位、酒店、重复预订、周末差旅等合规指标健康度。
5. **Gantt 时间轴**：每位成员一行，展示出发-返程区间，并对首次差旅地做红色提醒。
6. **明细表**：展示线路、时间、预订提前天数、合规标签。

## 交付路径

推荐的文件路径：
- JSON：`output/travel_dashboard.json`
- 静态 HTML：`output/travel_dashboard.html`
- Dynamic UI HTML：`output/travel_dashboard.dynamic.html`
- 经纬度缓存：`output/geo_cache.json`
- 历史足迹库：`output/travel_footprint_library.json`
- Email Ledger：`output/mail_ledger.json`

## 动态展示链路

1. 先执行 `build` 或 `render-html` / `render-dynamic-ui` 生成最终 HTML。
2. 再把 Dynamic UI HTML 放到动态展示目录，例如：
   - `.aime/dynamic-ui/react-card/team_travel_dashboard_时间戳.html`
3. 再把结果或链接组装为卡片 Payload，落盘到 `.ephemeral_pool/`，由主进程统一发射。

## 验收标准

- JSON 中 `summary.total_trips` 与 `trips.length` 一致。
- 所有 `trips` 都带齐 4 个核心字段；对单程票 / 多段 booking 允许 `return_time` 为空。
- 所有 `trips` 都带齐 6 个基础合规字段 + `contains_weekend` + `is_first_time_destination`。
- 多段 booking 不得因 segment 拆分而产生重复 trip。
- Email Ledger 必须能回溯到 travel parser 命中的原始邮件。
- 有坐标的记录能正常绘制飞线。
- 首次差旅地在地图 / 时间轴上有红色强提醒。
- HTML 打开后至少能看到：头部概览、飞线图、目的地榜单、合规健康度雷达、Gantt 时间轴、明细表。
