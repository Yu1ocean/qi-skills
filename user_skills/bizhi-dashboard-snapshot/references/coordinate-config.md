# 必招看板周趋势快照执行器配置 v2.0

> 坐标于 2026-07-09 通过 V2 API 实测确认。AI数据 section 位于 rows 14-22。

## 快照坐标表

| 分组 | 标签列 | 读取范围 (W5-W0) | 左移写入 (W5-W1) | W0写入 | 日期单元格 | 数据行数 |
|------|--------|------------------|------------------|--------|-----------|---------|
| US行业 | G16:G22 | H16:M22 | H16:L22 | M16:M22 | M1 | 7 |
| 按BD | Y16:Y22 | Z16:AE22 | Z16:AD22 | AE16:AE22 | AE1 | 7 |
| EU行业 | AL16:AL19 | AM16:AR19 | AM16:AQ19 | AR16:AR19 | AR1 | 4 |

## 日期行位置

日期写入 Row 1（主看板区域），格式为 `M/D`（如 `7/9`）。

Row 15 为 W5-W0 列头标识行（纯文本 "W5"..."W0"），不作为日期存储位置。

## 底表口径

- 工作簿：`M7x6sla1yh5I2itqefcl7HpqgSe`
- 看板 Sheet：`7JpNIf`（"C.7月必招"）
- 底表 Sheet：`jlfbt6`（"A. 全量底表"，8603 行，88 列）
- 底表数据行：5:8603（CSV 索引 4:）
- 固定过滤：B列(idx 1) = `必招 6 月`，V列(idx 21) = `已入驻`
- US行业：L列(idx 11) 匹配 G16:G22 标签
- 按BD：N列(idx 13) 匹配 Y16:Y22 标签
- EU行业：E列(idx 4) 匹配 AL16:AL19 标签

## 写入路径（v2.0 核心变更）

| 阶段 | 方法 | 说明 |
|------|------|------|
| 底表导出 | `lark-cli drive +export --sub-id jlfbt6 --file-extension csv` | Drive API，无超时问题 |
| 看板读写 | Python `requests` → 标准 Lark Sheets V2 REST API | 绕开 Sheet AI tool 5s RPC 超时 |
| 鉴权 | MITM 代理从 lark-cli 提取 user_access_token | 每次执行自动获取 |

## 防坑设计

1. **绕开 Sheet AI API**：lark-cli sheets（+csv-put/+cells-set 等）对此工作簿因 5s RPC 超时全部失败。改用标准 V2 API `PUT /open-apis/sheets/v2/spreadsheets/{token}/values`，timeout 60s。
2. 不使用跨 Sheet `COUNTIFS + "<>"`，所有统计在 Python 本地完成。
3. 底表通过 Drive export 获取 CSV，避免大表读取超时。
4. 同一 ISO 周重复执行默认不再左移，只刷新 W0 和日期。
5. Token 提取使用临时 MITM 代理，证书有效期 1 小时，执行结束即清理。
