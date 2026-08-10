# Changelog

## 1.2 — 数据源热更新 + value_map 支持

- resources/example_weekly_friday.json: id 2503254957 → 2507297138
- 新增 value_map 字段（可选）：源级值映射，示例 shop_status: {"2":"active"}
- scripts/sync_main.py: 合并阶段应用 value_map
- scripts/sources/aeolus_source.py: download_full 返回缺字段或失败时自动回退 url_query
- CDA 自检重新通过

## 1.1（首发 2026-08-07）

- 首次锻造 `multi-source-sync` 技能。
- 支持配置驱动的多数据源（Aeolus dataQuery/dashboard/chart/history + Bitable）合并同步到飞书电子表格。
- 表头第一行只读锁死；`data_range` 幂等清空；`+csv-put` 平铺写入；更新日期锚点单元格；RAW 回捞校验。
- 内置轻量交叉质检（`records_vs_rows` / `field_map_zero_loss` / `updated_at_anchor`）+ 可选复用 `zero-trust-qa-checker`。
- 首个实例：每周五 VA dataQuery（rid=6081878, id=2503254957）→ my.larkoffice Sheet `KRIUslDgdh7WvYtXK8ZmhOCcyOb` (sheet=`d85fa5`)。
- 用户已手动验证：50 行数据写入成功，K2=2026-08-07。
