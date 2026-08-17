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

<figure view-type="Card"><source name="us-am-stats-sync.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NWFhYTgxZWE4YjBhMzAxZGFkZDBmYWIyMGFkYTllYmRfZmZjYjI5ZjAxNDMzYjI1YTk4MTc0OGI1MmJiMmNlNDRfSUQ6NzY3MzcxOTI0MjcxOTg5MDQwMF8xNzg2OTM4ODgxOjE3ODY5NDI0ODFfVjM" mime="application/zip" size="36078" token="RtKrbTB5IoNeYBxLoLRcbzHtn9d"/></figure>

<figure view-type="Card"><source name="us-am-stats-sync.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OTA0Y2M0YWEyNTA1OGJlNDM5ZTlmYzZjNWUwNTQ3YTVfMjZjODVhZGViNTY0MGZmOTkyOGUyNjQ0NDIyMjM5YjBfSUQ6NzY3NDgwODg0NDk3OTYwNDQyOF8xNzg2OTM4ODgxOjE3ODY5NDI0ODFfVjM" mime="application/zip" size="44197" token="P1dcbvwwLokDa8xNW47cl4YFnKI"/></figure>

<figure view-type="Card"><source name="us-am-stats-sync.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NzkyODQ0ZTk5ZjI1OWRlMjA5MzUzZmQ4ZGRlMWY0Y2NfNmY5OGZmZTNlNDUzZTdhOGZkNzVlNDBlZmQyZWYzZjlfSUQ6NzY3NDgwODk5NjQ0MTc4NzM1OF8xNzg2OTM4ODgxOjE3ODY5NDI0ODFfVjM" mime="application/zip" size="44197" token="O5vUbpEQ5oZrv9x5aJIcUpG8nng"/></figure>

<figure view-type="Card"><source name="us-am-stats-sync.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OWQwZjU5ODM4OWRkMWY5MmEzNTA4N2FjZTA1OTk5ODJfOWFjMGZmZTI3MDcxNmZmYmUyZTkyZDNmZWI5ZTAxM2ZfSUQ6NzY3NDg0NDA1MjIxMDc5Nzc3M18xNzg2OTM4ODg0OjE3ODY5NDI0ODRfVjM" mime="application/zip" size="46103" token="EgBabTG4OofAnqxIO4OcsZLfnkg"/></figure>

<figure view-type="Card"><source name="us-am-stats-sync.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZTJiNDc3ZGQ4Zjg3Njk5ZmUyZjVjNWI4MTIxZjVmZmZfZjhkOTI0Yzk1NmJiMzdkY2Y5ZjFkNWI1OGQwYjZjYWNfSUQ6NzY3NDg1NDY5MTE4ODI4MDI1Nl8xNzg2OTQxMzYxOjE3ODY5NDQ5NjFfVjM" mime="application/zip" size="55003" token="Hz3dbyb5Hos3kExWLGQcn8mBnwe"/></figure>