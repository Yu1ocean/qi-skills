---
name: skill-heatmap-generator
description: 扫描 `.aime/log/subagent` 的 legacy slug 日志窗口，按旧版 heat_probe v1 兼容口径统计 Aime 技能库中 16 个已登记技能的近30天/当前巡检窗口使用次数，并通过飞书 MCP 路径把结果写回 Skill Registry 表格，适用于技能热度巡检、热度榜对齐、Wiki 台账补数与 RAW 回读验收场景。
---

# skill-heatmap-generator

将旧版 `heat_probe.py` 的启发式 slug 匹配逻辑固化为可复用本地技能：

1. 扫描 `.aime/log/subagent`
2. 仅统计【Aime 技能库】当前已登记的 16 个技能
3. 默认把计数写回 Skill Registry 表格最右侧“近30天使用次数”列
4. 写后重新下载目标文档做 RAW 回读验收

**默认目标文档：** `https://bytedance.larkoffice.com/docx/AKmddboNJos7RcxGiOlcoWCvnjd`

**当前版本：** `1.5`

version: 1.5
## 🔑 触发词

- 核心关键词：
  - 技能热度榜
  - 热度探针
  - heat_probe
  - Skill Registry 补数
  - 近30天使用次数
  - skill-heatmap-generator
- 典型指令示例：
  > 立刻刷新 Aime 技能库里 16 个技能的近30天使用次数
  > 跑一次 skill-heatmap-generator，把热度数据写回 Wiki 表格

## 何时使用

在以下场景使用本技能：

- 需要按旧版 `heat_probe v1` 兼容口径统计技能热度
- 需要把 16 个已登记技能的热度数字回写到 Wiki / 飞书文档
- 需要验证当前 Skill Registry 表格里的“近30天使用次数”列是否已落盘
- 需要给后续主流程提供本地已验证的 `heatmap_counts.json` 与 `leaderboard.txt`

## 口径说明（v1 兼容）

本技能**默认保持旧版 v1 口径**，不要擅自切换到 trace 正文解析或其他新口径：

- **只用目录名 slug 做启发式匹配**，不读取 `trace.jsonl` 正文做新统计
- **只统计 16 个已登记技能**，不写回 `product-copywriting`、`live-performance-summary-generator`、本技能自身
- 若 workspace 中存在已发布的本地热度榜文件（如 `AIME_武器热度榜_v1.0_·_Weapon_Heat_Index.lark.md`），则默认读取其中的“探针时间”作为 **v1 锚点时间**，只统计该锚点之前的 `.aime/log/subagent` 目录，从而与现有热度榜保持一致
- 若找不到本地热度榜锚点文件，则退回到当前 `.aime/log/subagent` 保留窗口

## 输入

无需额外输入即可运行，默认使用：

- 日志目录：`.aime/log/subagent`
- 目标文档：`https://bytedance.larkoffice.com/docx/AKmddboNJos7RcxGiOlcoWCvnjd`
- 统计对象：Skill Registry 当前 16 个技能
- 写回方式：`inner_skills/lark_download/lark_download.py` + `lark-cli docs +update`

## 输出

运行后至少生成以下文件：

- `output/heatmap_counts.json`：计数结果、窗口信息、兼容性校验、Wiki 写回与 RAW 回读结果
- `output/leaderboard.txt`：按计数降序排列的纯文本榜单
- `output/wiki_before.lark.md`：写回前下载副本
- `output/wiki_after.lark.md`：写后回读副本

## 执行命令

在技能根目录执行：

```bash
cd user_skills/skill-heatmap-generator && python3 scripts/generate_skill_heatmap.py
```

**⚠️ 强制要求：** 必须通过 `bash` 工具直接执行，并设置 `include_secrets=true`，严禁通过其他脚本间接调用或在无密钥环境下执行。因为脚本内部会通过 subprocess 调用飞书 MCP 包装器，若没有 secrets，Wiki 下载 / 写回 / 回读都会失败。

推荐执行方式：

```bash
cd /workspace/iris_19f7e856-22a9-491e-b611-5e5c09e9e419/user_skills/skill-heatmap-generator && python3 scripts/generate_skill_heatmap.py
```

## 执行流程

按以下顺序执行：

