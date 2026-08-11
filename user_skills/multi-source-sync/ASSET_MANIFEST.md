# Multi Source Sync - Asset Manifest

## 数据源清单

### 首个实例：每周五数据更新
- **Schedule**: 每周五定时任务（schedule_id: `fe4fad54-3d0d-44c5-bb31-910ba2f33362`）
- **数据源 1（Aeolus）**：
  - 类型：`aeolus` dataQuery
  - Region: `VA`（自动从域名 `aeolus-va.tiktok-row.net` 推断）
  - URL: `https://aeolus-va.tiktok-row.net/pages/dataQuery?appId=555771&dashboardId=727928&id=2507297138&isDefault=1&reportQuerySchemaKey=58976a47-26c9-444e-bff9-ab7d213b0ee6&rid=6081878&sid=3377819&waitForDataReady=0`
  - `download_full=true`（优先走 `download_dashboard_data` 单图表 xlsx 直出，缺字段或失败时自动回退 `url_query`）
  - `field_map`：映射到目标表头 `shop_id/shop_name/US行业/US AM/US Live AM/直播日均GMV/竞拍日均GMV/竞拍渗透/竞拍日均UV/shop_status`
  - `value_map`：`shop_status` 的值 `2 → active`

## 产出物

- **目标电子表格（主库）**: `https://bytedance.my.larkoffice.com/sheets/KRIUslDgdh7WvYtXK8ZmhOCcyOb?sheet=d85fa5`
- **目标电子表格（快照）**: `https://bytedance.my.larkoffice.com/sheets/KRIUslDgdh7WvYtXK8ZmhOCcyOb?sheet=05FUQ4`
- **目标 Sheet ID**: `d85fa5`（主库）, `05FUQ4`（快照）
- **Sheet1 列结构**: `A:K` 业务列 + `L=is_new` + `M=入库时间`
- **更新日期锚点**: `Sheet1!K2`，格式 `YYYY-MM-DD`
- **v2.0 首跑验收（2026-08-11）**：主库 existing=542 / new=0 / removed=0 / status_changes=0；`Sheet1 rows=542`；`Sheet2 rows=542`；`K2=2026-08-11`
- **QA 报告目录**: `output/qa_report_YYYYMMDD_HHMMSS.json`（每次同步落盘一份）

## 质检方案结论

**双引擎并存**：
- **复用 `user_skills/zero-trust-qa-checker`**：目标 Sheet 的物理契约断言（`non_null` / `unique` / `id_format` / `link_present`）；当配置 `qa.engine=zero_trust` 时自动调用其 `v3_engine.py`。
- **自建 `scripts/qa_check.py`**：覆盖多源合并交叉校验：
  - `records_vs_rows`
  - `field_map_zero_loss`
  - `updated_at_anchor`
  - `diff_summary`（`new / removed / status_changes / non_active`）

## 每次同步的 QA 报告结构

```json
{
  "run_id": "20260811_150722",
  "status": "PASS | WARN | FAIL",
  "sources": [
    {"id": "va_dq_2507297138", "type": "aeolus", "records_fetched": 543}
  ],
  "target": {
    "sheet_url": "...",
    "sheet1_id": "d85fa5",
    "sheet2_id": "05FUQ4",
    "sheet1": {"existing_patched": 542, "new_appended": 0},
    "sheet2": {"rows_written": 542}
  },
  "diff_summary": {
    "existing": 542,
    "new": 0,
    "removed": 0,
    "status_changes": 0
  },
  "raw_readback": {
    "sheet1_top": {"actual_range": "A1:M3"},
    "sheet2_top": {"actual_range": "A1:K3"}
  }
}
```
