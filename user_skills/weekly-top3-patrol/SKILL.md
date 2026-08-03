---
name: weekly-top3-patrol
version: 1.6.1
updated_at: "2026-08-03"
risk_level: high
description: 每周「重要三件事」进展巡检与自动化催办日历闭环。Mode A 软性催办（周日 16:00 群内 @ 未填写同学），Mode B 硬性收口（周一 16:00 调用飞书日历找空闲交集自动占位 15min 1on1）。
trigger_keywords:
  - 重要三件事
  - 周巡检
  - top3 巡检
  - top3 catchup
  - 催办日历
  - 1on1 强插
  - weekly-top3-patrol
---

# Weekly Top3 Patrol — 重要三件事周巡检与日历闭环

> **版本**：1.6.1 · **更新时间**：2026-08-03
> **作者**：于奇楠 / Aime
> **风险等级**：High（涉及群内 @ 广播 + 日历强插写操作 + 飞书 Bitable 读取）

---

## Common Rationalizations（常见借口库）

以下借口出现即视为"准备绕过护栏"，必须立刻熔断：

- "豁免名单先不写死，下次再补。" → ❌ 必须代码层硬过滤 `jiaoyanchen@bytedance.com`。
- "群 ID 我从历史日志拿一下就行。" → ❌ 必须从 `CHAT_REGISTRY.json` 单一真相源读取。
- "找不到共同空闲就先随便插一个时间吧。" → ❌ 必须熔断并发卡在群里同步状态，禁止盲插。
- "日历强插我先 dry-run 一下，跑通再说。" → ❌ Mode B 实操前必须经过 `--dry-run` 预演 + 用户口令确认。
- "巡检结果重复发一遍也无妨，反正是提醒。" → ❌ 必须做幂等性校验（同周同名单不重复触发）。
- "先切真实发送试一下，回头再补门禁。" → ❌ 非 dry-run 一律必须显式携带 `--confirm-real-send`。

## Red Flags（危险信号）

- 豁免名单未通过代码硬过滤，仅依赖配置文件或上下文。
- `CHAT_REGISTRY.json` 校验失败（群名关键字不匹配）后仍继续广播。
- Mode B 在用户/Aime 主账号 `freebusy` 拉取失败时回退到"硬插任意时间"。
- 自动创建的日历事件未把 `yuqinan@bytedance.com` 列为参会人。
- 输出中出现"应该 / 大概 / 我猜 / 先跳过 freebusy"等措辞。

## Verification（强制验收清单）

宣称"巡检完成"前必须满足：

1. **自检脚本通过**：`scripts/selfcheck.py` 退出码为 0，输出三层护栏 OK。
2. **CDA 自检通过**：`skill-forge-pipeline-v4/scripts/cda_guardrails_selfcheck.py --risk high` 退出码 0。
3. **豁免名单测试通过**：`tests/test_exemption_filter.py` 全部用例通过，确认 `jiaoyanchen` 永远被排除。
4. **群 ID 单一真相源**：群 ID 来自 `CHAT_REGISTRY.json` 中 `task_patrol_broadcast` 节点；运行前已做 pre-flight 群名关键字断言（`UK/EU/JP POP BD`）。
5. **Mode A dry-run 样例**：`python3 scripts/patrol.py --mode A --bitable "<生产源表URL>" --dry-run` 输出包含 `@username`、未填写名单、是否已豁免日志。
6. **Mode B dry-run 样例**：`python3 scripts/patrol.py --mode B --bitable "<生产源表URL>" --dry-run` 输出每位未填写同学与 `yuqinan` 的共同空闲交集（15min），且已生成"待写入"日历草稿。
7. **真实发送门禁**：任何非 dry-run 调用必须显式携带 `--confirm-real-send`，否则主入口直接熔断。
8. **路由合规**：群内催办消息走 `feishu-im-send`（L0 平铺），禁止 LMT Thread 继承。

---

## 📌 技能简介

