# 【技能说明】Weekly Top3 Patrol — 重要三件事周巡检与日历闭环

> **版本**：v1.4 ｜ **更新时间**：2026-06-08 ｜ **作者**：于奇楠 / Aime
>
> **风险等级**：High（涉及群内 @ 广播 + 日历强插写操作 + Bitable 读取）

## 📌 技能简介

每周「重要三件事」(Top3 Weekly Goals) 是 POP BD 团队的核心 OKR 节奏管理工具。本技能通过定时双模式巡检 + 自动化日历强插，确保团队成员按时填写 Top3，未填写者也能被强制拉到 1on1 同步状态。

- **数据源**：[Wiki 多维表格 — 重要三件事](https://bytedance.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV?sheet=uJkm4f)
- **豁免名单（代码硬过滤）**：`jiaoyanchen@bytedance.com` (焦彦晨) — 永久豁免
- **目标群聊**：`CHAT_REGISTRY.json -> task_patrol_broadcast`（即「UK/EU/JP POP BD」群）
- **触发节奏**：
  - **Mode A** — 每周日 16:00：软性催办，群内 @ 未填同学
  - **Mode B** — 每周一 16:00：硬性收口，调用 `feishu-calendar` 找共同空闲交集，自动强插 15min 1on1

## 🔑 触发词

- 核心关键词：
  - 重要三件事
  - 周巡检 / Top3 周巡检
  - weekly-top3-patrol
  - 催办日历
  - 1on1 强插
- 典型指令示例：
  > 跑一下 weekly-top3-patrol Mode A（dry-run）
  > 用 Top3 巡检看看本周谁没填，并强插 1on1
  > weekly-top3-patrol --mode B --week 2026-W22

## ⚙️ 核心架构 / SOP

### 架构概览

```
                Schedule Cron Trigger
                ├─ Mode A: 0 16 * * 0 (周日)
                └─ Mode B: 0 16 * * 1 (周一)
                        ↓
                 patrol.py 真实主入口
                        ↓
            ┌── 1. 读 CHAT_REGISTRY.json，断言群名
            ├── 2. 拉 Wiki Bitable 全量数据
            ├── 3. 扫描未填名单 + 豁免名单硬过滤
            └── 4. 路由 → Mode A 或 Mode B
                        ↓
        ┌───────────────┴────────────────┐
        ▼                                 ▼
    Mode A (软性)                    Mode B (硬性)
    feishu-im-send                   feishu-calendar
    L0 平铺 @ 未填同学                freebusy + create event
                                     + 群内总结通知
```

### Mode A — 周日 16:00 软性催办 SOP

1. 读 `CHAT_REGISTRY.json` 加载 `task_patrol_broadcast.chat_id`，断言群名含「UK/EU/JP POP BD」
2. 用 `managing-lark-bitable-data` 解析 Wiki URL → `app_token` → 拉取目标 sheet `uJkm4f` 全量记录
3. 应用 `exemption_filter.is_exempt(email)` 排除 `jiaoyanchen@bytedance.com`
4. 扫描未填记录：空字段 / 占位符 / 当周未提交 三选一判定
5. 通过 `feishu-im-send` 发送 L0 平铺消息（不允许 thread 盖楼）
6. 落盘日志至 `logs/patrol_<YYYY_WW>.json`

### Mode B — 周一 16:00 硬性收口 SOP

1. 重复 Mode A 步骤 1-4，得到未填同学名单 `pending_users[]`
2. 对每位 `pending_user`：
   - 调用 `feishu_calendar_freebusy` 查询当日 16:00-22:00 区间 `pending_user × yuqinan` freebusy
   - `find_common_slot(min_minutes=15)` 找首个 ≥15min 的共同空闲
   - 若找到 → `feishu_calendar_event.create` 强插日程：
     - summary: `[Top3 同步 / 强插] {pending_user.name} × yuqinan`
     - duration: 15min
     - attendees: `[pending_user.open_id, yuqinan.open_id]`
   - 若未找到 → 加入 `unresolvable[]`，跳过
3. 群内发送 Mode B 总结：成功强插列表 + 兜底名单
4. 落盘日志含 `event_id` / `booking_success` / `unresolvable[]`

### 调用入口

```bash
cd user_skills/weekly-top3-patrol

# Mode A (周日 16:00 软性催办)
python3 scripts/patrol.py --mode A --bitable "https://bytedance.sg.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV?sheet=uJkm4f" [--dry-run]

# Mode B (周一 16:00 硬性收口)
python3 scripts/patrol.py --mode B --bitable "https://bytedance.sg.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV?sheet=uJkm4f" [--dry-run]

# 真实执行（必须显式门禁）
python3 scripts/patrol.py --mode B --bitable "https://bytedance.sg.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV?sheet=uJkm4f" --confirm-real-send

# 三层护栏自检
python3 scripts/selfcheck.py
```

### 📅 Schedule 工具 Cron 配置建议

```yaml
# Mode A 软性催办
- name: weekly-top3-patrol-mode-A
  mode: cron
  cron_expression: "0 16 * * 0"   # 每周日 16:00
  message: "@Aime 跑 weekly-top3-patrol Mode A"
  stopped_at: "2026-11-21T16:00:00+08:00"  # 默认 180 天截止

# Mode B 硬性收口
- name: weekly-top3-patrol-mode-B
  mode: cron
  cron_expression: "0 16 * * 1"   # 每周一 16:00
  message: "@Aime 跑 weekly-top3-patrol Mode B"
  stopped_at: "2026-11-21T16:00:00+08:00"
```

## 🛡️ 约束条件与护栏

- **豁免名单代码硬过滤**：`exemption_filter.EXEMPT_EMAILS` 永久包含 `jiaoyanchen@bytedance.com`，严禁通过 CLI / 配置覆盖
- **群 ID SSOT**：必须从 `CHAT_REGISTRY.json` 读取，运行前 pre-flight 群名关键字断言（`UK/EU/JP POP BD`）
- **路由合规**：所有群消息走 `feishu-im-send` L0 平铺，禁止 LMT Thread 继承
- **Mode B 写日历前置**：`freebusy` → `find_common_slot` → `event.create` 顺序不可跳步
- **幂等性**：同一周对同一 `pending_user` 不重复创建日程（基于 `logs/patrol_<YYYY_WW>.json` 周度锁）
- **真实发送门禁**：所有非 dry-run 执行必须显式追加 `--confirm-real-send`
- **卡片渲染约束**：Mode B 强插列表必须渲染为“姓名：时间段”，禁止只显示裸时间
- **Dry-run 默认开启于测试**：所有发送/写入动作只输出 JSON 计划

## 📖 案例实录 (Best Practice)

- 🧑‍💻 **用户输入**：
  ```text
  @Aime 帮我跑一下本周的 Top3 周巡检，先看看 Mode A 谁还没填。
  ```

- 🤖 **标准输出（dry-run 节选）**：
  ```text
  ⏰ Weekly Top3 Patrol — Mode A (DRY RUN)
  Week: 2026-W22 (2026-05-25 ~ 2026-05-31)
  ChatID: oc_b566689fc5704ba70cc0f43fc32f0cc4 (UK/EU/JP POP BD) ✅
  Pending: 3 人（已剔除豁免名单 1 人：jiaoyanchen）
    - @张三 (zhangsan@..)  上次填写：2026-W21
    - @李四 (lisi@..)      上次填写：2026-W20
    - @王五 (wangwu@..)    上次填写：从未填写

  📤 待发送消息（L0 平铺，未真实发送）：
     [群] UK/EU/JP POP BD
     [文] @张三 @李四 @王五 本周 Top3 还未填写，请于今晚 23:59 前补齐 → <Wiki 链接>
  ```

## 🔌 依赖

- `inner_skills/managing-lark-bitable-data`：读 Wiki 多维表格
- `inner_skills/feishu-calendar`：freebusy 查询 + 日程创建
- `inner_skills/feishu-im-send`：群内 L0 平铺消息发送
- `CHAT_REGISTRY.json`：群 ID 单一真相源

## 🧪 验收清单

- ✅ `python3 scripts/selfcheck.py` 三层护栏 PASS
- ✅ `python3 tests/test_exemption_filter.py` 8/8 通过
- ✅ CDA Guardrails Selfcheck (--risk high) PASS
- ✅ Mode A / Mode B dry-run 可重现输出

## Changelog

### v1.4 — 2026-06-08（安全与渲染修复）

- 统一真实入口为 `scripts/patrol.py`，`run_patrol.py` 仅保留兼容转发。
- Mode B 增加基于 `logs/patrol_<YYYY_WW>.json` 的周度幂等锁，避免重复建会。
- 新增 `--confirm-real-send` 硬门禁，未显式确认禁止真实群发 / 写日历。
- 修复卡片渲染：Mode B 强插列表改为“姓名：时间段”绑定展示。
- 新增测试覆盖门禁、幂等锁与卡片渲染。

### v1.1 — 2026-05-25 (首次锻造)

- 双模式核心引擎：Mode A (软性催办) + Mode B (硬性收口)
- 代码层硬过滤：`jiaoyanchen` 永久豁免，含 L3 运行时 invariant
- CHAT_REGISTRY SSOT 加载器 + 群名关键字 pre-flight 断言
- 共同空闲交集算法（busy → free → intersect → first ≥15min slot）
- 三层护栏自检脚本 + 8 项豁免名单测试
- Schedule cron 配置建议（180 天默认截止）
