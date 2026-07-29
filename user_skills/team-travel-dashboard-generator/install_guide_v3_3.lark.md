## 技能简介

`team-travel-dashboard-generator` 用于把差旅审批邮件与商旅预订通知自动沉淀为结构化差旅资产，并进一步生成团队差旅大屏。

当前最新状态已对齐到 **V3.3**：
- 默认全量抓取可识别姓名的邮件，不再依赖固定名单。
- 兼容单程票、多段链式行程、booking 路线与 Email Ledger 审计台账。
- UI 说明层已同步补齐：详情换行规范化、`Message ID` 调试字段下线、费用金额进入主卡常驻展示区。

<callout icon="bulb" bgc="5">  
  **一句话理解：** 这是一个把“差旅邮件 → 结构化 JSON → 静态 HTML / Dynamic UI 大屏 → 审计台账 QA”串成一条龙的自动化技能，适合做团队差旅巡检、周会大屏与合规风险扫描。  
</callout>

## 版本信息

<table header-row="true" header-col="false" col-widths="180,220,420">  
  <tr>  
    <td>字段</td>  
    <td>当前值</td>  
    <td>说明</td>  
  </tr>  
  <tr>  
    <td>技能名称</td>  
    <td>`team-travel-dashboard-generator`</td>  
    <td>差旅大屏自动生成技能</td>  
  </tr>  
  <tr>  
    <td>当前版本</td>  
    <td>V3.3</td>  
    <td>已完成 UI 说明层补档与发版闸门固化</td>  
  </tr>  
  <tr>  
    <td>主脚本</td>  
    <td>`scripts/build_travel_dashboard.py`</td>  
    <td>负责抓邮件、解析、生成 JSON/HTML/Dynamic UI</td>  
  </tr>  
  <tr>  
    <td>审计脚本</td>  
    <td>`scripts/build_mail_ledger.py`</td>  
    <td>负责产出 `output/mail_ledger.json` 做零信任 QA</td>  
  </tr>  
  <tr>  
    <td>固定大屏入口</td>  
    <td>[差旅大屏固定地址](https://216a3e1709fd.aime-app.bytedance.net/)</td>  
    <td>技能配置中登记的固定 Dashboard URL</td>  
  </tr>  
</table>

## 前置条件

在安装或运行前，请先满足以下条件：

1. 已具备 Aime Skill 安装权限。
2. 本地环境可执行 `python3`。
3. 邮件抓取场景下，本地可执行 `lark-cli mail +triage` 与 `lark-cli mail +messages`。
4. 运行邮箱已具备飞书邮箱只读权限 `mail:user_mailbox:readonly`。
5. 如需酒店差标比对，建议准备好差标表数据来源或对应参数。

<callout icon="first_place_medal" bgc="3">  
  **重要提醒：** 这个技能的正式数据源是**原始差旅邮件**，不是 Excel、CSV 或飞书汇总表。若邮箱权限未开通，可以先完成安装与脚本校验，再补授权跑真数。  
</callout>

## 安装命令

如果你要在 Aime 环境中安装这个技能，推荐按下面顺序执行：

```bash
aime skill pack ./user_skills/team-travel-dashboard-generator -o /tmp
aime skill upload /tmp/team-travel-dashboard-generator.zip
aime skill enable team-travel-dashboard-generator
```

如果你已经有打好的 zip 包，也可以直接上传后启用：

```bash
aime skill upload /path/to/team-travel-dashboard-generator.zip
aime skill enable team-travel-dashboard-generator
```

安装完成后，可先用下面命令做最小探针：

```bash
cd user_skills/team-travel-dashboard-generator
python3 scripts/build_travel_dashboard.py -h
python3 scripts/build_mail_ledger.py -h
```

## 快速上手命令

### 1）仅抓邮件并生成 JSON：`collect-mails`

适合先验证抓取链路、字段抽取与结构化结果。

```bash
cd user_skills/team-travel-dashboard-generator
python3 scripts/build_travel_dashboard.py collect-mails \
  --mode auto \
  --output-json output/travel_dashboard.json \
  --geo-cache output/geo_cache.json \
  --city-alias-cache output/city_alias_cache.json \
  --footprint-library output/travel_footprint_library.json
```

### 2）全链路生成差旅大屏：`build`

适合直接产出 JSON + 静态 HTML + Dynamic UI 入口。

```bash
cd user_skills/team-travel-dashboard-generator
python3 scripts/build_travel_dashboard.py build \
  --mode auto \
  --output-json output/travel_dashboard.json \
  --output-html output/travel_dashboard.html \
  --geo-cache output/geo_cache.json \
  --city-alias-cache output/city_alias_cache.json \
  --footprint-library output/travel_footprint_library.json \
  --dynamic-ui-output output/travel_dashboard.dynamic.html
```

### 3）基于已有 JSON 重新渲染静态 HTML：`render-html`

适合你已经有结构化结果，只想重刷页面模板的场景。

```bash
cd user_skills/team-travel-dashboard-generator
python3 scripts/build_travel_dashboard.py render-html \
  --input-json output/travel_dashboard.json \
  --template assets/travel_dashboard_template.html \
  --output-html output/travel_dashboard.html
```

### 4）生成邮件审计台账：`build_mail_ledger`

适合做 travel parser 命中复核、误抓排查和零信任 QA。

```bash
cd user_skills/team-travel-dashboard-generator
python3 scripts/build_mail_ledger.py \
  --months 1 \
  --output-json output/mail_ledger.json
```

## 典型产物说明

<table header-row="true" header-col="false" col-widths="260,250,390">  
  <tr>  
    <td>产物</td>  
    <td>默认路径</td>  
    <td>用途</td>  
  </tr>  
  <tr>  
    <td>结构化主数据</td>  
    <td>`output/travel_dashboard.json`</td>  
    <td>包含 trips、summary、合规字段、首次差旅地等主结果</td>  
  </tr>  
  <tr>  
    <td>静态大屏</td>  
    <td>`output/travel_dashboard.html`</td>  
    <td>适合直接打开、挂网页或汇报演示</td>  
  </tr>  
  <tr>  
    <td>Dynamic UI 入口</td>  
    <td>`output/travel_dashboard.dynamic.html`</td>  
    <td>适合继续接动态展示链路</td>  
  </tr>  
  <tr>  
    <td>邮件审计台账</td>  
    <td>`output/mail_ledger.json`</td>  
    <td>用于 travel 分类统计、邮件证据回溯与 QA</td>  
  </tr>  
  <tr>  
    <td>历史足迹库</td>  
    <td>`output/travel_footprint_library.json`</td>  
    <td>用于跨轮运行判定 `is_first_time_destination`</td>  
  </tr>  
  <tr>  
    <td>城市缓存</td>  
    <td>`output/geo_cache.json`</td>  
    <td>缓存地理解析结果，避免重复请求</td>  
  </tr>  
</table>

## 验收清单

以下验收项直接对齐当前 SKILL.md 的 Verification 口径，安装完成后建议逐项过一遍：

1. 主脚本 `scripts/build_travel_dashboard.py` 可正常执行 `-h`。
2. `collect-mails` 或 `build` 产出的 JSON 中，`summary.total_trips == trips.length`。
3. 每条 `trips` 记录都带齐 4 个核心字段：`姓名 / 出发城市 / 目的城市 / 出发时间`；对单程票 / 多段 booking 允许 `return_time` 为空。
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
8. 静态 HTML 能渲染出：数据总览、飞线总览、目的地热度、合规健康度雷达、Gantt 时间轴、明细表。
9. V3.3 UI 回归通过：文本换行已做规范化渲染，不再出现原始 `\\n`；行程详情不再展示 `Message ID`；费用金额已进入主卡常驻展示区。
10. Dynamic UI 入口 HTML 可正常生成，且地图 / 时间轴对首次差旅地做了强提醒。
11. `SKILL.md`、`CHANGELOG.md`、`README.lark.md` 中的版本号、UI 变更摘要与执行口径一致。

## 建议使用顺序

<grid cols="2">  
<column width="50">  
  **第一次安装建议这样跑：**  
  
  1. 先执行 `-h` 校验脚本可用。  
  2. 再跑 `collect-mails` 验证邮件抓取与 JSON 结构。  
  3. 最后跑 `build` 生成完整大屏。  
</column>  
<column width="50">  
  **当你要排查误抓或漏抓时：**  
  
  1. 跑 `build_mail_ledger.py`。  
  2. 看 `output/mail_ledger.json` 的分类证据与 parser 命中。  
  3. 再回头修抽取规则，而不是拿 Excel 临时兜底。  
</column>  
</grid>

## 结论

这个技能目前**已经更新到最新状态（V3.3）**，并且版本号、变更日志、README 说明层已经同步对齐。你可以直接按本文档完成安装，并用 `collect-mails / build / render-html / build_mail_ledger` 四组命令快速完成首轮验证。