每周三件事（Top3 Weekly Goals）是 POP BD 团队的核心 OKR 节奏管理工具。本技能通过定时双模式巡检 + 自动化日历强插，确保团队成员按时填写 Top3，未填写者也能被强制拉到 1on1 同步状态：

- **数据源**：Wiki 多维表格 `https://bytedance.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV?sheet=uJkm4f`
- **巡检范围**：扫描"未填写人员"（关键字段为空 / 占位符为默认值 / 当前周次未提交）
- **豁免名单**（代码硬过滤）：`jiaoyanchen@bytedance.com` (焦彦晨)、`gaochuan.cherry@bytedance.com` (Cherry Gao)、`wanghaotian.666@bytedance.com` (王皓田)、`huangyizhuo.1992@bytedance.com` (黄忆卓 Amy)
- **目标群聊**：`CHAT_REGISTRY.json -> task_patrol_broadcast`（即"UK/EU/JP POP BD"群）
- **触发节奏**：
  - Mode A — 周日 16:00：软性催办（群内 @ 未填同学，提示当周截止）
  - Mode B — 周一 16:00：硬性收口（调用 `feishu-calendar` 查找未填同学与 `yuqinan` 的共同空闲，自动插入 15min 1on1，并群内通知）

### 更新日志（Changelog）

#### 2026-08-03 (v1.6.1)

- fix(tests): 补全 fallback fixture 至 2 人满足 ROSTER_MIN_COUNT=2 阈值；新增 ERROR_ROSTER_EMPTY 熔断契约用例。

#### 2026-08-03 (v1.6)

- `load_team_roster()` 新增字段兼容映射：`姓名` 归一为 `中文名称`，`open_id` 归一为 `Open ID`，兼容新旧名单表头且不改变后续巡检逻辑。
- 团队名单读取后若人数低于 `WEEKLY_TOP3_ROSTER_MIN_COUNT`（默认 2）立即熔断，日志状态写入 `ERROR_ROSTER_EMPTY`，禁止继续输出 `pending_users: []` 或发送卡片。
- 巡检日志新增 `raw_evidence` 字段，记录 `roster_count`、`owner_blocks_count`、`complete_users`、`absent_users`、`week_marker`、`fallback_reason`，用于区分全部已填、缺席漏判与查询失败。

#### 2026-05-25 (v1.1)

- 首次锻造发布。集成 Mode A/B 双模式、豁免名单硬过滤、CHAT_REGISTRY 单一真相源、Mode B 共同空闲交集寻址、Schedule 工具 cron 配置建议。

---

## 🔑 触发词

- **核心关键词**：重要三件事 / Top3 周巡检 / weekly-top3-patrol / 催办日历 / 1on1 强插
- **典型指令示例**：
  > 跑一下 weekly-top3-patrol Mode A（dry-run）
  > 用 Top3 巡检看看本周谁没填，并强插 1on1
  > weekly-top3-patrol --mode B --week 2026-W22

---

## ⚙️ 核心架构与 SOP

### 架构概览

```
                  ┌────────────────────────────────────┐
                  │  Schedule Cron Trigger             │
                  │  - Mode A: 0 16 * * 0 (Sunday)     │
                  │  - Mode B: 0 16 * * 1 (Monday)     │
                  └────────────────┬───────────────────┘
                                   ▼
                  ┌────────────────────────────────────┐
                  │  scripts/patrol.py                 │
                  │  ┌──────────────────────────────┐  │
                  │  │ 1. 读 CHAT_REGISTRY.json     │  │
                  │  │    断言群名关键字            │  │
                  │  ├──────────────────────────────┤  │
                  │  │ 2. 拉 Wiki Bitable 数据      │  │
                  │  │    via managing-lark-bitable │  │
                  │  ├──────────────────────────────┤  │
                  │  │ 3. 扫描未填写名单            │  │
                  │  │    + 豁免名单硬过滤          │  │
                  │  ├──────────────────────────────┤  │
                  │  │ 4. 路由至 Mode A or Mode B   │  │
                  │  └──────────────────────────────┘  │
                  └────────────────┬───────────────────┘
                          ┌────────┴────────┐
                          ▼                 ▼
                ┌──────────────┐    ┌─────────────────────┐
                │  Mode A      │    │  Mode B             │
                │  软性催办    │    │  硬性收口           │
                │              │    │                     │
                │  feishu-im-  │    │  feishu-calendar    │
                │  send (L0)   │    │  freebusy + create  │
                │  @ 未填同学  │    │  + im-send 通知     │
                └──────────────┘    └─────────────────────┘
```

