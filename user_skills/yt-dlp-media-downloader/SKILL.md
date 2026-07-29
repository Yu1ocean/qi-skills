---
name: yt-dlp-media-downloader
description: 使用 yt-dlp 作为媒体物理摄入探针，绕过常规网页抓取在 Visitor System、403、登录墙、反爬校验下的失效，并稳定完成视频/音频探测、最佳画质下载、音轨剥离与元信息留存。适用于用户提供 B 站、微博等媒体链接且常规爬虫/请求被拦截、需要先把内容抓到本地再继续分析、转写或归档的场景。
---

# yt-dlp 媒体物理摄入探针

当用户提供视频或音频链接，且常规 HTTP 抓取、网页提取或浏览器请求已经被 Visitor System、403、登录墙、风控签名、首帧可见但正文不可取等机制拦住时，优先调用本 skill，把 `yt-dlp` 作为前置“物理摄入探针”。

## Common Rationalizations（常见借口库）
- “先用普通网页抓取再试几次，也许就通了。”
- “能看到页面标题，说明视频也能直接抓下来。”
- “用户只要音频，没必要先探测格式信息。”
- “先下最差清晰度凑合，回头再补高码率版本。”
- “下载报错就口头建议用户自己试，不必保留 stderr 证据。”

## Red Flags（危险信号）
- 链接明显是媒体页，却还在用通用网页抓取反复撞墙。
- 已出现 Visitor System、403、登录墙、需登录、需签名、anti-bot 等报错，却没有切换到 `yt-dlp`。
- 没有先做 `probe` 探测，就直接下载。
- 用户要音频，却只下载了整段视频且未抽音轨。
- 下载后没有输出文件路径、元信息 JSON 或失败 stderr 摘要。

## Verification（强制验收清单）
当宣称“媒体已成功摄入”时，必须同时满足：
1. 已先执行 `probe`，拿到基础元信息或明确错误。
2. 已根据任务类型选择 `video` 或 `audio` 模式，而不是拍脑袋执行默认下载。
3. 已产出本地文件路径，且文件真实存在。
4. 已保留一份 JSON 元信息文件，便于后续转写、归档或复盘。
5. 若失败，已返回 stderr / 提取器报错要点，而不是笼统说“下载失败”。

## 🔑 触发词
- 核心关键词：
  - yt-dlp
  - 下载视频
  - 下载音频
  - Visitor System
  - 403
  - 登录墙
  - B站
  - 微博视频
  - 媒体抓取失败
- 典型指令示例：
  - “这个 B 站链接被 Visitor System 拦了，帮我把视频弄下来。”
  - “微博这个视频普通抓取 403 了，先下本地再转文字。”
  - “给你一个视频链接，帮我只提音频。”

## 输入要求
- 必填：媒体页面 URL。
- 可选：
  - `mode`：`probe` / `video` / `audio`
  - `output_dir`：下载目录；未指定时默认写入 `downloads/yt_dlp_media/`
  - `filename_template`：自定义文件名模板
  - `cookies_file`：当站点需要登录态时传入 cookies 文件
  - `extra_args`：额外 yt-dlp 参数（仅在明确需要时使用）

## ⚙️ 核心架构 / SOP / 约束条件

### 台账闭环（新增）
- 所有 `probe / video / audio` 执行结束后，脚本都会自动向飞书台账 **《yt-dlp 媒体探测下载台账》** 追加一行记录。
- 当前固定台账地址：`https://bytedance.my.larkoffice.com/sheets/WqYCsiQ46hWZPYtaem7mN0Lyy8g`
- 记录字段包含：`记录ID / 执行时间 / 模式 / 执行状态 / 来源站点 / 提取器 / 媒体标题 / 媒体ID / 上传者 / 时长秒数 / 输出目录 / 主产物路径 / 元信息JSON路径 / 源链接 / stderr摘要`
- 设计原则：**单行追加、执行后落账、成功失败都留痕**。即使提取失败，也要把失败状态与错误摘要写入台账，方便后续排障与归档。
- 兜底策略：若飞书台账暂时不可写，媒体抓取主流程不应被台账写入故障反向打崩；脚本需在标准输出 JSON 中显式回传 `ledger.status=failed` 与错误原因。

