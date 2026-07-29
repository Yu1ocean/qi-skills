---
name: speech-knowledge-precipitation
description: 将长音视频、演讲、对谈或飞书妙记转写沉淀为结构化知识文档。支持本地音频 ASR 切片转写，也支持以 minutes_transcript 作为一等输入源跳过 ASR，直接进入逐字稿规范化、L1-L4 提炼、零信任 QA 与飞书 Docx 归档。适用于视频解析、演讲复盘、会议妙记沉淀、知识提炼、逐字稿整理与飞书归档场景。
---

<!-- SSOT version marker (read by skill-forge-pipeline-v4 register_skill.py) -->
version: 1.1
# 演讲知识沉淀 (Speech Knowledge Precipitation v1.1)

把任意一段长音视频 / 演讲 / 对谈 / 飞书妙记转写内容，**严谨、防幻觉、可回溯**地沉淀为一份结构化飞书知识资产。

> **v1.1 变更要点**：新增 `minutes_transcript` 作为一等输入源。当上游已经通过飞书妙记产出 transcript 时，本技能必须跳过 ASR 音频切片，直接执行逐字稿规范化 → L1-L4 结构化提炼 → 零信任 QA → 飞书 Docx 归档；妙记 Summary/Todo/Chapter 只能作为辅线，不能替代原始 transcript 分析。

## Common Rationalizations（常见借口库 - L1 反合理化）

以下借口一旦出现，视为"准备绕过零信任护栏"，必须立刻停下并回到 SOP：

- "音频太长，先截开头 10 分钟跑跑看效果。"
- "中间这段听不清，先跳过算了，反正大纲能编出来。"
- "ASR 失败一次先不重试，先继续后面的步骤。"
- "时间戳算不准，先估个大概给用户。"
- "逐字稿太长就不全量贴附录了，给摘要就行。"
- "飞书写入网关麻烦，先用 OpenAPI 直连一下。"
- "DOC 编号先猜一个，归档台账回头再补。"
- "QA 比对很慢，先跳过 zero-trust-qa-checker。"
- "已经有飞书妙记 transcript 了，但还是按默认音频切片 ASR 跑一遍更保险。"
- "妙记 Summary 看起来够用了，直接拿 Summary 生成知识文档，不回看逐字稿。"

## Red Flags（危险信号 - L1 反合理化）

出现任意一条，必须熔断或要求用户确认：

- 切片转写时**任何一段** ASR 失败但没有触发 ≥2 次重试。
- 重试后仍失败的片段**没有在最终文档中显式标注缺失范围**。
- 大纲里出现"具体数字 / 案例 / 引语"，但在逐字稿全文中找不到对应原文。
- L1-L4 切片缺时间戳，或时间戳没有精确到秒。
- 飞书文档创建/写入未走 `feishu-doc-writing-guide` 网关。
- 落盘文档新建时没有显式 `target_type=personal`，未把 `yuqinan@bytedance.com` 设为 Owner。
- 【图书馆】SSOT 台账写入后未做 RAW 写后回读核对。
- DOC 编号绕开 `omni-asset-archiver` 发号器自创格式。
- `input_source=minutes_transcript` 时仍调用 `scripts/slice_audio.py` 或 `scripts/transcribe_segments.py` 重跑 ASR。
- 妙记 transcript 缺少可解析时间戳却继续生成 L1-L4 空降链接。
- 最终文档未写入 `minute_url` / `minute_token` 等原始来源锚点。

## Verification（强制验收清单 - L1 反合理化）

宣称"知识沉淀完成"时，必须同时满足：

