# 团队全景差旅大屏自动生成器（UK/EU/JP POP BD）

<figure view-type="Card"><source name="team-travel-dashboard-generator.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ODE4NWVjOWFmZTI5Y2EwZWRiODlmODhmMTBhN2EyNzFfOGNjMWJiOWVjMTQ3N2RlNmNlYmNmOTllNjNiMGVhODZfSUQ6NzY0ODgzNTIwNjQ1NTEwMjcwN18xNzg2OTM2ODI4OjE3ODY5NDA0MjhfVjM" mime="application/zip" size="415575" token="HkuObInS7o0sK7xp9b1ccp8Nnud"/></figure>

<figure view-type="Card"><source name="team-travel-dashboard-generator.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MzcxMGY5ZGFhYWZmNjM0Mzc4OGVhZWEyMWZjZThjYmFfNmIzZDY3YWFjNjM5OTUwNjVjMjA5MjMwYjE0OGVkMWFfSUQ6NzY0ODE0MDU5MDI4MjExNjMxN18xNzg2OTM2ODI4OjE3ODY5NDA0MjhfVjM" mime="application/zip" size="64472" token="Sh2sblmkgoTQOWxOOEbcaMSFnBg"/></figure>

<figure view-type="Card"><source name="team-travel-dashboard-generator.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZGFkMjVlYmQ0NmEzY2RhZGJlM2NjYjM2ODJlMzgyNWVfMDdjMjI2NDU1OWE0NDNkMDdmMjNkYTkyMmQ2MmVlODZfSUQ6NzY0ODEzMzI5Nzg2ODA4MjM2NF8xNzg2OTM2ODI4OjE3ODY5NDA0MjhfVjM" mime="application/zip" size="36668" token="XJ5ybWfEYoOoaZxDNYNcTbxDnrf"/></figure>

## 📌 技能简介

将 UK/EU/JP POP BD 团队的差旅审批邮件自动沉淀为结构化差旅资产：抓取近 3 个月邮件、按固定 9 人名单过滤、抽取 6 个核心字段、补齐经纬度，并输出暗色系差旅大屏 HTML。适用于团队差旅巡检、周会大屏、跨区域拜访排期复盘等场景。

## 🔑 触发词

- 核心关键词：

  - 差旅大屏
  - 差旅审批邮件
  - 团队全景差旅大屏
  - UK/EU/JP POP BD 差旅
  - travel dashboard
- 典型指令示例：

  > 抓近 3 个月差旅审批邮件，给 UK/EU/JP POP BD 团队做一个自动化差旅大屏。只看固定 9 个人，把审批邮件里的姓名、起终城市、时间、事由抽出来，再生成飞线地图和 Gantt 时间轴。

## ⚙️ 核心架构 / SOP / 约束条件

- **核心链路**：飞书邮箱检索 → 9 人准入名单过滤 → 6 字段抽取 → 经纬度解析与缓存 → JSON 结构化 → 静态暗色大屏 HTML → 动态展示入口文件。
- **邮件抓取**：通过 `lark-cli mail +triage` 搜近 3 个月审批邮件，再用 `lark-cli mail +messages` 拉取正文。
- **名单硬约束**：仅允许以下 9 人进入正式结果：于奇楠、李京达、江家徽、李泽、夏春雨、黄忆卓、赵月晨、叶佳智、宋欣蕖。
- **字段硬约束**：每条记录必须带齐 `姓名 / 出发城市 / 目的城市 / 出发时间 / 返程时间 / 事由` 六项；缺失即丢弃，不写空记录。
- **地理解析**：默认对出发城市与目的城市做经纬度解析，并写入缓存文件；解析失败允许留空，但不得伪造坐标。
- **模板约束**：大屏必须含 4 类模块：数据总览、飞线总览、榜单区、Gantt 时间轴；最终交付为静态 HTML。
- **动态展示衔接**：本技能负责生成最终 HTML 与动态展示入口文件；后续 build-check 与展示交付需由展示链路继续完成。

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：

  ```Plain Text
  给我做一个 UK/EU/JP POP BD 团队的差旅大屏。抓近 3 个月审批邮件，只看固定 9 人，抽姓名、出发城市、目的城市、出发时间、返程时间、事由，再输出暗色大屏和可继续展示的 HTML。
  
  ```
