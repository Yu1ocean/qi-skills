# 物理摄入 media-fetcher

<figure view-type="Card"><source name="media-fetcher.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OWMxMmRkYTA3YTFmMmI4OTU4NDk3Mjg4NWExNTY3YTdfOThjNjkzYzQ4ZDM2NzBjZjQ3YzI3MTMxNmM0MmVkODJfSUQ6NzY3NjM2NDc4ODY3NTMxNzAzMl8xNzg3MjkyOTU5OjE3ODcyOTY1NTlfVjM" mime="application/zip" size="16171" token="EezEbvU5eoYcN1xlqRvceiMjn1e"/></figure>

<figure view-type="Card"><source name="media-fetcher.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NjVkNmRiODQxZGUxNjRiYmRkNmExZTQ5YTQ1MmQ0MjhfMGNlNzQ0YWM1MTdjMTNhNWI2YjQ1ZjdjZTIyMTJmYWRfSUQ6NzY1MTEwNTYzODk3Nzk5ODAzNV8xNzg3MjkyOTU1OjE3ODcyOTY1NTVfVjM" mime="application/zip" size="6413" token="VyWibWkTxo5oHHx3AC3cwCV3nTg"/></figure>

## 📌 技能简介

`media-fetcher` 是热门剧本沉淀链路里的“物理摄入 orchestrator”。

它不重复发明下载器，而是把 `yt-dlp-media-downloader` 统一包装成批处理入口：先 probe，再按 `video` / `audio` 模式拉取主产物，并沉淀批次 manifest 与 DLQ，方便后续 `video-script` 与 `script-archive` 继续消费。

## 🔑 触发词

- 核心关键词：

  - 批量下载视频
  - 媒体物理摄入
  - 批量 yt-dlp
  - 媒体落地
  - 下载 manifest
- 典型指令示例：

  > 把这批热门视频 URL 全部落地到本地，先探测再下载。我给你一个候选池 JSON，帮我批量拉视频并生成失败清单。

## ⚙️ 核心架构 / SOP / 约束条件

### 1. 输入必须是批次，不是零散 URL

支持两种输入：

- 纯列表 JSON：`[{"url": "...", "tags": {...}}]`
- `hot-radar` 输出的候选 manifest（读取其中 `candidates` 字段）

### 2. 强制 probe

每条 URL 必须先调用底层 fetcher 做 `probe`：

- probe 成功：才能进入 `video` / `audio`
- probe 失败：直接进入 DLQ，并保留 stderr 摘要

<callout emoji="💡">
`media-fetcher` 的底线不是“尽量多下几条”，而是 **先判活、再拉流、留痕失败项**。不允许跳过 probe，也不允许把失败静默吞掉。
</callout>

### 3. 输出必须成包

批次级输出最少包括：

- `batch_id`
- `mode`
- `summary`
- `items`
- `dlq_path`

逐条记录中应尽量包含：

- `primary_asset_path`
- `info_json_path`
- `metadata`
- `stderr_summary`

### 4. 运行脚本

```Bash
python3 scripts/batch_media_fetch.py \
  --input-json output/hot_radar_candidates.json \
  --mode video \
  --output-root downloads/media_fetcher \
  --fetch-script /abs/path/to/yt_dlp_fetch.py \
  --result-json output/media_fetch_manifest.json \
  --dlq-jsonl output/media_fetch_dlq.jsonl

```

### 5. 结果解释

- `probe` 模式：只做连通性与元信息探测，不下载主产物
- `video` 模式：下载视频主产物
- `audio` 模式：下载或抽取音频，适合 ASR

### 6. 验收标准

判定“批次摄入完成”前，至少满足：

- 每条 URL 都执行过 probe
- 成功项带有路径或 metadata
- 失败项进入 DLQ
- 输出存在批次 manifest JSON
- 下游可直接消费这份结果结构

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：

  ```Plain Text
  这里有一批热门视频 URL，帮我先全部 probe，再把有效的下载成视频，失败项留档。
  
  ```
- 🤖 标准输出：

  ```Plain Text
  已按批次执行：每条链接先走 yt-dlp probe，再进入 video 下载。
  成功项保留视频路径和 info.json，失败项写入 DLQ 并附 stderr 摘要，最终统一输出 manifest JSON。
  
  ```

## 附：本次首发范围

- 当前版本：`0.1`（发布链路会升迁到正式首发版本）
- 技能目录：`media-fetcher/`
- 主要脚本：`scripts/batch_media_fetch.py`