1. **逐字稿完整性**：所有切片转写结果都成功合并；失败片段已显式列出缺失时间区间（如：`[12:00 - 18:00] 转写失败，已重试 3 次`），不允许静默丢弃。
2. **时间戳精度**：L4 切片每条都附 `HH:MM:SS` 或 `?t=<seconds>` 跳转标注；本地音频则使用 `[<音频文件名> @ HH:MM:SS]`。
3. **大纲对应性**：L1-L4 中每个论据 / 案例 / 金句都能回到逐字稿原文（zero-trust-qa-checker 抽样比对通过）。
4. **飞书落盘合规**：文档由 `feishu-doc-writing-guide` 创建，`target_type=personal`，Owner 为 `yuqinan@bytedance.com`。
5. **台账归档闭环**：通过 `omni-asset-archiver` 写入【图书馆】，DOC 编号匹配 `^DOC-\d{4}-\d{2,4}$` 月维度白名单，并完成 RAW 写后回读校验。
6. **输出契约一致**：飞书文档结构必须严格符合"100 字高光 + 全局大纲 + 多主题 L1-L4 + 秒级时间戳 + 空降链接 + 高精逐字稿附录"模板。
7. **妙记输入契约**：若 `input_source=minutes_transcript`，必须存在 `source_manifest.json`，且包含 `minute_token / minute_url / source_audio_name / transcript_path`；最终 Docx 第一屏必须可见原始来源锚点。

## 触发条件 (Trigger Conditions)

当用户提供以下任一输入并要求"提取知识 / 总结 / 沉淀 / 归档"时触发：
- 长视频 URL（Bilibili、YouTube 等）
- 本地音频文件路径（`.wav` / `.mp3` / `.m4a` 等）
- 已有逐字稿文本 + 媒体文件路径
- 飞书妙记 transcript 产物：`input_source=minutes_transcript`，包含 `transcript_path / minute_token / minute_url / source_audio_name` 等元数据

## 合规默认值 (Defaults - L2 默认层)

- `DEFAULT_SLICE_SECONDS = 1080`：切片时长 18 分钟（≤ 20 min 防超时）。
- `DEFAULT_MAX_RETRIES = 3`：ASR 单段最多重试次数。
- `DEFAULT_TARGET_TYPE = "personal"`：飞书文档默认落到用户个人空间。
- `DEFAULT_OWNER_EMAIL = "yuqinan@bytedance.com"`：所有产出文档默认 Owner。
- `DEFAULT_DOC_PREFIX = "DOC"`：DOC-YYMM-NNN 月度发号。
- `DEFAULT_ARCHIVE_TARGET = "library_registry"`：【图书馆】台账归档预设。
- `DEFAULT_ASR_TASK_PROMPT = "逐字转写音频内容，标注每个发言段落的开始时间（秒）。中文输出。保留完整原文，不要总结。"`：ASR 调用模板。
- `DEFAULT_INCLUDE_SECRETS = True`：所有飞书 / 云盘脚本必须传 `include_secrets=true`。
- `DEFAULT_INPUT_SOURCE = "audio_or_video"`：默认保持 v1.0 兼容路径；只有显式提供 `input_source=minutes_transcript` 时才进入妙记 transcript 分支。
- `DEFAULT_MINUTES_TRANSCRIPT_REQUIRED_FIELDS = ["transcript_path", "minute_token", "minute_url", "source_audio_name"]`：妙记输入一等契约。

## 5-Phase 标准化作业流程 (5-Phase SOP)

### Phase 1：媒体抽水 / 妙记导入与高精转写 (Media Extraction, Minutes Import & ASR)

**目标**：从原始多媒体文件或已有飞书妙记 transcript 中拿到一份完整、带时间戳、可追溯来源的高精度逐字稿。

0. **输入模式判定**：
   - 默认路径：未声明 `input_source`，或 `input_source=audio_or_video`，继续执行媒体准备、切片与 ASR。
   - 妙记导入路径：当 `input_source=minutes_transcript` 时，**必须跳过** `scripts/slice_audio.py` 与 `scripts/transcribe_segments.py`，直接调用 `scripts/normalize_minutes_transcript.py`。
1. **妙记 transcript 导入（v1.1 新增）**：
   - 输入字段必须包含：`transcript_path / minute_token / minute_url / source_audio_name`，`note_id / raw_summary / raw_todos / raw_chapters` 可选。
   - 调用 `scripts/normalize_minutes_transcript.py` 统一编码、标准化时间戳、生成 `transcript_full.md` 与 `source_manifest.json`。
   - 妙记 Summary/Todo/Chapter 只能作为辅线 metadata，不能替代 transcript 主分析。
