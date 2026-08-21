# 【技能说明】赛博灵感卡片生成器 (cyber-inspiration-generator) v2.1

<figure view-type="Card"><source name="cyber-inspiration-generator.zip" href="https://api3-eeft-drive.feishu.cn/space/api/box/stream/download/authcode/?code=N2ZkMmI0OTEwNDhmNDBlMDRmZjdkMDY3NTc2MGZlMjFfODdkNzdkZWIwZDAwMTVhMGE0ZDVkZWFhOTY1MGQxYzdfSUQ6NzY3NjQ1MzUzMTcxMjI2MTc1Ml8xNzg3MzEzNjQzOjE3ODczMTcyNDNfVjM" mime="application/zip" size="29374829" token="PeWdbCBHloXZSaxzEKZmoESCyxg"/></figure>

## 📌 技能简介

`cyber-inspiration-generator` 把一次成就 / 修复 / 上线，转成「AI 视觉图 + 双轨赛博文案 + 卡片网页 + 全尺寸截图 + V3 画廊台账记录」的完整高光资产。它是 `skill-forge-pipeline-v4`**Celebrate 阶段**的执行引擎，也可独立用于任何需要仪式感留档的高光时刻。

- **解决什么问题**：让「技能上线 / 故障修复 / 里程碑达成」不再只是一句口头汇报，而是可归档、可回看、可检索的视觉资产。
- **适用谁**：Aime 技能锻造流水线、需要沉淀高光时刻的个人与团队。
- **带来什么收益**：一条命令闭环 图→文→网页→截图→台账，并带 L3 运行时断言，杜绝「同步失败却静默放行」。

## 🔑 触发词

- 核心关键词：

  - 高光时刻 / 赛博卡片 / 灵感卡片
  - Celebrate 阶段 / 画廊同步
  - sync_gallery
- 典型指令示例：

  > 给这次修复生成一张赛博高光卡片并同步画廊  
  > 走 Celebrate 流程，把卡片写进 V3 画廊表

## ⚙️ 核心架构 / SOP / 约束条件

### 画廊表归属声明（唯一正式表）

| 用途 | Base | Table | 附件字段 | 状态 |
|-|-|-|-|-|
| **Celebrate / 画廊同步（唯一正式）** | `PRbvbUyLqaeITqsXNMRcRCM5nhh` | `tblHHVXl9ObjSyRw` | `fldOBqrqET` | ✅ 正式 |
| 旧灵感台账（历史兼容） | `PRbvbUyLqaeITqsXNMRcRCM5nhh` | `tbly6lJBR0QYTBfW` | `fldsx6ENfb` | ⚠️ 仅历史兼容，禁止用于 Celebrate |

- V3 画廊 schema：`技能名称 / 技能编号 / 技能类型 / 关联文档·高光时刻 / 状态 / 功能简述`。
- `scripts/update_bitable.py` 指向旧灵感台账，**仅作历史兼容**，禁止用于 Celebrate / 画廊同步。
- 仓库根目录的 `sync_gallery_forge_v516.py` / `sync_gallery_fdwg_v75.py` / `sync_gallery_ct13.py` / `sync_gallery_v311.py` 为历史一次性脚本，**已被 `scripts/sync_gallery.py` 取代**，保留仅作既有资产留档，禁止新建同类一次性脚本。

### 五步 SOP

1. **视觉生成**：调用 `image-generate` 生成 16:9 赛博朋克风视觉图。

   - 提示词建议：Cyberpunk/sci-fi visual of a "holographic streamer elf"（全息流光精灵），neon colors、digital floating particles、high-tech aesthetic、16:9。
2. **双轨剧本文案**：以 Aime（护主小精灵）第一人称撰写，严格分两段。

   - 【小说】极度夸张的中二赛博神话风格（150-200 字），把成就转化为赛博空间中的神迹或战役。
   - 【说明】极度冷酷、简单明了的客观事实陈述（2-3 行，不带感情色彩）。
