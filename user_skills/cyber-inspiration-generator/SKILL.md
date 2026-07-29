---
name: cyber-inspiration-generator
description: 生成包含 AI 视觉图、赛博小说剧本文案和卡片式网页展示的专属高光时刻回顾。支持文案双轨制、网页全尺寸截图及飞书多维表格（Bitable）画廊自动同步。
---

# Cyber Inspiration Generator (Cyber-myth V2)

本 Skill 旨在将用户的成就或高光时刻转化为极具赛博朋克感的视觉与文学产物，并以网页卡片形式呈现。V2 版本升级了文案引擎与排版对比感，并支持多维表格画廊对接。

## 执行流程

当用户提供“高光事件或任务成功描述”时，按以下步骤执行：

### 1. 视觉生成 (AI Image Generation)
调用 `image-generate` 工具生成一张 16:9 比例的赛博朋克风格 AI 视觉图。
- **提示词建议**：Cyberpunk/sci-fi visual of a "holographic streamer elf" (全息流光精灵), neon colors, digital floating particles, high-tech aesthetic, 16:9 aspect ratio.

### 2. 双轨剧本文案撰写 (Script Writing)
以 **Aime（护主小精灵）** 的第一人称视角，撰写文案。内容必须严格分为以下两段：
- **【小说】**：极度夸张的中二赛博神话风格（150-200字）。将成就转化为赛博空间中的神迹或战役。
- **【说明】**：极度冷酷、简单明了的客观事实陈述（不带感情色彩，2-3行）。

### 3. 卡片组装与发布 (Card Assembly & Deployment)
将生成的图片链接、文案以及主题信息组装成网页卡片并发布。

**操作步骤：**
1. 运行组装脚本：
   ```bash
   python3 scripts/assemble_card.py "{{ SUBJECT }}" "{{ STORY_CONTENT }}" "{{ FACT_CONTENT }}" "{{ IMAGE_URL }}" "assets/card_template.html" "index.html"
   ```
2. 发布网页：
   使用 `mcp_servers/deploy` 部署 `index.html`（以及关联资源）。

### 4. 自动化截图与台账同步 (Automation & Bitable)
网页部署后，执行以下自动化操作：
1. **全尺寸截图**：
   使用 playwright 对部署后的 URL 进行全尺寸截图：
   ```bash
   python3 scripts/capture_screenshot.py --url "{{ DEPLOYED_URL }}" --output "screenshot.png"
   ```
2. **多维表格同步**：
   将截图、URL 及文案同步至【灵感台账】（Bitable）：
   ```bash
   # 必须设置 include_secrets=true
   python3 scripts/update_bitable.py "{{ SUBJECT }}" "{{ STORY_CONTENT }}" "{{ FACT_CONTENT }}" "{{ IMAGE_URL }}" "screenshot.png" "{{ DEPLOYED_URL }}"
   ```

### 5. 结果返回
返回以下格式的响应：
- **标题**：`【EP-CARD-YYYYMMDD：主题】`
- **内容**：【小说】+【说明】预览 + 部署后的网页链接 + Bitable 记录同步成功的状态确认。

## 示例参考

**输入**：成功修复了核心网关的流量风暴问题。
**输出预览**：
> 【EP-CARD-20260408：静默协议：网关平息】
>
> **【小说】**：吾主，在 0x3F 时刻，混沌的流量风暴正试图撕裂我们的边缘网关……但您的意志如冷冽的编译器，精准地重构了受损的代码。
> 
> **【说明】**：2026-04-08 20:00，核心网关异常流量峰值回落至正常区间，受损路由表已重置。
> 
> 全息记录：https://xxx.aime-app.bytedance.net/
