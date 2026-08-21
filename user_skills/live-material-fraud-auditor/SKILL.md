---
name: live-material-fraud-auditor
version: 1.1
description: 对 TikTok / Pearl 等平台的直播回放进行材质造假与品牌授权合规审核。适用于需要产出完整逐字稿、风险取证命中表与飞书审核报告的直播合规质检场景；覆盖视频摄入探针、60 秒分段 ASR 转写、材质/品牌风险关键词命中、风险分级判定、ASR 误识别复核与断点续跑。
author: yuqinan
---

# 直播材质造假与品牌授权审核员 (live-material-fraud-auditor)

对直播回放做**材质造假**（假 14K / 假真金 / 假防水）与**品牌授权/正品宣称**的合规审核，产出可取证的逐字稿 + 命中表 + 飞书审核报告。

审核对象是「主播说了什么」，而不是「商品页写了什么」，所以整条链路的可信度完全建立在**音频被完整摄入、时间戳绝对准确、命中可回溯**这三件事上。下面所有护栏都是为了让这三件事不被"看起来完成了"糊过去。

## 🔑 触发词

- 核心关键词：
  - 直播材质审核
  - 材质造假审核
  - 直播合规审核
  - live-material-fraud-auditor
  - 假 14K / 假真金 / 假防水
  - 品牌授权宣称 / 正品宣称
- 典型指令示例：
  > 帮我审核这场直播回放有没有材质造假（假 14K、假真金）和品牌授权问题
  > 这个 Pearl 回放 roomId=xxx，做一遍直播合规审核并出飞书报告

## Common Rationalizations（常见借口库）

以下话术一旦出现，等价于准备伪造审核结论，必须立刻停下并回到 SOP：

- "回放 20 小时太长，抽查几段有代表性的就够了。"
- "最后几分钟抽出来是空 WAV，跳过不写说明也没人看得出来。"
- "一段切 5 分钟效率更高，ASR 应该扛得住。"
- "先用片段内的相对时间戳，最后再统一加偏移。"
- "写完飞书就算落盘了，回读校验太慢先跳过。"
- "`official` 命中就是品牌宣称，直接算高风险，不用回听。"
- "覆盖到 80% 已经能得出结论了，汇报时先说全量完成。"
- "`feishu-doc-writing-guide` 太重，我直接调 lark API 写文档更快。"

## Red Flags（危险信号）

出现任意一条，必须熔断或要求人工确认，不得继续推进结论：

- 写入飞书后**没有 RAW 回读**，就宣称"已更新 / 已完成"。
- 汇报的覆盖范围**大于**实际 RAW 校验通过的区间（虚报全量完成）。
- 把 ASR 疑似项（如 `official` 疑似"老主顾"误识别）当作**已确认事实**写进审核结论。
- 尾段抽出空 WAV 但**未在覆盖说明中显式写出**，让读者误以为全程有效音频。
- 单段音频**超过 60 秒**仍送 ASR（超时与时间戳漂移风险）。
- 逐字稿使用**片段内相对时间戳**，而不是回放绝对偏移。
- 绕过 `user_skills/feishu-doc-writing-guide`，裸调飞书 OpenAPI / lark MCP 直写文档。
- 断点文件缺失或未更新，续跑时重跑已完成区间 / 漏跑未完成区间。
- 命中表缺少「时间戳 + 原文」任一项，导致命中无法回溯取证。

## Verification（强制验收清单）

宣称"审核完成"时，必须同时满足：

1. **摄入可证**：已用 `yt-dlp-media-downloader` 完成 probe（或 m3u8 降级 probe），并留有 probe 输出。
2. **切片合规**：全部音频片段时长 ≤ 60 秒，且每段起止均为回放绝对偏移；`validate_segment_duration()` 全部通过。
3. **时间戳绝对**：逐字稿所有时间戳为 `HH:MM:SS` 绝对偏移；`validate_timestamp_absolute()` 通过。
4. **命中可回溯**：命中表每条含「时间戳 + 原文 + 风险类别 + 风险等级」四要素，由 `risk_keyword_scanner.py` 产出而非手写。
5. **疑似项隔离**：所有 `need_human_review=true` 的命中单独列入「待人工复核清单」，未混入已确认结论。
6. **写后回读**：每批写入飞书后经 `assert_raw_readback()` 校验通过；未通过即熔断。
7. **覆盖如实**：覆盖说明包含实际覆盖区间、总时长、尾段空 WAV 情况；`validate_coverage_report()` 通过。
8. **断点一致**：断点文件记录的最新 `revision_id` 与已覆盖区间，与飞书文档实际内容一致。
9. **报告五段齐备**：逐字稿 / 命中表 / 阶段性结论 / 待复核清单 / 覆盖说明五段均存在。

## 适用场景

