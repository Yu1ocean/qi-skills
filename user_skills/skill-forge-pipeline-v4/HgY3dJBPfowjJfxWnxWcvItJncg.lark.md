# 【技能说明】自动化技能创建与归档流水线 (Forge Pipeline V4)

<figure view-type="Card"><source name="team-travel-dashboard-generator.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ODZiZGE4MTVkOWQ0ODA5MjkzZmRhMDc3Nzk5YzNjNjdfODRhNzg3NThjMWM0OGIyZTgxMDQzNGY2YmUyNTc5ZWJfSUQ6NzY1MDM3NjQxMDAwNzYyMDg1MV8xNzg2OTQ1NDY0OjE3ODY5NDkwNjRfVjM" mime="application/zip" size="1191362" token="I2E1bAxLbo8CaZxsvLAc0UgvnTc"/></figure>

<figure view-type="Card"><source name="skill-forge-pipeline-v4.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MDBmYjRlZmE0MzZiZWNhZGUwZmU2NTkyMWM2MzNhMjBfMDQzOGIzNTZhYmFhZGJiMGIzMGI1MGQzMTU3ZDczODhfSUQ6NzY0MTY2ODk5MjUxNzI2MjI2Nl8xNzg2OTQ1NDY0OjE3ODY5NDkwNjRfVjM" mime="application/zip" size="2894261" token="Y5G2bPYojolKSXxeWo4cIOchnP4"/></figure>

<figure view-type="Card"><source name="skill-forge-pipeline-v4.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZjJmZThjYzExY2NkMTUyODgyYzgzZThkN2FmMWVmZTBfOTFlYjNhNzRkOTExYjM0OTZhZTExNTdiYWQyYWViZmJfSUQ6NzYzMzM4NTg3NDA3MzYxOTQwNF8xNzg2OTQ1NDY0OjE3ODY5NDkwNjRfVjM" mime="application/zip" size="2884412" token="PR9wbJKIsoD82UxOvMPcveyQnNb"/></figure>

<figure view-type="Card"><source name="skill-forge-pipeline-v4.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=Njc0MGYzNzQ3MjFiNGMzNmY1OTllYjE0NzAzZmY3ODdfNzkxYjM0N2RkYWE5Y2RiMDFiNjI0MjAyMjg5MjY2OGZfSUQ6NzYzMjY0MDY4NTIxMjAyNzgzNV8xNzg2OTQ1NDY0OjE3ODY5NDkwNjRfVjM" mime="application/zip" size="10765" token="LIaXbTYCaoiF8lxjkRFcUF1rn6v"/></figure>

<figure view-type="Card"><source name="skill-forge-pipeline-v4.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OTA0MzU4ZmI1MmZmNDRhMzQxMTA1ZWQ3YTY0Mzk4NWVfMzFkZTc0ZmI0MjdmNTBmNGMwYzcyYTJiYjVhMjVlYTBfSUQ6NzYzMjYzOTgyODQ4NzkxNjQ4Ml8xNzg2OTQ1NDY0OjE3ODY5NDkwNjRfVjM" mime="application/zip" size="10453" token="UHDrbkr2rov5U1xt6d6caKi3n3c"/></figure>

> 📄 **文档编号**：SYS-2604-012 📅 **归档日期**：2026-04-13

---

<callout emoji="💡">
**技能定位**：自动化技能创建与归档流水线，确保 Forge、Celebrate 和 Archive 步骤的原子性执行。
</callout>

## 📌 技能简介

自动化技能创建、升级、打包发布与归档流水线；并在 Forge 阶段强制触发 CDA 三层护栏自检，失败即熔断。

## 🔑 触发词

- 核心关键词：

  - skill-forge-pipeline-v4
  - CDA Guardrails
  - Forge / Celebrate / Archive
- 典型指令示例：

> 【CDA Guardrails 固化到 skill-forge-pipeline-v4】创建/升级一个技能并完成打包发布与归档

## 一、 强制原子工作流 (Atomic Transaction)

