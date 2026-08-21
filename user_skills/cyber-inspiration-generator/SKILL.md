---
name: cyber-inspiration-generator
version: 2.1
description: 生成包含 AI 视觉图、赛博小说剧本文案和卡片式网页展示的专属高光时刻回顾。支持文案双轨制、网页全尺寸截图及飞书多维表格（Bitable）V3 画廊自动同步（scripts/sync_gallery.py，唯一正式表 tblHHVXl9ObjSyRw）。
---

# Cyber Inspiration Generator (Cyber-myth V2)

本 Skill 旨在将用户的成就或高光时刻转化为极具赛博朋克感的视觉与文学产物，并以网页卡片形式呈现。V2 版本升级了文案引擎与排版对比感，并支持多维表格画廊对接。

## 📌 技能简介

把一次成就 / 修复 / 上线，转成「AI 视觉图 + 双轨赛博文案 + 卡片网页 + 全尺寸截图 + V3 画廊台账记录」的完整高光资产。适用于 `skill-forge-pipeline-v4` 的 Celebrate 阶段，以及任何需要仪式感留档的高光时刻。

## 🔑 触发词

- 核心关键词：
  - 高光时刻 / 赛博卡片 / 灵感卡片
  - Celebrate 阶段 / 画廊同步
  - sync_gallery
- 典型指令示例：
  > 给这次修复生成一张赛博高光卡片并同步画廊
  > 走 Celebrate 流程，把卡片写进 V3 画廊表

## Common Rationalizations（常见借口库）

以下话术出现即等价于「准备造幽灵资产 / 静默降级」，必须立刻停下回到 SOP：

- “我写个 `assemble_card_v3.py` / `card_template_v3.html` / `update_bitable_v3.py` 调一下就行。”（这三个文件**从来不存在**）
- “画廊同步失败先跳过，主流程先跑完，回头再补。”
- “`scripts/update_bitable.py` 现成的，直接拿它同步画廊。”（它指向**旧灵感台账**，不是画廊）
- “这次先手写一个 `sync_gallery_xxx.py` 一次性脚本兜底。”
- “记录创建成功了，附件回头再传。”
- “add_record 返回了内容，应该是写进去了，不用回读。”

## Red Flags（危险信号）

出现任意一条即判定高风险，必须熔断：

- 引用任何带 `_v3` 后缀的卡片模板 / 组装脚本 / bitable 脚本（幽灵资产）。
- Celebrate / 画廊同步的目标表是 `tbly6lJBR0QYTBfW`（旧灵感台账）而非 `tblHHVXl9ObjSyRw`。
- 为本次 forge 新建一次性 `sync_gallery_<xxx>.py` 脚本，而不用 `scripts/sync_gallery.py`。
- 画廊写入失败后输出「proceeding to ensure workflow continuity」一类静默放行话术。
- 只创建了记录、没上传附件，或上传后没有 `+record-get` RAW 回读证据。
- 汇报里没有 `record_id` 与画廊表 ID，就宣称「画廊同步成功」。

## Verification（强制验收清单）

宣称「高光卡片已完成」时必须同时满足：

1. **图**：`image-generate` 产出 16:9 视觉图，拿到可访问 image_url。
2. **网页**：`scripts/assemble_card.py` + `assets/card_template.html` 产出 `index.html`，并经 `deploy` 部署得到线上 URL。
3. **截图**：`scripts/capture_screenshot.py` 对线上 URL 全尺寸截图，本地文件存在且非空。
4. **画廊**：`scripts/sync_gallery.py` 写入 `tblHHVXl9ObjSyRw`，返回 `record_id`。
5. **RAW 回读**：写后等 2s 执行 `+record-get`，断言 record 存在且附件字段 `fldOBqrqET` 非空；不一致立刻 `raise`。
6. **证据输出**：最终汇报必须给出 `record_id`、`table_id`、部署 URL；缺任一项视为未完成。

