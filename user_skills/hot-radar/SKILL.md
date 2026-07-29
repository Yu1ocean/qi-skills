---
name: hot-radar
description: 热门视频候选集构建器，负责按平台、市场、类目、时间窗口和 Top N 约束发现并整理 TikTok Shop / 抖音跨境服饰内容候选池，输出可直接交给 media-fetcher 或 video-script 消费的结构化 URL 清单、账号信息、基础指标和视频类型标签。适用于需要批量巡检热门视频、搭建爆款样本池、从公开搜索结果或 Aeolus 导出中沉淀候选集的场景。
---
version: 1.1
# 热门雷达（hot-radar）

把“到处翻热门视频”变成一套有输入约束、有 NULL 契约、有结构化输出的候选池构建流程。

## Common Rationalizations（常见借口库）

以下借口一旦出现，视为准备绕过候选池数据契约：

- “先抓到链接再说，指标以后再补。”
- “这条视频应该很火，没看到播放量就先估一个区间。”
- “视频类型先凭感觉打标签，后面再慢慢修。”
- “找不到账号名也没关系，标题差不多就够用了。”
- “公开搜索抓不到 GMV，就先拿互动量替代。”
- “先给一堆 URL，结构化字段等下游再整理。”

## Red Flags（危险信号）

出现任意一条，必须降级、入 DLQ 或显式标 NULL：

- 未明确平台 / 市场 / 类目 / 时间窗口 / Top N，就开始捞数。
- 找不到指标时填 `0`、`-`、空字符串，或主观估算值，而不是 `NULL`。
- 同一候选集中混入不同平台或不同市场，但没有显式字段区分。
- 视频类型标签没有证据来源（标题、文案片段、账号定位、人工备注）。
- 输出不含 URL 主键、账号名、来源说明，导致下游无法去重和追溯。

## Verification（强制验收清单）

当你宣称“热门候选集已构建完成”时，必须同时满足：

1. **查询上下文完整**：平台、市场、类目、时间窗口、Top N 已明确。
2. **主键完整**：每条候选至少包含 `video_url`，并可追溯到 `source_type` / `source_note`。
3. **NULL 契约成立**：缺失指标统一写 `NULL`，禁止估算、禁止静默留空。
4. **标签可解释**：视频类型标签能回到标题关键词、描述片段、账号定位或人工备注。
5. **输出可消费**：结果可直接交给 `media-fetcher` / `video-script`，无需二次清洗字段名。

## 📌 技能简介

`hot-radar` 负责把“发现热门视频”这件事标准化：
- 先明确查询维度，再决定使用公开搜索、内部看板导出、人工白名单巡检等哪条链路。
- 最终统一产出结构化候选集，而不是一坨散乱链接。
- 对缺失指标坚持 `NULL` 合同，防止后续方法论沉淀被幻觉脏数据污染。

## 🔑 触发词

- 核心关键词：
  - 热门雷达
  - 热门视频候选集
  - TikTok Shop Top 视频
  - 抖音跨境热视频
  - 爆款样本池
- 典型指令示例：
  > 帮我做一个 TTS US 女装近 7 天 Top 50 热门视频候选池。
  > 先把抖音跨境服饰相关热视频整理成可下载的 URL 清单。

## 何时使用

当任务满足以下任一条件时触发：

- 需要按平台 / 市场 / 类目捞取一批热门视频候选。
- 需要把公开搜索结果、Aeolus 导出、人工巡检结果统一成结构化 manifest。
- 需要给 `media-fetcher` 提供批量 URL 输入。
- 需要沉淀长期可复用的“爆款样本池”。

## Defaults（合规默认值）

- `DEFAULT_TOP_N = 50`
- `DEFAULT_METRIC_NULL = "NULL"`
- `DEFAULT_SOURCE_TYPES = ["public_search", "aeolus_export", "manual_watchlist"]`
- `DEFAULT_VIDEO_TYPE_TAGS = ["口播", "剧情", "测评", "种草", "直播切片", "混剪"]`
- `DEFAULT_OUTPUT_FILE = "hot_radar_candidates.json"`

## ⚙️ 核心架构 / SOP / 约束条件

### Step 1：先锁查询合同

先明确以下字段，再开始发现：
- `platform`：如 `TikTok Shop` / `抖音跨境`
- `market`：如 `US` / `UK` / `JP` / `Global`
- `category`：如 `女装` / `服饰` / `跨境电商`
- `time_window`：如 `近7天` / `近30天`
- `top_n`：候选条数上限