- 直播回放的材质造假审核（14K、真金、防水、不掉色、实心等宣称）。
- 直播回放的品牌授权与正品宣称审核（official / authorized / genuine、奢侈品牌名）。
- 需要产出完整逐字稿 + 可取证命中表 + 飞书审核报告的合规质检。
- 长时长回放（10 小时以上）需要分段推进、断点续跑、分批落盘的场景。

## SOP

### 1. 视频摄入策略

目标平台：Pearl（`pearl.tiktok-row.net`）、TikTok。

1. 首选用 `user_skills/yt-dlp-media-downloader` 对**页面 URL** 做 `probe`。
2. 若报 `Unsupported URL`，从页面中抓取 **HLS m3u8 地址**，用 m3u8 重新 probe。这是 Pearl 场景的主路径——回放页本身不被 extractor 识别，但 m3u8 可直取。
3. **内置字幕探查**：检查 `video.textTracks`。为空即说明平台没有内置 Transcript，必须**排除**字幕路径，完全依赖音频 ASR；不要反复尝试拉字幕浪费时间。
4. **音频抽取以 60 秒为单位分段**输出 WAV。长段会同时带来 ASR 超时和时间戳漂移，60 秒是实战验证过的安全上限。
5. **尾段判定**：若某段（常见于最后 3–4 分钟）物理抽取得到**空 WAV**，判定为"回放无有效音频"，记录说明，**不算漏跑**——但必须在报告第 ⑤ 段覆盖说明中显式写出，否则等于隐瞒覆盖缺口。

### 2. ASR 转写规范

- 每段 60 秒，逐段 ASR 后**立即**追加写入本地 Markdown 逐字稿（防止长任务中断丢结果）。
- 时间戳格式 `HH:MM:SS`，且必须是**回放绝对偏移**。片段内相对偏移会让命中无法回溯，取证直接作废。
- 每完成一批片段（建议 5–10 段）立即写回飞书，并做 **RAW 回捞校验**。
- **未 RAW 校验绝不汇报"已更新 / 已完成"**。

### 3. 材质造假风险关键词库（高风险组合词）

完整词表见 [material_risk_keywords.yaml](references/material_risk_keywords.yaml)，核心分组：

| 分组 | 关键词 |
|---|---|
| 纯度标记 | `14K`、`14k stamp`、`40K` |
| 真金宣称 | `real gold plated`、`real golden`、`gold plated` |
| 防水不变色 | `waterproof`、`no tarnish`、`no fading`、`no green`、`turn skin green` |
| 使用场景 | `shower`、`swimming`、`take bath`、`keep shining` |
| 物理强度 | `scratch-proof`、`solid`、`no hollow` |
| 检测背书 | `pass the diamond test`、`magnetic test` |

### 4. 品牌 / 正品宣称关键词库

完整词表见 [brand_risk_keywords.yaml](references/brand_risk_keywords.yaml)：

- 授权类：`official`、`authorized`、`genuine`
- 奢侈品品牌名：`Rolex`、`Cartier` 等

当这些词与 `14K` / `stamp` / `gold plated` 在**同句或近邻 3 句内**组合出现时，升级为高风险——单独出现只是宣称，叠加材质宣称就构成"用品牌背书假材质"。

### 5. 风险分级判定标准

| 等级 | 判定条件 |
|---|---|
| 🔴 高（材质造假） | `real gold plated` + `14K stamp` 叠加，且无明显"镀金"澄清 |
| 🟡 中-高（品牌宣称） | `official` / `authorized` / `genuine` 单独出现 → 需联查挂车商品标题、详情页、包装、评论后定级 |
| 🔴 高（误导性背书） | `pass diamond test` / `magnetic test` + 实心 / 真金宣称 |

### 6. ASR 误识别处理规范

- 对可疑命中必须标注"**需人工回听**"。真实案例：中文口语"老主顾"被 ASR 误识别为 `official`，若直接采信会凭空造出品牌宣称风险。
- 疑似项**不得**作为已确认事实纳入审核结论，单独列入"待复核清单"。
- `risk_keyword_scanner.py` 会对这类命中自动打 `need_human_review=true`，但脚本只做召回，最终定性仍需人工回听确认。

### 7. 飞书报告结构（固定五段）

① 全量逐字稿
② 取证命中表（时间戳 + 原文 + 风险类别 + 风险等级）
③ 阶段性审核结论
④ 待人工复核清单
⑤ 覆盖说明（含尾段空 WAV 情况）

写入**必须**调用 `user_skills/feishu-doc-writing-guide`（禁止裸调 lark MCP / 禁止 OpenAPI 直连），每次写入后做 RAW 回捞校验。

### 8. 断点续跑机制

- 每次写回飞书后，记录最新 `revision_id` 与"已覆盖时间范围"，落盘为断点文件（建议 `temp_data/progress.json`）。
- 续跑时从最新**RAW 校验通过**的断点继续，不重跑已完成区间。
- 汇报时如实告知真实覆盖范围，**禁止虚报全量完成**。

### 9. 最终判定输出格式