2. **媒体准备（向后兼容 v1.0）**：
   - 视频 URL：用 `yt-dlp -x --audio-format wav <URL>` 抽出音频（保存为 `.wav` / `.m4a`）。
   - 本地音频：直接复用，禁止二次有损转码。
2. **防超时切片**：调用 `scripts/slice_audio.py`，把音频切成 ≤ `DEFAULT_SLICE_SECONDS`（18 分钟）的片段，并产出 `segments_manifest.json`（含每段 `index / start_seconds / end_seconds / path`）。
3. **高精转写**：调用 `scripts/transcribe_segments.py`，对每段调用由环境变量 `AIME_ANALYZE_AUDIO_SCRIPT` 指定的音频分析工具，task 使用 `DEFAULT_ASR_TASK_PROMPT`。
   - 单段失败必须重试至 `DEFAULT_MAX_RETRIES`，否则在合并稿中显式插入 `[GAP: <start>-<end> 转写失败 ×3]` 占位（**严禁静默丢弃**）。
   - 合并所有片段时，每段内部时间戳必须加上该片段的全局起始偏移（`segment.start_seconds`）。
4. **产出**：`transcript_full.md`（带 `HH:MM:SS` 时间戳的全量逐字稿）。

### Phase 2：降维与结构化重构 (Dimensionality Reduction)

基于 `transcript_full.md`，由本技能直接做语义分析（也可调用 `scripts/build_outline.py` 中的辅助方法），输出：
- **100 字核心高光（Core Highlights）**：精准概括中心思想与最高价值点。
- **全局高阶大纲（High-level Outline）**：5 ~ 10 条 L1 级方向，勾勒整体逻辑骨架。

### Phase 3：L1-L4 深度切片与赛博外挂 (Thematic Slicing & Deep-Links)

把全局大纲解构为深度链接的精细化知识单元，遵守 **L1-L4 知识分类法**：
- **L1（方向）**：最高层级的核心议题或领域。
- **L2（论点）**：支撑 L1 的关键性主张或观点。
- **L3（论据）**：用于支撑 L2 的具体解释、数据或逻辑。
- **L4（案例 / 金句）**：具体实例、故事、引用或数据点。

赛博外挂（Cyber-augmentation）强制要求：
- **时间戳空降链接**：
  - 视频 URL 输入：`?t=<seconds>` 形式（B 站 / YouTube 兼容），并展示为 `[HH:MM:SS]` 锚文本。
  - 本地音频输入：`[<音频文件名> @ HH:MM:SS]`，明确标注是本地文件、非 URL 跳转。
- **原声金句（Quote）**：对关键论点直接引用原文，标记 `> 原声金句：……`。

### Phase 4：零信任质检与遗漏回捞 (Zero-Trust QA)

为防 AI 在降维中丢失关键信息，强制启用零信任质检：
- 准备 QA Manifest（参考 `references/qa-manifest-template.json`）：声明 `outline.md` 与 `transcript_full.md` 之间的覆盖率断言、关键金句存在性断言、时间戳合法性断言（`HH:MM:SS` 不超过音频总时长）。
- 调用 `user_skills/zero-trust-qa-checker` 的 `scripts/v3_engine.py` 做交叉比对。
- 输出 `qa_report.md`，列：
  - 大纲覆盖率（被遗漏的高价值主题清单）。
  - 抽样金句的物理回捞结果（原文存在 / 缺失）。
  - 时间戳异常列表。
- 若用户输入信息不足（如缺少音频时长、缺少视频 URL），必须返回 QA Manifest 并向用户索要补全，禁止猜测继续。

### Phase 5：终极落盘与归档 (SG Node Landing & Archive)

#### 5.1 飞书文档生成

调用 `scripts/render_lark.py` 把 outline + transcript 组装成 `<doc_basename>.lark.md`。若存在 `source_manifest.json`（例如 `minutes_transcript` 模式），必须通过 `--source-manifest` 传入，使最终文档头部写入 `minute_url / minute_token` 原始来源锚点。结构必须严格按以下"标准输出契约"：

