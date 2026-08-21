<title>【技能说明】skill-forge-pipeline · 技能锻造流水线 (Forge Pipeline V5.23)</title>

<figure view-type="Card"><source name="skill-forge-pipeline.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YTU4MWQ2NDczMGZhMGI1MThlYWZhMDhlYWFiNjAxMWRfN2JjNjQxMjY1OTYzMWU0Njc0NzM3MWY1ZmFhMGU4OTdfSUQ6NzY3NjQ5MTY1MTczNjUzODMxMl8xNzg3MzIyNDk2OjE3ODczMjYwOTZfVjM" mime="application/zip" size="2968212" token="Dtszb3jPmohAr8xV8M9cOTKLnoh"/></figure>

> 🤖 **本区块由 forge 流水线自动生成（Overwrite Zone），请勿手工编辑**  
> **技能名称**：`skill-forge-pipeline`  
> **版本号**：5.23  
> **描述**：创建、升级、打包、发布、归档并上传到 Aime 云端的自制技能锻造流水线。适用于新技能锻造、既有技能迭代、技能上线发布、云端发布与台账归档场景。  
> **更新时间**：2026-08-21 22:28

# 【技能说明】skill-forge-pipeline · 技能锻造流水线 (Forge Pipeline V5.23)

> 📄 **文档编号**：SYS-2604-012 📅 **归档日期**：2026-04-13

---

<callout emoji="💡">
**技能定位**：自动化技能创建与归档流水线，确保 Forge、Celebrate 和 Archive 步骤的原子性执行。
</callout>

## 📌 技能简介

自动化技能创建、升级、打包发布与归档流水线；并在 Forge 阶段强制触发 CDA 三层护栏自检，失败即熔断。

## 🔑 触发词

- 核心关键词：

  - skill-forge-pipeline
  - CDA Guardrails
  - Forge / Celebrate / Archive
- 典型指令示例：

> 【CDA Guardrails 固化到 skill-forge-pipeline】创建/升级一个技能并完成打包发布与归档

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
  【CDA Guardrails 固化到 skill-forge-pipeline】
  
  ```
- 🤖 标准输出：

  ```Plain Text
  1) Forge：CDA-Guardrails-Selfcheck PASSED（风险分级 + L1/L2/L3 覆盖）
  2) Celebrate：生成 EP 卡片并部署（返回 URL）
  3) Archive：register_skill 产出 metadata.json（含 zip_path/drive_file_url/doc_link），并完成台账 RAW 写后即读
  
  ```

## 🔒 双轨原子写入约束 (Dual-Track Atomic Write) — V5.23 新增

关联决策：DEC-20260821-001「决策录入必须双轨原子写入，单轨成功即判失败」。事故起因：forge 子特工只写飞书镜像台账、从未 append 本地 SSOT `memory/topics/decision-registry.md`，形成孤儿行，漂移数天不可见。

**适用范围**：凡 forge 流程中涉及「决策台账写入飞书镜像」的节点（决策录入、护栏升格、复盘沉淀带出的新决策），一律适用。

**事务块绑定顺序**：① 飞书镜像写入成功 → ② 立刻执行本地 SSOT append → ③ 双轨断言。两步绑定为一个事务，中间不允许插入任何其他动作，不允许等待用户确认。

**双轨断言规则**：写后等待 2 秒执行 RAW read-after-write —— 轨道 A 回读本地末条 `- id: DEC-...`、轨道 B 回读飞书镜像末行 ID，两者都必须等于目标 ID；任一轨失败或不一致立刻 raise 熔断，严禁静默成功。

**失败即孤儿标记**：断言或写入失败时，条目写入死信队列 `.ephemeral_pool/orphan_decisions.jsonl`（含 decision_id / failed_track(local|mirror) / error / timestamp / suggested_fix），标记 ⚠️[孤儿待修复]，随后由 `tools/sync_decision_registry.py` 以本地为准修复镜像，或补 append 本地后重跑断言收敛。

**调用示例**（均需 include_secrets=true）：

```
# 零副作用前置校验
python3 user_skills/skill-forge-pipeline/scripts/dual_track_atomic_write.py --dry-run --decision-id DEC-20260821-001 --entry-file /tmp/dec_entry.yaml

# 双轨原子写入
python3 user_skills/skill-forge-pipeline/scripts/dual_track_atomic_write.py --decision-id DEC-20260821-001 --entry-file /tmp/dec_entry.yaml

# 事后巡检（只做双轨回读断言）
python3 user_skills/skill-forge-pipeline/scripts/dual_track_atomic_write.py --verify-only DEC-20260821-001

# 故障注入自测（验证 raise + 死信队列链路）
python3 user_skills/skill-forge-pipeline/scripts/dual_track_atomic_write.py --verify-only DEC-20260821-001 --inject-failure mirror
```

## 📝 使用案例 & 踩坑记录

> 本章节属于 Preserve Zone：forge 流水线永不覆盖，请在此自由记录使用案例、踩坑与注意事项。

[待补充使用案例]

## 📋 更新日志

> 本章节只追加、不覆盖历史条目。

- **V5.23**: 新增「飞书说明文档三分区（Zone）策略」，终结 forge 覆盖人工沉淀的风险。
- **V5.23**: 新增「飞书说明文档三分区（Zone）策略」，终结 forge 覆盖人工沉淀的风险。