3. **卡片组装与发布**：

   ```bash
   python3 scripts/assemble_card.py "{{ SUBJECT }}" "{{ STORY_CONTENT }}" "{{ FACT_CONTENT }}" "{{ IMAGE_URL }}" "assets/card_template.html" "index.html"
   ```
4. **全尺寸截图**：

   ```bash
   python3 scripts/capture_screenshot.py --url "{{ DEPLOYED_URL }}" --output "screenshot.png"
   ```
5. **V3 画廊同步（标准调用步骤）**：

   ```bash
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

### L3 断言层（任一失败即 raise，禁止静默降级）

1. `assert_screenshot_exists`：截图文件必须存在且非空。
2. `assert_official_table`：拒绝写入旧灵感台账 `tbly6lJBR0QYTBfW`。
3. `assert_record_created`：`add_record` 返回非 `ok` 或拿不到 `record_id` 即熔断。
4. `assert_attachment_uploaded`：附件上传返回非 `ok` 即熔断。
5. `assert_read_after_write`：写后等 2s 执行 `+record-get` RAW 回读，断言 record 存在且附件字段非空。

### 反合理化护栏（CDA L1）

- **Common Rationalizations**：「写个 `assemble_card_v3.py` / `update_bitable_v3.py` 调一下就行」「画廊同步失败先跳过」「拿 `update_bitable.py` 直接同步画廊」「先手写一个一次性 `sync_gallery_xxx.py` 兜底」「record 建好了附件回头再传」。
- **Red Flags**：引用任何 `_v3` 后缀幽灵资产；画廊落到 `tbly6lJBR0QYTBfW`；新建一次性 `sync_gallery_*.py`；输出「proceeding to ensure workflow continuity」静默放行；没有 `+record-get` RAW 回读证据。
- **Verification**：图 → 网页（部署 URL）→ 截图（存在且非空）→ 画廊 `record_id` → RAW 回读附件非空 → 汇报输出 `record_id` + `table_id` + 部署 URL。

### 约束条件

- 所有涉及飞书的调用必须设置 `include_secrets=true`。
- 飞书读写一律走 MCP / `lark-cli` 链路，严禁裸调 OpenAPI。
- 严禁新建 `*_v3.py` / `card_template_v3.html` 一类不存在的资产。

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：

  ```text
  skill-forge-pipeline-v4 升级到 V5.17 了，走 Celebrate 生成高光卡片并同步画廊
  ```
- 🤖 标准输出：

  ```text
  1. image-generate 产出 16:9 赛博视觉图 → hero.jpg
  2. 撰写【小说】+【说明】双轨文案
  3. assemble_card.py + card_template.html → index.html → deploy → 线上 URL
  4. capture_screenshot.py → screenshot.png（存在且非空）
  5. sync_gallery.py → tblHHVXl9ObjSyRw，record_id=recvsVPmaEJtUJ
  6. RAW 回读 PASS（附件字段 fldOBqrqET 非空，file_token=DftVbQU9woyxtZxvtWDcYnRUnuf）
  交付：部署 URL + record_id + table_id
  ```

## 变更记录 (Changelog)

- **v2.1**（2026-08-21）：修复 Celebrate 阶段降级根因，正式路径收敛为「V2 脚本 + V3 画廊表」。

  - 新增通用化脚本 `scripts/sync_gallery.py`：把历史一次性脚本 `sync_gallery_forge_v516.py` 的逻辑全面参数化，并内置 5 条 L3 运行时断言，任一失败即 `raise`，禁止静默降级。
  - 文档明确「Celebrate / 画廊同步的唯一正式表是 `tblHHVXl9ObjSyRw`」；`scripts/update_bitable.py` 标注为旧灵感台账 `tbly6lJBR0QYTBfW` 的历史兼容用途。
  - 历史一次性 `sync_gallery_*.py` 标注为已被取代，保留留档不删除。
  - 顶部补齐 CDA L1 三件套 + Defaults 合规默认值，新增「🔑 触发词」与「📖 案例实录」头尾双加持；frontmatter 补 `version` 字段。
- **v2.0**：文案双轨制（小说 + 说明）、卡片排版对比感升级、多维表格画廊对接。