### Step 1：识别是否命中本 skill
命中任一条件就优先使用本 skill：
- 用户明确给出视频/音频链接，并表达“下载 / 保存 / 提取音频 / 转写前先抓下来”。
- 常规抓取已报错：`403`、`Visitor System`、`需登录`、`anti-bot`、`forbidden`、`unable to extract`。
- 目标站点属于典型媒体平台，如 B 站、微博、YouTube、X/Twitter 视频页等。

### Step 2：先探测，再下载
始终先执行 `probe`，统一通过 `scripts/yt_dlp_fetch.py` 调用：

```bash
python3 scripts/yt_dlp_fetch.py --mode probe --url "<媒体链接>"
```

探测阶段只做两件事：
- 验证提取器能否识别该链接
- 输出基础元信息 JSON（标题、提取器、时长、上传者、直链候选等）

### Step 3：按任务类型选择下载模式
#### A. 下载最佳音视频
```bash
python3 scripts/yt_dlp_fetch.py --mode video --url "<媒体链接>"
```
默认策略：
- 优先 `bv*+ba/b`，拿最佳视频+最佳音频，必要时自动合并
- 输出目录默认 `downloads/yt_dlp_media/`
- 自动落地 `<safe_title>_<id>.info.json`

#### B. 仅抽取音频
```bash
python3 scripts/yt_dlp_fetch.py --mode audio --url "<媒体链接>"
```
默认策略：
- 使用 `-x --audio-format mp3`
- 适用于 ASR、会议摘录、播客转写等后续流程

### Step 4：需要登录态时再加 cookies
若 probe 或下载报“需登录 / 仅粉丝可见 / 年龄限制 / 权限不足”，再使用 cookies：

```bash
python3 scripts/yt_dlp_fetch.py \
  --mode video \
  --url "<媒体链接>" \
  --cookies-file "<cookies.txt>"
```

### Step 5：把结果交给后续任务
成功下载后，继续根据目标任务把文件交给后续链路：
- 做转写 → 交给语音/视频处理流程
- 做归档 → 上传云盘并保留元信息 JSON
- 做内容分析 → 基于本地文件而不是网页链接继续处理
- 做审计 → 自动回看本次执行输出里的 `ledger` 字段，确认飞书台账单行追加是否成功

## 合规默认值（Defaults）
- 默认输出目录：`downloads/yt_dlp_media/`
- 默认视频策略：`bv*+ba/b`
- 默认音频格式：`mp3`
- 默认文件名模板：`%(title).120B_[%(id)s].%(ext)s`
- 默认保留元信息：开启 `--write-info-json`
- 默认不传 cookies：只有遇到登录墙时才显式补充

## 运行时断言（L3）
- `scripts/yt_dlp_fetch.py` 在真正调用 `yt-dlp` 前必须先执行 `validate_mode`、`validate_url`、`validate_cookies_file`。
- 任一校验失败都必须直接 `raise ValueError` / `FileNotFoundError` / `RuntimeError`，禁止带病继续下载。

## 失败重试策略
- 提取器失败：先重新执行 `probe`，保留完整报错。
- 视频模式失败但用户只要语音：改走 `audio` 模式。
- 平台需要登录：要求补充 `cookies_file` 后重试。
- 单链接失效但页面仍可访问：尝试页面 canonical URL 或分享短链原始地址。
- 若 `yt-dlp` 本身无法识别，明确返回当前 extractor 报错，不要伪造成功。

## 📖 案例实录 (Best Practice)
- 🧑‍💻 用户输入：
  ```text
  这个 B 站链接被 Visitor System 拦了，先帮我把视频下载下来。
  ```
- 🤖 标准输出：
  ```text
  已切换到 yt-dlp 作为前置物理摄入探针，先 probe 再下载最佳音视频；若站点需要登录态，再补 cookies 重试。交付物至少包含下载文件路径和 info.json 元信息。
  ```

## 更新日志 (Changelog)
- 1.1（2026-06-08）：新增飞书台账 **《yt-dlp 媒体探测下载台账》**，`scripts/yt_dlp_fetch.py` 在每次 `probe / video / audio` 执行后自动单行追加日志，并在标准输出 JSON 中新增 `ledger` 回传结构；补齐失败留痕与台账写入兜底口径。
- 1.0（2026-06-08）：首版发布，固化“probe → video/audio → cookies 兜底 → 元信息留存”的媒体物理摄入 SOP。