```
# <文档主题标题>

## 📌 核心高光（100 字）
<100 字核心高光>

## 📚 全局大纲
<5-10 条 L1 方向条目>

## 🧭 多主题深度切片（L1-L4 + 秒级时间戳）
### L1：<方向 1>
- L2：<论点>
  - L3：<论据>
    - L4：<案例 / 金句> [HH:MM:SS]（或 `[<file> @ HH:MM:SS]`）
      > 原声金句：……
…
（其余 L1 主题同上）

## 🛡️ 零信任质检报告
<qa_report.md 摘录：覆盖率 / 抽样验证 / 缺失片段说明>

## 📖 高精逐字稿（附录，全量、不分页拆段）
<transcript_full.md 全文，保留 HH:MM:SS 时间戳>
```

随后调用本仓库的 `feishu-doc-writing-guide`：
- 用 `mcp_lark_create_lark_doc` 创建文档，必须显式 `target_type=personal`、传入文档标题（避免在标题里再写一次 H1，因为 mcp 工具会自动加）。
- 创建成功后，立刻执行写后即读：用 `mcp_lark_lark_download` 重新下载并核对关键段（100 字高光、L1 第一条、附录第一段）是否一致。

#### 5.2 SSOT 台账归档

通过 `user_skills/omni-asset-archiver` 调起：
- `asset_type = library_registry`（默认归档到【图书馆】）。
- DOC 编号通过 `omni-asset-archiver/scripts/global_id_allocator.py DOC` 申请（月维度 `DOC-YYMM-NNN`）。
- 写入字段：编号 / 名称（HYPERLINK 公式）/ 描述。
- 归档脚本内部已强制 RAW 写后回读，本步骤必须捕获其返回值并写入 conclude 报告。

## 输出契约（标准输出模板）

任何一次"演讲知识沉淀"任务的最终飞书文档必须严格满足：

> **100 字高光 + 全局大纲 + 多主题 L1-L4 + 秒级时间戳 + 空降链接 + 高精逐字稿附录**

缺任意一项即视为不合规，必须返工。

## Pre-flight Checklist（前置检查清单）

- [ ] 飞书写入必须经 `feishu-doc-writing-guide`，禁止直连 OpenAPI。
- [ ] 文档默认在 SG 节点 / 用户个人空间（`target_type=personal`）。
- [ ] 表格链接字段使用 `=HYPERLINK("<url>", "<text>")`。
- [ ] 新建文档 Owner = `yuqinan@bytedance.com`，并赋予 full access。
- [ ] 所有调用飞书凭证的脚本传 `include_secrets=true`。
- [ ] DOC 编号经 `omni-asset-archiver/scripts/global_id_allocator.py DOC` 申请。
- [ ] 失败片段以 `[GAP: ...]` 形式显式呈现，不静默丢弃。
- [ ] zero-trust-qa-checker 至少跑一轮（覆盖率 + 物理回捞）。

## 失败处理与重试策略

- **分段 ASR**：每段最多重试 `DEFAULT_MAX_RETRIES = 3` 次（指数退避 2 / 4 / 8 秒）。
- **数据完整性**：重试后仍失败的片段必须显式标记缺失范围（`[GAP: HH:MM:SS - HH:MM:SS] ASR 失败 ×3`），最终大纲在涉及该时间段的位置主动补一句"该段缺失，详见 GAP 列表"。
- **质检失败**：若 zero-trust-qa-checker 报告抽样金句缺失或大纲覆盖率过低，回到 Phase 2-3 修复后重跑，直到 PASSED。
- **写入失败**：若飞书创建 / 写台账失败，触发 omni-asset-archiver 的 DLQ 兜底（本地 JSONL）并向用户显式报错，禁止假装成功。

## 引用脚本（low 自由度护栏）

