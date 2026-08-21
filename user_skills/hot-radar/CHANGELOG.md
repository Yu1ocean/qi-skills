# hot-radar Changelog

本文件记录 hot-radar 技能本体的版本变更。版本号真相源为 `SKILL.md` frontmatter 的 `version:`。

## v1.2 — 2026-08-21

**治理来源**：`ledger_year_audit_20260821` / `DEC-20260821`（热门剧本沉淀 P0 治理）

**背景**：审计发现全链路 67 个脚本零处 `pub_date` 过滤，`--time-window` 只写进
manifest 的 query 元数据、完全不参与过滤，导致入库样本中位年龄 436 天、74.4%
超 90 天。项目层 `pub_date_guard.py` 已加固，但技能本体被单独调用时仍无任何
时效保护 —— 本次补上这个洞。

**变更点**

- 新增 `scripts/pub_date_guard.py`：技能自包含的发布时间硬过滤守门员
  （锚点 `GUARD-PUB_DATE-v1`），移植自项目层实现，配置路径默认解析到
  `references/hot_radar_config.yaml`，配置缺失时回退内置默认值且只严不宽。
  保留 NULL 契约：解析不到发布时间返回 `(None, "NULL")`，绝不估算。
- 新增 `references/hot_radar_config.yaml`：`hard_cutoff_days: 90`、
  `soft_prefer_days: 30`、`null_action: reject`。
- `scripts/build_candidate_manifest.py`：
  - `--time-window` 真实参与过滤，支持『近7天』/『近30天』/『last 7 days』/『7d』/『30』；
  - 在 dedupe / top-n 截断**之前**调用 `gate_candidates()` 做硬过滤；
  - 有效 cutoff = `min(--time-window 解析天数, --pub-date-cutoff-days)`；
  - 新增 `--pub-date-cutoff-days`（默认 90）、`--null-action`（默认 reject）；
  - 拦截候选落 DLQ 并写明 `pub_date_gate:<reason>`；
  - `summary` 新增 `stale_rejected_count` / `null_pub_date_count` /
    `synthetic_id_rejected_count` / `fresh_within_30d_count`；
  - 写盘前执行出口断言 `assert_no_stale_in_output()`；
  - `--time-window` 无法解析时抛错熔断（fail-closed）。
- `SKILL.md`：Common Rationalizations 新增时效借口；Red Flags 新增
  「`--time-window` 只写元数据」「NULL 放行」；Verification 新增时效硬过滤验收；
  新增 Step 5 时效硬过滤章节与新命令示例；Defaults 补齐时效默认值。

## v1.1 — 2026-06-14

首版正式发布，固化「查询合同 → 多源发现 → 字段归一化 → 标签归一化 → JSON manifest 输出」流程。