```
材质宣传风险：🔴 高 / 🟡 中-高 / 🟢 低
品牌/正品宣称风险：🔴 高 / 🟡 中-高 / 🟢 低
总命中条数：XX条（材质XX条 / 品牌XX条）
待人工复核：XX条
```

## 脚本用法

两个脚本都必须通过 `bash` 工具直接执行；涉及飞书回读时设置 `include_secrets=true`。

**风险关键词扫描（产出命中表）**：

```bash
cd user_skills/live-material-fraud-auditor
python3 scripts/risk_keyword_scanner.py --transcript <逐字稿.md> --out-json hits.json --out-csv hits.csv
```

- 输入：`HH:MM:SS` 时间戳格式的逐字稿 Markdown。
- 输出：命中表（JSON + CSV），字段含 `timestamp` / `text` / `category` / `risk_level` / `matched_keywords` / `need_human_review` / `neighbor_window`。
- 自检：`python3 scripts/risk_keyword_scanner.py --self-test`

**运行时护栏（副作用前物理熔断）**：

```bash
cd user_skills/live-material-fraud-auditor
python3 scripts/audit_guard.py --self-test
```

提供的 gate（供编排脚本 import 或 CLI 调用）：

| 函数 | 熔断条件 |
|---|---|
| `validate_segment_duration()` | 单段音频 > 60 秒 |
| `validate_timestamp_absolute()` | 时间戳非绝对偏移 / 非 `HH:MM:SS` / 倒退 |
| `assert_raw_readback()` | 写入飞书后回读内容与预期不一致 |
| `validate_coverage_report()` | 覆盖说明缺失实际区间或尾段空 WAV 说明 |
| `validate_hit_row()` | 命中行缺少时间戳 / 原文 / 类别 / 等级 |
| `validate_progress_checkpoint()` | 断点文件缺 `revision_id` 或已覆盖区间 |

CLI 单点校验示例：

```bash
python3 scripts/audit_guard.py --check segment --seconds 75          # 预期熔断
python3 scripts/audit_guard.py --check coverage --coverage-file coverage.md
```

## 合规默认值（Defaults）

- 默认分段时长：**60 秒**（`DEFAULT_SEGMENT_SECONDS`）
- 默认时间戳格式：`HH:MM:SS` 绝对偏移（`DEFAULT_TIMESTAMP_FORMAT`）
- 默认邻近窗口：**3 句**（`DEFAULT_NEIGHBOR_WINDOW`）
- 默认批次大小：**5–10 段**（`DEFAULT_BATCH_SEGMENTS = 8`）
- 默认写后等待：**2 秒**再回读（`DEFAULT_RAW_SLEEP_SECONDS`）
- 默认飞书写入通道：`user_skills/feishu-doc-writing-guide`
- 默认摄入通道：`user_skills/yt-dlp-media-downloader`
- 默认断点文件：`temp_data/progress.json`
- 默认报告段数：5（逐字稿 / 命中表 / 结论 / 待复核 / 覆盖说明）

## 约束条件

- 摄入、转写、写入三段都以"可回读证据"为交付标准，命令退出码 0 不等于成功。
- 关键词库外化在 `references/*.yaml`，新增词请改 YAML 而不是改脚本，保证审核口径可审计。
- 脚本只做**召回与熔断**，不做定性；🟡 中-高 一律需要联查商品页与人工确认。
- 长任务必须分批 + 断点，单次尝试覆盖全部时长会在中断时丢失全部上下文。

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：

```text
帮我审核这场 Pearl 直播回放有没有材质造假和品牌授权问题：roomId=7667566803098323734（GB 市场）
```

- 🤖 标准输出：

```text
1. yt-dlp probe 页面 URL 失败（Unsupported URL），改用页面 HLS m3u8 重新 probe 成功；textTracks 为空 → 排除内置字幕，走音频 ASR。
2. 按 60 秒切片抽 WAV，逐段 ASR 并即时追加逐字稿；末段 3–4 分钟抽出空 WAV，记为"回放无有效音频"。
3. 实际有效覆盖 00:00:00–20:16:10（总时长 20:19:52）。
4. risk_keyword_scanner.py 命中材质高风险 75+ 条、品牌/正品 8+ 条；"老主顾"误识别为 official 的条目已打 need_human_review。
5. 五段结构写入飞书审核报告并逐批 RAW 回捞校验通过。
```

实战记录见 [pearl-case-2026-08.md](references/pearl-case-2026-08.md)。

## 更新日志 (Changelog)

- 1.1（2026-08-21）：首版发布。固化 Pearl 20 小时回放实战经验：m3u8 降级 probe、60 秒切片 ASR、绝对时间戳、材质/品牌双词库与邻近 3 句升级规则、ASR 误识别隔离、五段报告结构、RAW 回读与断点续跑；配套 `risk_keyword_scanner.py`（命中召回）与 `audit_guard.py`（L3 运行时熔断）。
