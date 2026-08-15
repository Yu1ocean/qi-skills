# US AM Stats Sync

## 📌 技能简介

将「美区AM招商统计」飞书多维表格每日同步到统计电子表格，并在 VM2reD 明细页维护按同步日期横向追加的辅助区；汇总页仅维护 N2 更新日期公式。

- 目标 Sheet：https://bytedance.larkoffice.com/sheets/XZoSsAwObh72kPtn3DLmWJ4AyWc
- 明细 Tab：VM2reD
- US行业统计 Tab：2unp6l

## 🔑 触发词

- US AM 招商统计同步
- 刷新 VM2reD 明细

## ⚙️ 核心架构 / SOP / 约束条件

运行：`python3 scripts/daily_sync.py`（需 include_secrets=true）

## 📖 案例实录 (Best Practice)

- 用户输入：同步 US AM 招商统计到 Sheet
- 标准输出：JSON 审计日志 + RAW 回捞结果

<figure view-type="Card"><source name="us-am-stats-sync.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OGYxMjlkYmM0OWQxNGJhOWQxYTcwOTJiYzEwYjdlYmNfYTFkZDA5OGIwMTEzYzlhNjEwYWI3ZWRkODBlY2NjNjVfSUQ6NzY3MzcxOTI0MjcxOTg5MDQwMF8xNzg2Njc2OTk0OjE3ODY2ODA1OTRfVjM" mime="application/zip" size="36078" token="RtKrbTB5IoNeYBxLoLRcbzHtn9d"/></figure>