### Mode A — 周日 16:00 软性催办 SOP

1. 读 `CHAT_REGISTRY.json` 加载 `task_patrol_broadcast.chat_id`（断言群名含 `UK/EU/JP POP BD`）。
2. 用 `managing-lark-bitable-data` 解析 Wiki URL → `app_token` → 拉取目标 sheet `uJkm4f` 全量记录。
3. 应用 `exemption_filter.is_exempt(email)` 排除代码层豁免名单（当前含 `jiaoyanchen@bytedance.com`、`gaochuan.cherry@bytedance.com`、`wanghaotian.666@bytedance.com`、`huangyizhuo.1992@bytedance.com`）。
4. 扫描未填写记录：判定标准在 `references/empty_detection_rules.md`（空字段 + 占位符 + 当周未提交三选一）。
5. 通过 `feishu-im-send` 发送 L0 平铺消息（不允许 thread 盖楼），格式：
   - 标题：⏰ 周日重要三件事软性催办 (Mode A)
   - 正文：@ 未填同学 + 当周截止时间 + 表格直达链接
6. 落盘日志至 `logs/patrol_<YYYY_WW>.json`。

### Mode B — 周一 16:00 硬性收口 SOP

1. 重复 Mode A 步骤 1-4，得到未填同学名单 `pending_users[]`。
2. 对每位 `pending_user`：
   - 调用 `feishu_calendar_freebusy` 查询当日 16:00-22:00 区间内 `pending_user` 与 `yuqinan` 的 freebusy。
   - 用 `interval_intersect.find_common_slot(min_minutes=15)` 找到第一个 ≥15min 的共同空闲交集。
   - 若找到 → 调用 `feishu_calendar_event.create` 创建日程：
     - summary: `[Top3 同步 / 强插] {pending_user.name} × yuqinan`
     - duration: 15min
     - attendees: `[pending_user.open_id, yuqinan.open_id]`
     - description: 包含 Wiki Bitable 链接 + 自动化原因说明
   - 若未找到（24h 内 0 共同空闲） → 加入 `unresolvable[]` 名单，跳过本人创建。
3. 通过 `feishu-im-send` 在群内发送 Mode B 总结：
   - 已成功强插的 1on1 列表（含日历直达链接）
   - 未找到共同空闲的兜底名单 + 提示手动协调
4. 落盘日志至 `logs/patrol_<YYYY_WW>.json`，含 `event_id`、`booking_success`、`unresolvable[]`。

### 调用入口

```bash
# Mode A（周日 16:00 软性催办）
cd user_skills/weekly-top3-patrol
python3 scripts/patrol.py --mode A --bitable "https://bytedance.sg.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV?sheet=uJkm4f" [--dry-run]

# Mode B（周一 16:00 硬性收口）
python3 scripts/patrol.py --mode B --bitable "https://bytedance.sg.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV?sheet=uJkm4f" [--dry-run]

# 真实发送 / 真写日历（必须显式门禁）
python3 scripts/patrol.py --mode B --bitable "https://bytedance.sg.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV?sheet=uJkm4f" --confirm-real-send

# 自检（必须在每次升级后跑通）
python3 scripts/selfcheck.py
```

---

## 🛡️ 约束条件与护栏

