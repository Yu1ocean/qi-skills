# Changelog

## v2.0 (2026-08-11)
- feat: 双 Sheet 架构（Sheet1 主库只增不减 / Sheet2 快照全量覆盖）
- feat: L 列 `is_new` 增量标记，M 列 `入库时间` 永久保留
- feat: 增量 diff 计算 + 状态变化追踪（`new_shops` / `removed_shops` / `status_changes`）
- feat: `removed_shops` 不删行，仅 patch `shop_status=removed`
- feat: QA 报告新增 diff 摘要（new / removed / status_changes / non_active）
- safe: Sheet1 严格 patch / append，禁止全表覆盖；已有 M 列值绝不覆盖

## v1.4 (2026-08-11)
- fix: aeolus_source._fetch_via_download 改走单图表 xlsx 直出（`--chart-id <rid>`），绕开 dashboard 路由 403 与 url_query pivot cells 误展开 bug
- fix: 修复 pivot_table 数据抽取错误，行数从 49 → 542
- feat: xlsx 异步下载增加 3 次幂等重试（5s 间隔），应对 aeolus/unknown 偶发
- safe: 保留 `server_total > fetched_rows` 熔断

## v1.3 (2026-08-10)
- scripts/sync_main.py: 新增 dedup（按 shop_id 去重 + 剔 Sum 行）与 apply_field_format()（int_round / percent_no_decimal）
- scripts/qa_check.py: records_vs_rows 支持以转换后目标行数作为 expected_after_transform，避免 dedup 后误报
- resources/example_weekly_friday.json: 新增 dedup、field_format、target.columns 中 J 列 = shop_status
- QA 报告扩展：dedup_applied / field_format_applied
- 真跑结果：records_fetched=350 → rows_written=49，J1=shop_status，K2=2026-08-10，QA status=PASS

## v1.2 (2026-08-10)
- resources/example_weekly_friday.json: id 2503254957 → 2507297138
- 新增 value_map 字段（可选）：源级值映射，示例 shop_status: {"2":"active"}
- scripts/sync_main.py: 合并阶段应用 value_map
- scripts/sources/aeolus_source.py: download_full 返回缺字段或失败时自动回退 url_query
- CDA 自检重新通过

## v1.1（首发 2026-08-07）
- 首次锻造 `multi-source-sync` 技能。
- 支持配置驱动的多数据源（Aeolus dataQuery/dashboard/chart/history + Bitable）合并同步到飞书电子表格。
- 表头第一行只读锁死；`data_range` 幂等清空；`+csv-put` 平铺写入；更新日期锚点单元格；RAW 回捞校验。
- 内置轻量交叉质检（`records_vs_rows` / `field_map_zero_loss` / `updated_at_anchor`）+ 可选复用 zero-trust-qa-checker。
- 首个实例：每周五 VA dataQuery（rid=6081878, id=2503254957）→ my.larkoffice Sheet `KRIUslDgdh7WvYtXK8ZmhOCcyOb` (sheet=`d85fa5`)。
- 用户已手动验证：50 行数据写入成功，K2=2026-08-07。
