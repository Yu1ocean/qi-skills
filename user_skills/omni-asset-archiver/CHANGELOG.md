# CHANGELOG

## v5.0 - 2026-05-20

### 1. 架构层
- 将 `omni-asset-archiver` 重构为**联邦制薄 I/O 驱动器**，剥离上层业务目录语义。
- 新增 `assets/federated_route_manifest.json`，将显式目标白名单、兼容预设与 DLQ 配置外置为单一事实源。
- 保留三条兼容预设：`aeolus_links` / `skill_inventory` / `library_registry`。
- 新增 `scripts/archiver_driver.py`，统一执行 Schema 校验、HYPERLINK 拼装、幂等 upsert、RAW 写后回读与 DLQ 兜底。

### 2. 可靠性层
- 新增 `⚠️[未分类_待分诊]` DLQ 标签体系。
- 新增本地 JSONL 死信队列：`assets/dlq/omni_asset_archiver_dlq.jsonl`。
- 发号器改造为真实飞书表格读写 + RAW 回读，不再依赖本地假 Excel。
- 风神链接 / 技能清单 / 图书馆写入增加幂等判重与精准 upsert 逻辑。

### 3. 兼容性层
- 保留 Aeolus 链接专项归档能力与严格行列约束。
- 保留复盘报告 / 架构演进报告写入图书馆的兼容入口。
- 保留专属技能清单的 Skill ID 精准更新能力。