- **豁免名单代码硬过滤**：`scripts/exemption_filter.py` 中 `EXEMPT_EMAILS` 常量永久包含 `jiaoyanchen@bytedance.com`，并维护当前业务豁免项（含 `huangyizhuo.1992@bytedance.com`），严禁通过 CLI 参数或配置文件覆盖。
- **群 ID SSOT**：所有 `chat_id` 必须从 `CHAT_REGISTRY.json` 读取，禁止从历史 / 缓存 / 上下文猜测；运行前 pre-flight 群名关键字断言（`UK/EU/JP POP BD`）。
- **路由合规**：群内催办与总结消息均走 `feishu-im-send` L0 平铺；禁止 LMT Thread 继承；payload 落盘到 `/workspace/.ephemeral_pool/[TASK_ID]_top3_patrol.card.json`。
- **Mode B 写日历前置条件**：必须先 `freebusy` 验证 → `find_common_slot` → `event.create`，缺一不可；任何一步失败立即熔断并落盘 unresolvable。
- **幂等性**：同一周（ISO Week）内对同一 `pending_user` 不重复创建日程；使用 `logs/patrol_<YYYY_WW>.json` 做去重锁。
- **真实发送门禁**：所有非 dry-run 执行都必须显式追加 `--confirm-real-send`，否则主入口直接熔断。
- **卡片渲染约束**：Mode B 的“强插日程列表”必须展示为“姓名：时间段”绑定格式，禁止只渲染裸时间。
- **Dry-run 默认开启于测试**：在 `--dry-run` 模式下，所有发送 / 写入动作只输出 JSON 计划，不真实落地。
- **失败降级**：Bitable 拉取失败 → 写 DLQ + 告警；Calendar 写入失败 → 该用户进入 unresolvable 列表，不影响其他用户。

---

## 📅 Schedule 工具 Cron 挂载建议

```yaml
# Mode A 软性催办
- name: weekly-top3-patrol-mode-A
  mode: cron
  cron_expression: "0 16 * * 0"   # 每周日 16:00
  message: "@Aime 跑 weekly-top3-patrol Mode A，巡检本周重要三件事未填名单并群内软性催办"
  stopped_at: "2026-11-21T00:00:00+08:00"   # 180 天默认截止
  target: main

# Mode B 硬性收口
- name: weekly-top3-patrol-mode-B
  mode: cron
  cron_expression: "0 16 * * 1"   # 每周一 16:00
  message: "@Aime 跑 weekly-top3-patrol Mode B，对未填名单做 freebusy 共同空闲交集查找并自动强插 15min 1on1"
  stopped_at: "2026-11-21T00:00:00+08:00"
  target: main
```

---

## 📖 案例实录 (Best Practice)

- 🧑‍💻 **用户输入**：

  ```text
  @Aime 帮我跑一下本周的 Top3 周巡检，先看看 Mode A 谁还没填。
  ```

- 🤖 **标准输出（dry-run）**：

  ```text
  ⏰ Weekly Top3 Patrol — Mode A (DRY RUN)
  Week: 2026-W22 (2026-05-25 ~ 2026-05-31)
  ChatID: oc_b566689fc5704ba70cc0f43fc32f0cc4 (UK/EU/JP POP BD) ✅ 群名断言通过
  Pending: 3 人（已剔除豁免名单 1 人：jiaoyanchen）
    - @张三 (zhangsan@..)  上次填写：2026-W21
    - @李四 (lisi@..)       上次填写：2026-W20
    - @王五 (wangwu@..)     上次填写：从未填写

  📤 待发送消息（L0 平铺，未真实发送）：
     [群] UK/EU/JP POP BD
     [文] @张三 @李四 @王五 本周 Top3 还未填写，请于今晚 23:59 前补齐 → <Wiki 链接>
  ```

---

## 🔌 依赖

- `inner_skills/managing-lark-bitable-data`：读 Wiki 多维表格
- `inner_skills/feishu-calendar`：freebusy 查询 + 日程创建
- `inner_skills/feishu-im-send`：群内 L0 平铺消息发送
- `CHAT_REGISTRY.json`：群 ID 单一真相源
