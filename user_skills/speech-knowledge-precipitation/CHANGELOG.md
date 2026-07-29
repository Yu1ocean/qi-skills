# Changelog

## v1.1 — 2026-07-13

- 新增 `minutes_transcript` 作为一等输入源：当已有飞书妙记转写文本时，跳过 ASR 音频切片，直接进入逐字稿规范化、L1-L4 结构化提炼、零信任 QA 与飞书 Docx 归档。
- 新增 `scripts/normalize_minutes_transcript.py`：读取妙记 transcript，校验 `minute_token / minute_url / source_audio_name / transcript_path`，规范化秒级时间戳，产出 `transcript_full.md` 与 `source_manifest.json`。
- 更新 `scripts/render_lark.py`：新增 `--source-manifest` 参数，支持在最终 `.lark.md` 头部写入 `minute_url / minute_token` 原始来源锚点。
- 保持向后兼容：默认 `audio_or_video` 路径仍沿用 v1.0 的切片 ASR 链路；只有显式 `input_source=minutes_transcript` 才进入新分支。

## v1.0 — 2026-04-20 / 2026-05-22

- 首次发布；定义五阶段 SOP，固化“100 字高光 + 全局大纲 + 多主题 L1-L4 + 秒级时间戳 + 空降链接 + 高精逐字稿附录”输出契约。
- 接入 `zero-trust-qa-checker`、`feishu-doc-writing-guide`、`omni-asset-archiver` 三大网关。
