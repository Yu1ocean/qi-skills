# 团队全景差旅大屏自动生成器（UK/EU/JP POP BD）｜交付报告

## TL;DR

本次已完成一个新的 user skill：`team-travel-dashboard-generator`。

它已经打通以下链路：
1. **差旅审批邮件抓取入口**：支持拉取近 3 个月审批邮件，并按固定 9 人名单过滤。
2. **结构化抽取链路**：抽取 `姓名 / 出发城市 / 目的城市 / 出发时间 / 返程时间 / 事由` 6 个核心字段，并补齐城市经纬度缓存。
3. **双层展示产物**：
   - 静态暗色大屏 HTML
   - dynamic-ui 可展示入口 HTML（已通过 build-check）
4. **正式锻造入库**：已完成 zip 打包、文档挂载、Wiki Mount、技能清单入库与 metadata 落盘。

---

## 1. 本次新增的核心资产

### 1.1 技能目录
- `user_skills/team-travel-dashboard-generator/`

### 1.2 主脚本
- `scripts/build_travel_dashboard.py`
- 支持子命令：
  - `collect-mails`
  - `render-html`
  - `render-dynamic-ui`
  - `build`
  - `materialize-dynamic-ui`

### 1.3 模板资产
- `assets/travel_dashboard_template.html`
  - 暗色系静态大屏模板
- `assets/travel_dashboard_dynamic_ui_template.html`
  - dynamic-ui 可展示模板（React 挂载版）

### 1.4 规则文档
- `references/mail-extraction-rules.md`
- `references/dashboard-output-contract.md`

### 1.5 示例验证资产（仅 smoke test）
- `output/travel_dashboard.sample.json`
- `output/travel_dashboard.sample.html`
- `.aime/dynamic-ui/card/team_travel_dashboard_dynamic_1780719608.html`

> 说明：以上 sample 仅用于页面渲染与展示链路验证，不代表真实业务邮件结果。

---

## 2. 已实现能力

### 2.1 邮件抓取
- 通过 `lark-cli mail +triage` 搜索近 3 个月差旅审批邮件。
- 通过 `lark-cli mail +messages` 拉取正文。
- 默认检索词：
  - `差旅审批`
  - `出差审批`
  - `travel approval`
  - `trip approval`
  - `差旅`

### 2.2 名单过滤
固定硬编码 9 人准入名单：
- 于奇楠
- 李京达
- 江家徽
- 李泽
- 夏春雨
- 黄忆卓
- 赵月晨
- 叶佳智
- 宋欣蕖

### 2.3 字段抽取
抽取并校验 6 个核心字段：
- 姓名
- 出发城市
- 目的城市
- 出发时间
- 返程时间
- 事由

缺字段邮件不会进入正式结果。

### 2.4 地理解析 / 缓存
- 对出发城市与目的城市做经纬度解析。
- 默认缓存到 `output/geo_cache.json`。
- 同城重复命中缓存，不重复请求。

### 2.5 可视化输出
已完成两套输出：
- **静态 HTML 大屏**：适合直接打开、挂网页或做截图汇报。
- **dynamic-ui 展示入口**：适合继续接 Aime 的展示链路。

---

## 3. 验证结果

### 3.1 代码与技能层验证
- `python3 -m py_compile`：通过
- `python3 scripts/build_travel_dashboard.py -h`：通过
- `quick_validate.py`：通过
- `cda_guardrails_selfcheck.py --risk auto`：通过

### 3.2 页面链路验证
- 静态 HTML 渲染：通过
- dynamic-ui 专用 HTML 生成：通过
- dynamic-ui `build-and-check.sh`：通过
- 编译产物已生成：
  - `.aime/dynamic-ui/card/team_travel_dashboard_dynamic_1780719608.html`

### 3.3 锻造 / 入库验证
- zip 打包：通过
- 技能说明文档创建：通过
- File Block 挂载：通过
- Wiki Mount：通过
- 技能清单入库：通过
- metadata 落盘：通过

---

## 4. 正式发布信息

- **Skill Name**: `team-travel-dashboard-generator`
- **Skill ID**: `TEAM-TRAVEL-DASHBOARD-GENERATOR`
- **Version**: `1.1`
- **Doc URL**: https://bytedance.larkoffice.com/docx/OJ4Xd5utOoVJbzxYgOEcQxycnHf
- **Wiki URL**: https://bytedance.larkoffice.com/wiki/GU0ewkyaGi4i5nkwBtNcM3aPn9g
- **Zip Path**: `user_skills/team-travel-dashboard-generator.zip`

---

## 5. 当前未完成的真实数据前置条件

当前**真实邮件抓取尚未做业务级回捞验证**，原因不是代码未完成，而是运行邮箱读权限尚未完成业务授权闭环。

我在前置探测时拿到的阻塞信息是：
- 缺少 `mail:user_mailbox:readonly` scope

这意味着：
- **技能本体已经 ready**
- **真实数据跑数还需要先完成飞书邮箱读取授权**

---

## 6. 建议的下一步

### Plan A｜直接真数验证
完成邮箱读权限授权后，执行：

```bash
python3 user_skills/team-travel-dashboard-generator/scripts/build_travel_dashboard.py build \
  --output-json output/travel_dashboard.json \
  --output-html output/travel_dashboard.html \
  --geo-cache output/geo_cache.json \
  --dynamic-ui-output ../../.aime/dynamic-ui/react-card/team_travel_dashboard_real_$(date +%s).html
```

### Plan B｜继续增强字段识别
如果后续发现审批邮件模板字段名和当前别名不完全一致，优先补：
- `FIELD_ALIASES`
- `mail-extraction-rules.md`

而不是放宽名单或允许空字段混入结果。

---

## 7. 结论

这次不是“只做了一个概念稿”，而是已经交付了一个**可注册、可入库、可生成 HTML、可接展示链路**的新技能。

剩下唯一的真机阻塞点，是**邮箱读权限授权**。一旦权限通了，这个技能就可以直接开始吐真实差旅大屏。