1. 识别本地热度榜锚点文件，尽量保持 v1 兼容窗口
2. 扫描 `.aime/log/subagent` 目录名
3. 依据 legacy alias map 统计 16 个技能的调用次数
4. 生成 `output/leaderboard.txt`
5. 下载目标 Wiki 文档
6. 找到 `## 一、技能存量清单 (Skill Registry)` 对应的表格 block
7. 用统计结果替换最右侧“近30天使用次数”列
8. 通过飞书 MCP update 写回文档
9. 再次下载目标文档做 RAW 回读，确认 16 行最后一列已出现对应数字
10. 生成 `output/heatmap_counts.json`

## Common Rationalizations（常见借口）

出现以下想法时，视为准备偏离本技能目标，必须立刻回到 SOP：

- “既然 trace.jsonl 现在能读，就顺手切到更严格的新口径吧。”
- “表格先不写回，先出个 json 交差。”
- “直接走 OpenAPI 改一列更快，没必要经过 MCP。”
- “16 个技能太麻烦了，顺便把 `product-copywriting` 和 `live-performance-summary-generator` 也写进去。”
- “写回后不用回读了，返回成功就算成功。”
- “本地已有旧下载文件，直接拿它当写后证据就行。”
- “为了避免锚点时间影响，直接扫全部目录吧。”

## Red Flags（危险信号）

出现任意一条，都必须视为失败或高风险状态：

- 输出计数与当前 v1 热度榜核心数字明显不一致，却没有给出窗口解释
- 统计范围包含了 16 个登记技能之外的技能
- 写回不是通过 `lark_download.py` / `lark-cli docs +update` 完成
- toolset 漂移导致 MCP 路径断裂，修复策略：下载走 lark_download，写回走 lark-cli docs +update
- 目标表格不是 `## 一、技能存量清单 (Skill Registry)` 下方那张表
- 只更新了部分技能行，或者表格末列仍为空
- 没有二次下载目标文档做 RAW 回读
- `output/heatmap_counts.json` 中缺少 `wiki_update.readback.success`

## Verification（强制验收）

宣称“技能已跑通”前，必须同时满足：

1. `scripts/generate_skill_heatmap.py` 已实际执行至少一次
2. `output/leaderboard.txt` 已生成，且包含 16 个技能的排序结果
3. `output/heatmap_counts.json` 已生成，且包含：
   - `window.mode`
   - `counts`
   - `compatibility_check`
   - `wiki_update.before_values`
   - `wiki_update.after_values`
   - `wiki_update.readback.success`
4. 目标文档 Skill Registry 表格 16 行最后一列均已被写入数字
5. RAW 回读已成功，且能明确指出至少若干行的最终数值
6. v1 兼容校验中，核心数字应与既有热度榜一致：
   - `info-miner=41`
   - `zero-trust-qa-checker=38`
   - `periodic-report-generator=37`
   - `omni-asset-archiver=31`
   - `skill-forge-pipeline-v4=19`
   - `smart-scheduler=18`
   - `heartbeat-inspector=11`
   - `task-flow-engine=11`
   - `agatha-ai-novelist=8`
   - `feishu-doc-writing-guide=8`
   - `cyber-inspiration-generator=6`
   - `merchant-tier-analyzer=5`
   - `pro-task-planner=2`
   - `internet-insight-analyzer=0`
   - `v6-panoramic-chart-generator=0`
   - `zero-trust-data-analyzer=0`

## 失败时的处理方式

- 统计失败：保留 `output/leaderboard.txt` 与 `output/heatmap_counts.json` 中的错误上下文，停止后续写回
- Wiki 写回失败：直接报错，不得声称“只是没回写成功但统计已完成”
- RAW 回读失败：直接视为失败，不得把 update 接口返回成功当作最终成功

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：
  ```text
  立刻刷新 Aime 技能库里 16 个技能的近30天使用次数，并把结果写回 Wiki 表格。
  ```
- 🤖 标准输出：
  ```text
  1. 扫描 .aime/log/subagent 的 legacy slug 窗口。
  2. 仅统计 Skill Registry 已登记的 16 个技能。
  3. 生成 output/leaderboard.txt 与 output/heatmap_counts.json。
  4. 通过飞书 MCP 写回“近30天使用次数”列。
  5. 再次下载 Wiki 文档做 RAW 回读，确认 16 行末列已成功落盘。
  ```

## 资源

- 主脚本：`scripts/generate_skill_heatmap.py`
- 输出目录：`output/`