- 🤖 标准输出：

  ```Plain Text
  产物 1：output/travel_dashboard.json
  - 近 3 个月差旅结构化数据
  - trips 数组包含 6 个核心字段 + 经纬度 + 来源邮件信息
  
  产物 2：output/travel_dashboard.html
  - 暗色差旅大屏
  - 包含数据总览、飞线总览、目的地热度、事由分布、Gantt 时间轴、明细表
  
  产物 3：.aime/dynamic-ui/react-card/team_travel_dashboard_<timestamp>.html
  - 动态展示入口文件
  - 可继续接展示链路做 build-check 与交付
  
  ```

## 这次交付内容

- 新建技能目录：`user_skills/team-travel-dashboard-generator/`
- 主脚本：`scripts/build_travel_dashboard.py`
- 静态模板：`assets/travel_dashboard_template.html`
- 规则文档：`references/mail-extraction-rules.md`
- 输出契约：`references/dashboard-output-contract.md`

<figure view-type="Card"><source name="team-travel-dashboard-generator.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NjJlOGVhNjc5ODMyZTE3MWEzNzlhNWZmOGM5NzRkZmRfYTMxY2VkZTk3NGNhZWQ3ZjkyZmVjZWM3OTlhNzI2YjFfSUQ6NzY3MTA3NDQwMTQyODgwMjUyNF8xNzg2OTM2ODI4OjE3ODY5NDA0MjhfVjM" mime="application/zip" size="2146379" token="X4MfbzYjdohNjcx3LL1cplEZn6c"/></figure>

<figure view-type="Card"><source name="team-travel-dashboard-generator.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MWU3ZDI3MTdlMjJiMWZmNTJlNThkYTBjODgzZjUzMmZfMGJlOGQzNGI2YjUzNTkzZWQ2OGE5ZDczZWMxNDBjZDlfSUQ6NzY3MzAwNzk4MzI2MDk2MTk3MV8xNzg2OTM2ODI4OjE3ODY5NDA0MjhfVjM" mime="application/zip" size="2280460" token="Aad7boPZloe0SMx1REzcApNunYI"/></figure>

<figure view-type="Card"><source name="team-travel-dashboard-generator.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZGI3YmRiNTVjMmMyM2Y1MmJhMmE4ZDRhMmQ0MzIwYWNfNWYzZDdhNGFjNmUxMzZjYzQ1YmVmZGY2OGY2NmEwYmVfSUQ6NzY3MzAxNDk1MzI0NjkxOTg5MV8xNzg2OTM2ODI4OjE3ODY5NDA0MjhfVjM" mime="application/zip" size="2280460" token="ACK1bxWYto2NZvxPCoOcBY0CnBb"/></figure>

<figure view-type="Card"><source name="team-travel-dashboard-generator.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=Yzk1ZWI1MWZmN2YwNDA1YjM4NmEyNDNkNmY3NTRiODdfODYzM2ViMzI1ZGFjZjBkNjk0MjRkMDEyODkwYjc0YzhfSUQ6NzY3MzY4NTUwMTQxMjYwOTIzNF8xNzg2OTM2ODI4OjE3ODY5NDA0MjhfVjM" mime="application/zip" size="2339076" token="FUCZb9rM9omxGAxAxn2cOZQanQd"/></figure>

<figure view-type="Card"><source name="team-travel-dashboard-generator.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OTExOGYzNDBhMzRkZjM5ZTE1MjQwNzlhZmZiMGYzZmRfMDJmNzAzMGE4OGNjMjZlNTNmNGU4MjM0MmJiZTA3NjRfSUQ6NzY3NDgzNTIzODY5MDIxMzE0M18xNzg2OTM2ODMyOjE3ODY5NDA0MzJfVjM" mime="application/zip" size="2359349" token="BJ2gbcC1bomI1AxhFtRc9xC3nrb"/></figure>