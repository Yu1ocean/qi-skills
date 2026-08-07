# Multi Source Sync - Asset Manifest

## 数据源清单

### 首个实例：每周五数据更新
- **Schedule**: 每周五定时任务（schedule_id: `fe4fad54-3d0d-44c5-bb31-910ba2f33362`）
- **数据源 1（Aeolus）**：
  - 类型：`aeolus` dataQuery
  - Region: `VA`（自动从域名 `aeolus-va.tiktok-row.net` 推断）
  - URL: `https://aeolus-va.tiktok-row.net/pages/dataQuery?appId=555771&dashboardId=727928&id=2503254957&isDefault=1&reportQuerySchemaKey=58976a47-26c9-444e-bff9-ab7d213b0ee6&rid=6081878&sid=3377819&waitForDataReady=0`
  - `download_full=true`（走 `download_dashboard_data`，规避 1000 行 hard limit）
  - `field_map`：按 `target.columns` 顺序直接映射（用户已验证 50 行结构）

## 产出物

- **目标电子表格**: `https://bytedance.my.larkoffice.com/sheets/KRIUslDgdh7WvYtXK8ZmhOCcyOb?sheet=d85fa5`
- **目标 Sheet ID**: `d85fa5`
- **写入范围**: `A2:J10000`（表头第一行 `A1:J1` 只读锁死）
- **更新日期锚点**: `K2`，格式 `YYYY-MM-DD`
- **验收锚点（用户已验证）**：`K2 = 2026-08-07`，rows_written = 50（可用作首次 dry-run 回读校验）
- **QA 报告目录**: `output/qa_report_YYYYMMDD_HHMMSS.json`（每次同步落盘一份）

## 质检方案结论

**双引擎并存**：
- **复用 `user_skills/zero-trust-qa-checker`**：目标 Sheet 的物理契约断言（`non_null` / `unique` / `id_format` / `link_present`）；配套 `resources/qa_manifest.example.json` 最小可运行示例，当配置 `qa.engine=zero_trust` 时自动调用其 `v3_engine.py`。
- **自建 `scripts/qa_check.py`**：覆盖 zero-trust 未覆盖的多源合并交叉校验：
  - `records_vs_rows`：Σ(records_fetched) 与 rows_written 一致性核对（union_append 语义）。
  - `field_map_zero_loss`：字段映射零丢失核查（记录源字段 → 目标列的命中率）。
  - `updated_at_anchor`：`updated_at_cell` 存在性与格式校验。

## 每次同步的 QA 报告结构

```json
{
  "run_id": "20260807_144500",
  "config": "resources/example_weekly_friday.json",
  "status": "PASS | WARN | FAIL",
  "sources": [
    { "id": "va_dq_2503254957", "type": "aeolus", "records_fetched": 50 }
  ],
  "target": {
    "sheet_url": "...",
    "sheet_id": "d85fa5",
    "rows_written": 50,
    "updated_at": "2026-08-07"
  },
  "cross_checks": {
    "records_vs_rows": { "expected": 50, "actual": 50, "ok": true },
    "field_map_zero_loss": { "mapped_fields": 10, "unmapped_fields": [], "ok": true },
    "updated_at_anchor": { "cell": "K2", "value": "2026-08-07", "ok": true }
  },
  "raw_readback": {
    "range": "A1:J3",
    "match": true,
    "diff": []
  },
  "errors": []
}
```
