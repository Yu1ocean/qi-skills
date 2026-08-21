# Changelog — video-script

本文件记录 video-script 技能的版本变更。版本号 SSOT 为 `SKILL.md` frontmatter 的 `version:`。

## [待发布] 创建时间（created_at）字段固化

- **来源**：`ledger_year_audit_20260821 / DEC-20260821（热门剧本沉淀 P0 治理）`
- **背景**：P0 治理审计发现全链路零处 pub_date 时效过滤，入库样本中位年龄 436 天、
  74.4% 超 90 天。`hot-radar` v1.2 已把 `pub_date_guard` 守门员移植进技能本体，
  本次把同一套字段契约下沉到下游技能本体，避免技能被单独调用时又漏掉时效元数据。
- **变更**：见 `SKILL.md` 的 Changelog 小节（含 created_at 解析优先级、NULL 契约与
  时效三态标签定义）。