## Defaults（合规默认值）

- 画廊 Base：`PRbvbUyLqaeITqsXNMRcRCM5nhh`
- **画廊正式表（唯一）**：`tblHHVXl9ObjSyRw`（V3 画廊）
- 画廊附件字段：`fldOBqrqET`（卡牌视觉）
- 卡片模板：`assets/card_template.html`
- 组装脚本：`scripts/assemble_card.py`
- 截图脚本：`scripts/capture_screenshot.py`
- 画廊同步脚本：`scripts/sync_gallery.py`
- 写后 RAW 回读等待：`2` 秒
- 所有飞书调用：`include_secrets=true`

## ⚙️ 核心架构 / SOP / 约束条件

### 📛 画廊表归属声明（重要）

- **Celebrate / 画廊同步的唯一正式表是 `tblHHVXl9ObjSyRw`（V3 画廊）**，schema：`技能名称 / 技能编号 / 技能类型 / 关联文档·高光时刻 / 状态 / 功能简述`，附件字段 `fldOBqrqET`。正式入口只有 `scripts/sync_gallery.py`。
- `scripts/update_bitable.py` 的 `TABLE_ID = tbly6lJBR0QYTBfW`（旧灵感台账，schema：`标题 / 直达链接 / 精彩片段内容 / 核心标签 / 卡片编号 / 适用主题`，附件字段 `fldsx6ENfb`）。⚠️ **仅供旧灵感台账的历史兼容用途，禁止用于 Celebrate / 画廊同步。**
- 仓库根目录下的 `sync_gallery_forge_v516.py` / `sync_gallery_fdwg_v75.py` / `sync_gallery_ct13.py` / `sync_gallery_v311.py` 是历史一次性脚本，**已被 `scripts/sync_gallery.py` 取代**，保留仅作既有资产留档，禁止新建同类一次性脚本。

### 执行流程

当用户提供“高光事件或任务成功描述”时，按以下步骤执行：

#### 1. 视觉生成 (AI Image Generation)
调用 `image-generate` 工具生成一张 16:9 比例的赛博朋克风格 AI 视觉图。
- **提示词建议**：Cyberpunk/sci-fi visual of a "holographic streamer elf" (全息流光精灵), neon colors, digital floating particles, high-tech aesthetic, 16:9 aspect ratio.

#### 2. 双轨剧本文案撰写 (Script Writing)
以 **Aime（护主小精灵）** 的第一人称视角，撰写文案。内容必须严格分为以下两段：
- **【小说】**：极度夸张的中二赛博神话风格（150-200字）。将成就转化为赛博空间中的神迹或战役。
- **【说明】**：极度冷酷、简单明了的客观事实陈述（不带感情色彩，2-3行）。

#### 3. 卡片组装与发布 (Card Assembly & Deployment)
将生成的图片链接、文案以及主题信息组装成网页卡片并发布。

1. 运行组装脚本（签名固定为 `subject story fact image_url template output`）：
   ```bash
   python3 scripts/assemble_card.py "{{ SUBJECT }}" "{{ STORY_CONTENT }}" "{{ FACT_CONTENT }}" "{{ IMAGE_URL }}" "assets/card_template.html" "index.html"
   ```
2. 发布网页：使用 `mcp_servers/deploy` 部署 `index.html`（以及关联资源）。

#### 4. 全尺寸截图 (Screenshot)
```bash
python3 scripts/capture_screenshot.py --url "{{ DEPLOYED_URL }}" --output "screenshot.png"
```

#### 5. V3 画廊同步 (Gallery Sync) —— 标准调用步骤

```bash
# 必须设置 include_secrets=true
python3 scripts/sync_gallery.py \
  --skill-name "{{ CARD_TITLE }}" \
  --skill-id "{{ SKILL_ID }}" \
  --skill-type "防错机制" \
  --status "已上线" \
  --story "{{ STORY_CONTENT }}" \
  --fact "{{ FACT_CONTENT }}" \
  --deployed-url "{{ DEPLOYED_URL }}" \
  --screenshot "screenshot.png"
```