若其中任一字段缺失，先补齐或用默认值，不要直接盲搜。

### Step 2：选择发现链路

根据上下文选择最可靠的数据入口：

1. **公开搜索链路**：适合先做公开候选池。
   - 用 `search(web)` 找公开榜单、公开视频页、账号主页或合集页面。
   - 只能记录看得到的事实；看不到的指标写 `NULL`。
2. **Aeolus / 内部导出链路**：适合已有榜单或导出文件。
   - 读取导出 CSV / JSON 后，统一进标准 schema。
   - 不允许改写原始指标含义。
3. **人工巡检链路**：适合白名单账号、专题活动、临时爆点。
   - 必须补 `source_note`，说明候选为何进入池子。

### Step 3：统一字段 schema

标准输出字段至少包含：

- `video_url`
- `platform`
- `market`
- `category`
- `account_name`
- `video_title`
- `publish_time`
- `view_count`
- `like_count`
- `comment_count`
- `share_count`
- `gmv`
- `video_type_tags`
- `is_live_clip`
- `source_type`
- `source_note`

任何缺失的数值/文本指标统一填 `NULL`，而不是空字符串或 0。

### Step 4：标签归一化

视频类型标签优先依据：
- 标题关键词
- 描述 / 文案片段
- 账号定位
- 人工备注

常见映射：
- `try on` / `ootd` / `上身` → `种草`
- `review` / `测评` / `对比` → `测评`
- `live clip` / `直播切片` / `直播间` → `直播切片`
- `story` / `剧情` / `反转` → `剧情`
- 以上都不命中时，保留 `其他` 或人工补标。

### Step 5：去重与输出

- 以 `video_url` 为主键去重。
- 保留首次出现的来源说明，必要时合并 `source_note`。
- 输出 JSON manifest，供 `media-fetcher` 批量消费。
- 如存在非法 URL 或关键字段缺失，写入 DLQ，而不是混入主清单。

## Runtime Assertions（运行时断言）

执行脚本前后至少满足以下断言：

```python

def validate_query(platform, market, category, top_n):
    if not all([platform, market, category]):
        raise ValueError("platform / market / category 不完整，禁止继续")
    if int(top_n) <= 0:
        raise ValueError("top_n 必须大于 0")


def validate_candidate_row(row):
    if not str(row.get("video_url", "")).startswith(("http://", "https://")):
        raise ValueError("候选缺少合法 video_url")


def validate_null_contract(row):
    forbidden = {"", None, "N/A", "unknown"}
    for key in ["view_count", "like_count", "comment_count", "share_count", "gmv"]:
        if row.get(key) in forbidden:
            raise ValueError(f"字段 {key} 必须使用 NULL，而不是空值")
```

## 推荐脚本

当输入已经有一批候选记录（CSV / JSON），用下列脚本统一归一化：

```bash
python3 scripts/build_candidate_manifest.py \
  --input-path data/raw_candidates.json \
  --output-path output/hot_radar_candidates.json \
  --platform "TikTok Shop" \
  --market "US" \
  --category "服饰" \
  --time-window "近7天" \
  --top-n 50
```

## 输出口径要求

- `hot-radar` 负责候选发现与整理，不负责伪造榜单权威性。
- 看得到的数据就写事实，看不到的就写 `NULL`。
- 如果来源是公开搜索，必须把 `source_type` 标成 `public_search`。
- 如果来源是内部导出，必须保留原来源说明，方便后续复盘。

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：
  ```text
  帮我整理 TTS US 女装近 7 天 Top 30 热门视频候选集，先给 media-fetcher 用。
  ```
- 🤖 标准输出：
  ```text
  已先锁定查询合同（平台=TikTok Shop，市场=US，类目=女装，时间窗口=近7天，TopN=30），
  再把公开搜索/Aeolus 导出的候选统一整理成标准 manifest。
  缺失指标全部显式写 NULL，输出可直接交给 media-fetcher 批量下载。
  ```

## Changelog

- **v0.1 (2026-06-14)**：首版发布，固化“查询合同 → 多源发现 → 字段归一化 → 标签归一化 → JSON manifest 输出”的热门候选池流程。

## 操作示例

- 读取文档：按需读取本 skill 的 `SKILL.md`。
- 执行脚本：先进入本 skill 根目录，再执行 `python3 scripts/build_candidate_manifest.py ...`。
- 若任务需要进一步下载媒体，直接把输出 JSON 交给 `media-fetcher`。