- `scripts/normalize_minutes_transcript.py`：把飞书妙记导出的 transcript 规范化为 `transcript_full.md`，生成 `source_manifest.json`，并对 `minute_token / minute_url / 时间戳` 做运行时熔断校验。
- `scripts/slice_audio.py`：基于 ffmpeg 把任意音频切成 ≤ 18 分钟片段，输出 `segments_manifest.json`。
- `scripts/transcribe_segments.py`：调用可配置的 analyze_audio 工具串行转写所有切片，自动重试，合并成全局时间戳逐字稿。执行前需由调用方把实际音频分析脚本路径注入环境变量 `AIME_ANALYZE_AUDIO_SCRIPT`。
- `scripts/build_outline.py`：基于完整逐字稿生成 100 字高光 + 全局大纲 + L1-L4 切片骨架（输出可被本技能进一步润色）。
- `scripts/render_lark.py`：把 outline + 逐字稿组装成 `.lark.md`，并校验"输出契约"完整性，缺项立刻 raise。

## 引用资源（references）

- `references/qa-manifest-template.json`：QA Manifest 模板，供 zero-trust-qa-checker 直接消费。
- `references/output-contract.md`：标准输出契约的字段级解释 + 反例库。

## 操作示例

Skill 资源位于 `user_skills/speech-knowledge-precipitation`，**文档中所有相对路径/命令均相对于此目录**。

```bash
# 0. 妙记 transcript 输入（v1.1 新增，跳过 ASR）
cd user_skills/speech-knowledge-precipitation \
  && python3 scripts/normalize_minutes_transcript.py \
       --input-source minutes_transcript \
       --transcript-path /tmp/skp_minutes/transcript.txt \
       --minute-token "obcxxx" \
       --minute-url "https://bytedance.feishu.cn/minutes/obcxxx" \
       --source-audio-name "meeting_audio.m4a" \
       --output /tmp/skp_minutes/transcript_full.md \
       --manifest-output /tmp/skp_minutes/source_manifest.json

# 1. 切片（仅 audio_or_video 默认路径使用）
cd user_skills/speech-knowledge-precipitation \
  && python3 scripts/slice_audio.py \
       --input "/abs/path/to/audio.wav" \
       --workdir /tmp/skp_audio_xxx \
       --segment-seconds 1080

# 2. 转写
python3 scripts/transcribe_segments.py \
  --manifest /tmp/skp_audio_xxx/segments_manifest.json \
  --output /tmp/skp_audio_xxx/transcript_full.md

# 3. 组装大纲与渲染 .lark.md（详见脚本 --help）
python3 scripts/build_outline.py --transcript /tmp/skp_audio_xxx/transcript_full.md --output /tmp/skp_audio_xxx/outline.md
python3 scripts/render_lark.py \
  --transcript /tmp/skp_audio_xxx/transcript_full.md \
  --outline /tmp/skp_audio_xxx/outline.md \
  --highlight /tmp/skp_audio_xxx/highlight.md \
  --qa-report /tmp/skp_audio_xxx/qa_report.md \
  --title "<文档主题标题>" \
  --audio-basename "audio.wav" \
  --source-manifest /tmp/skp_audio_xxx/source_manifest.json \
  --output /tmp/skp_audio_xxx/output.lark.md
```

最后通过 `feishu-doc-writing-guide` + `omni-asset-archiver` 完成落盘与归档（参见上文 Phase 5）。

## 变更记录 (Changelog)

- **v1.1 (2026-07-13)**：新增 `minutes_transcript` 一等输入源；新增 `scripts/normalize_minutes_transcript.py` 作为入口适配层，支持已有飞书妙记 transcript 时跳过 ASR 音频切片，直接进入逐字稿规范化、L1-L4 结构化提炼、零信任 QA 与飞书 Docx 归档；`render_lark.py` 新增 `--source-manifest`，在最终文档头部写入 `minute_url / minute_token` 原始来源锚点。
- **v1.0 (2026-04-20 / 2026-05-22 重锻)**：首次发布；定义五阶段 SOP，固化"100 字高光 + 全局大纲 + 多主题 L1-L4 + 秒级时间戳 + 空降链接 + 高精逐字稿附录"输出契约；接入 zero-trust-qa-checker、feishu-doc-writing-guide、omni-asset-archiver 三大网关。