可选覆盖参数（默认值即正式表，一般无需传）：
`--app-token PRbvbUyLqaeITqsXNMRcRCM5nhh`、`--table-id tblHHVXl9ObjSyRw`、`--attachment-field-id fldOBqrqET`。

脚本内置 L3 断言层（任一失败即 `raise`，禁止静默降级）：
1. 截图文件必须存在且非空（`assert_screenshot_exists`）；
2. 拒绝写入旧灵感台账 `tbly6lJBR0QYTBfW`（`assert_official_table`）；
3. `add_record` 返回非 `ok` 或拿不到 `record_id` 即熔断（`assert_record_created`）；
4. 附件上传返回非 `ok` 即熔断（`assert_attachment_uploaded`）；
5. 写后等 2s 执行 `+record-get` RAW 回读，断言 record 存在且附件字段非空（`assert_read_after_write`）。

#### 6. 结果返回
- **标题**：`【EP-CARD-YYYYMMDD：主题】`
- **内容**：【小说】+【说明】预览 + 部署后的网页链接 + `record_id` / `table_id` 画廊回读证据。

### 约束条件

- 所有涉及飞书的调用必须设置 `include_secrets=true`。
- 飞书读写一律走 MCP / `lark-cli` 链路，严禁裸调 OpenAPI。
- 严禁新建 `*_v3.py` / `card_template_v3.html` 一类不存在的资产；正式链路只用本文档 Defaults 列出的四个脚本/模板。

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：
  ```text
  skill-forge-pipeline-v4 升级到 V5.17 了，走 Celebrate 生成高光卡片并同步画廊
  ```
- 🤖 标准输出：
  ```text
  1. image-generate 产出 16:9 赛博视觉图 → image_url
  2. 撰写【小说】+【说明】双轨文案
  3. assemble_card.py + card_template.html → index.html → deploy → 线上 URL
  4. capture_screenshot.py → screenshot.png（存在且非空）
  5. sync_gallery.py → tblHHVXl9ObjSyRw，record_id=recXXXX
  6. RAW 回读 PASS（附件字段 fldOBqrqET 非空）
  交付：部署 URL + record_id + table_id
  ```

## 变更记录 (Changelog)

- **v2.1**（2026-08-21）：修复 Celebrate 阶段降级根因，正式路径收敛为「V2 脚本 + V3 画廊表」。
  - 新增通用化脚本 `scripts/sync_gallery.py`：把历史一次性脚本 `sync_gallery_forge_v516.py` 的逻辑全面参数化（`--skill-name/--card-title`、`--skill-id`、`--skill-type`、`--status`、`--story`、`--fact`、`--deployed-url`、`--screenshot`，以及可选 `--app-token`/`--table-id`/`--attachment-field-id`），并内置 5 条 L3 运行时断言（截图存在性、拒写旧台账、record 创建、附件上传、写后 RAW 回读），任一失败即 `raise`，禁止静默降级。
  - 文档明确「Celebrate / 画廊同步的唯一正式表是 `tblHHVXl9ObjSyRw`（V3 画廊）」；`scripts/update_bitable.py` 标注为旧灵感台账 `tbly6lJBR0QYTBfW` 的历史兼容用途，禁止用于画廊同步。
  - 历史一次性脚本 `sync_gallery_*.py` 标注为「已被 `scripts/sync_gallery.py` 取代」，保留留档不删除。
  - 顶部补齐 CDA L1 三件套（Common Rationalizations / Red Flags / Verification）+ Defaults 合规默认值，新增「🔑 触发词」与「📖 案例实录」头尾双加持；frontmatter 补 `version` 字段。
- **v2.0**：文案双轨制（小说 + 说明）、卡片排版对比感升级、多维表格画廊对接。