本技能是 Aime 专属技能的“造物主”，严禁在流程中途退出，必须一次性完成以下闭环：

### 1. Forge 锻造 (核心编写)

- 调用 `inner_skills/aime-skill-creator`。
- 完成 `SKILL.md` 编写、目录初始化、验证及 Pack 打包。

### 2. Celebrate 庆祝 (赛博灵感)

- 只要打包成功，**强制**调起 `cyber-inspiration-generator`。
- 生成赛博朋克风 AI 视觉图 (16:9)。
- 同步至【灵感画廊】多维表格，保留视觉资产。

### 3. Archive 入库 (图书馆归档)

- **物理写入网关**：流水线严禁直接操作表格，必须通过 `omni-asset-archiver` 执行。
- **资产闭环**：将技能编号、名称链接、功能描述写入【专属技能清单】。

## 二、 核心护栏 (Guardrails)

<grid>
<column width-ratio="0.500000">
**防脱节修改铁律**  
严禁使用编辑器直接篡改代码。所有修改必须通过流水线触发，并同步更新 `SKILL.md` 说明书。
</column>
<column width-ratio="0.500000">
**双轨校验熔断**  
若只改代码未改说明书（或版本号未升迁），系统将强制熔断，拒绝保存更改。
</column>
</grid>

- **唯一入口制**：造/改技能必须从此入口进入。
- **强制版本升迁**：每次迭代必须在 `SKILL.md` 顶部 Bump Version。

<callout emoji="⭐">
**Changelog V4**: 架构解耦，正式确立 `omni-asset-archiver` 为唯一的物理写入网关，引入 RAW 原子锁规范。
</callout>

- 2026-04-27：v5.2.0 - 新增 CDA-Guardrails-Selfcheck Checkpoint（风险分级 + 三层自检 + 失败熔断）。

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：

  ```Plain Text
  【CDA Guardrails 固化到 skill-forge-pipeline-v4】
  
  ```
- 🤖 标准输出：

  ```Plain Text
  1) Forge：CDA-Guardrails-Selfcheck PASSED（风险分级 + L1/L2/L3 覆盖）
  2) Celebrate：生成 EP 卡片并部署（返回 URL）
  3) Archive：register_skill 产出 metadata.json（含 zip_path/drive_file_url/doc_link），并完成台账 RAW 写后即读
  
  ```

<figure view-type="Card"><source name="weekly-top3-patrol.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NTgyZGNjZWU5NTU1MWQ1YzY3YmJlYzA0YTNjNjc2Y2ZfYzkzNDFiOTg5NGQyZjc4NmE3ODRjOWY0MzMyNjRhODZfSUQ6NzY2OTYwNDI5Mzg2Njk2NTk5NF8xNzg2OTQ1NDY0OjE3ODY5NDkwNjRfVjM" mime="application/zip" size="11833238" token="Bi5XbVhjro9GR1xh7txcy1VNn9f"/></figure>

<figure view-type="Card"><source name="weekly-top3-patrol.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NGMzZTg2MmJmZTA5NjczNDMxZjlkMzViNWIwNjVlOWVfY2NiM2MyYTdiNjM0OWRkMjE3NzIxNzIwYzcwODBkZTBfSUQ6NzY2OTYwNDM4NTQ5MjEyNjk0Ml8xNzg2OTQ1NDY0OjE3ODY5NDkwNjRfVjM" mime="application/zip" size="11833238" token="B4gCbJ8L1oHom6xxfKVcaj50nqf"/></figure>

<figure view-type="Card"><source name="skill-forge-pipeline-v4.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZWY4YzZjNzY0MTkwZWY5NGI2ZmFhNzBmMzgzN2MyZmVfMDZhMDI4M2EzY2MyZDRiYTQ0ODk0ODRmYzk2ZWNjMmVfSUQ6NzY3NDg3MjMzMjYzMjE4MTcyMF8xNzg2OTQ1NDY5OjE3ODY5NDkwNjlfVjM" mime="application/zip" size="2951668" token="PCyabnm5qoL7inxuCtIceK6Xnmc"/></figure>