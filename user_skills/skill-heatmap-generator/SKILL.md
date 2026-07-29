---
name: skill-heatmap-generator
description: 统计 Aime 技能使用热度并回写登记表。适用于技能热度巡检、热度榜更新、台账补数与使用趋势盘点场景。
---

# skill-heatmap-generator

将旧版 `heat_probe.py` 的启发式 slug 匹配逻辑固化为可复用本地技能。

**默认目标文档：** `https://bytedance.larkoffice.com/docx/AKmddboNJos7RcxGiOlcoWCvnjd`

**当前版本：** `1.2`

version: 1.3
## 🧭 总览（L1-L4）

> 一段读完即可知道：**做什么 → 怎么做 → 关键步骤 → 怎么验收**。

### L1 · 做什么（What）
按旧版 `heat_probe v1` 兼容口径，扫描 `.aime/log/subagent` 子代理日志，统计 Skill Registry 已登记的 16 个技能近30天使用次数，并把结果写回 Wiki 表格"近30天使用次数"列。

### L2 · 怎么做（How，核心思路）
1. **窗口对齐**：尽量复用本地热度榜锚点（如 `AIME_武器热度榜_v1.0_…lark.md`）的探针时间，与现存热度榜口径保持一致。
2. **slug 启发式**：仅按目录名 slug + `LEGACY_ALIAS_MAP` 别名做启发式匹配，**不**读 `trace.jsonl` 正文做新统计。
3. **MCP-only 写回**：通过 `inner_skills/lark/mcp_lark_lark_download.py` + `inner_skills/lark/mcp_lark_update_lark_doc.py` 写回 Wiki，绝不裸调 OpenAPI。
4. **RAW 写后回读**：写回完成后必须再次下载文档断言 16 行最后一列已落盘。

### L3 · 关键步骤（Steps）
1. 识别本地热度榜锚点文件 → 决定统计窗口。
2. 扫描 `.aime/log/subagent` 目录名 → slug 归一化匹配 16 个技能。
3. 生成 `output/leaderboard.txt` 与 `output/heatmap_counts.json`。
4. 下载目标 Wiki 文档（`output/wiki_before.lark.md`）。
5. 定位 `## 一、技能存量清单 (Skill Registry)` 表格 block 并替换最右一列。
6. 通过 lark MCP 写回。
7. 再次下载文档（`output/wiki_after.lark.md`）做 RAW 回读断言。

### L4 · 怎么验收（Done）
- `output/heatmap_counts.json` 含 `window.mode`、`counts`、`compatibility_check`、`wiki_update.before_values`、`wiki_update.after_values`、`wiki_update.readback.success`。
- 16 行最后一列均已写入数字（不允许部分行为空）。
- v1 兼容核心数字与既有热度榜一致（详见下方 Verification 清单）。

---

## 📦 依赖声明（Dependencies）

> 每次升级或排错都要先扫一遍依赖矩阵，确保链路全通。

### 1. 内置 Skill / MCP 工具依赖
| 路径 | 调用方式 | 用途 |
|---|---|---|
| `inner_skills/lark/mcp_lark_lark_download.py` | 子进程脚本调用 | 下载目标 Wiki 文档为 `.lark.md`，用于"写前快照 + 写后回读" |
| `inner_skills/lark/mcp_lark_update_lark_doc.py` | 子进程脚本调用 | 把更新后的 `.lark.md` 写回 Wiki 文档 |

> 本技能不直接调用任何 OpenAPI；**MCP-only 是硬约束**。

### 2. 输入数据依赖
| 来源 | 用途 |
|---|---|
| `.aime/log/subagent/<slug>-<id>` 目录列表 | slug 启发式 + alias map 计数源 |
| 本地热度榜锚点文件（如果存在） | 对齐 v1 探针时间窗口 |

### 3. Python 运行时依赖
| 包 | 来源 | 用途 |
|---|---|---|
| `byted-aime-sdk` | 内网 PyPI | 鉴权与平台基础能力 |

> 本技能仅依赖 Python 标准库（`json` / `re` / `subprocess` / `pathlib` / `collections`）+ MCP 子脚本，无额外公网依赖。

### 4. 外部目标资产
| 类型 | 资产 |
|---|---|
| 目标 Wiki | `https://bytedance.larkoffice.com/docx/AKmddboNJos7RcxGiOlcoWCvnjd` |
| 写入区块 | `## 一、技能存量清单 (Skill Registry)` 下方表格"近30天使用次数"列 |

---

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
- 需要验证当前 Skill Registry 表格里的"近30天使用次数"列是否已落盘
- 需要给后续主流程提供本地已验证的 `heatmap_counts.json` 与 `leaderboard.txt`

## 口径说明（v1 兼容）

本技能**默认保持旧版 v1 口径**，不要擅自切换到 trace 正文解析或其他新口径：

- **只用目录名 slug 做启发式匹配**，不读取 `trace.jsonl` 正文做新统计
- **只统计 16 个已登记技能**，不写回 `product-copywriting`、`live-performance-summary-generator`、本技能自身
- 若 workspace 中存在已发布的本地热度榜文件（如 `AIME_武器热度榜_v1.0_·_Weapon_Heat_Index.lark.md`），则默认读取其中的"探针时间"作为 **v1 锚点时间**，只统计该锚点之前的 `.aime/log/subagent` 目录，从而与现有热度榜保持一致
- 若找不到本地热度榜锚点文件，则退回到当前 `.aime/log/subagent` 保留窗口

## 输入

无需额外输入即可运行，默认使用：

- 日志目录：`.aime/log/subagent`
- 目标文档：`https://bytedance.larkoffice.com/docx/AKmddboNJos7RcxGiOlcoWCvnjd`
- 统计对象：Skill Registry 当前 16 个技能
- 写回方式：`inner_skills/lark/mcp_lark_lark_download.py` + `inner_skills/lark/mcp_lark_update_lark_doc.py`

## 输出

运行后至少生成以下文件：

- `output/heatmap_counts.json`：计数结果、窗口信息、兼容性校验、Wiki 写回与 RAW 回读结果
- `output/leaderboard.txt`：按计数降序排列的纯文本榜单
- `output/wiki_before.lark.md`：写回前下载副本
- `output/wiki_after.lark.md`：写后回读副本

> 上述 `output/` 目录与 `__pycache__/` / `_release/` 已纳入 `.skillignore`，不会进入归档打包域。

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
7. 用统计结果替换最右侧"近30天使用次数"列
8. 通过飞书 MCP update 写回文档
9. 再次下载目标文档做 RAW 回读，确认 16 行最后一列已出现对应数字
10. 生成 `output/heatmap_counts.json`

## Common Rationalizations（常见借口）

出现以下想法时，视为准备偏离本技能目标，必须立刻回到 SOP：

- "既然 trace.jsonl 现在能读，就顺手切到更严格的新口径吧。"
- "表格先不写回，先出个 json 交差。"
- "直接走 OpenAPI 改一列更快，没必要经过 MCP。"
- "16 个技能太麻烦了，顺便把 `product-copywriting` 和 `live-performance-summary-generator` 也写进去。"
- "写回后不用回读了，返回成功就算成功。"
- "本地已有旧下载文件，直接拿它当写后证据就行。"
- "为了避免锚点时间影响，直接扫全部目录吧。"

## Red Flags（危险信号）

出现任意一条，都必须视为失败或高风险状态：

- 输出计数与当前 v1 热度榜核心数字明显不一致，却没有给出窗口解释
- 统计范围包含了 16 个登记技能之外的技能
- 写回不是通过 `mcp_lark_lark_download.py` / `mcp_lark_update_lark_doc.py` 完成
- 目标表格不是 `## 一、技能存量清单 (Skill Registry)` 下方那张表
- 只更新了部分技能行，或者表格末列仍为空
- 没有二次下载目标文档做 RAW 回读
- `output/heatmap_counts.json` 中缺少 `wiki_update.readback.success`

## Verification（强制验收）

宣称"技能已跑通"前，必须同时满足：

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
- Wiki 写回失败：直接报错，不得声称"只是没回写成功但统计已完成"
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
  4. 通过飞书 MCP 写回"近30天使用次数"列。
  5. 再次下载 Wiki 文档做 RAW 回读，确认 16 行末列已成功落盘。
  ```

## 资源

- 主脚本：`scripts/generate_skill_heatmap.py`
- 输出目录：`output/`（被 `.skillignore` 排除，不会进归档包）

## Changelog

- **V1.2 (2026-05-20)**：
  - SKILL.md 重构为 L1-L4 总览置顶结构，新增完整的【依赖声明】章节（含 MCP 子脚本依赖矩阵）。
  - 新增 `.skillignore`，把 `output/`、`__pycache__/`、`_release/` 排除出归档打包域。
  - `setup.sh` 显式声明本技能仅依赖标准库 + 内置 MCP 包装器，无额外公网包。
- **V1.1**：v1 兼容口径稳定，新增 RAW 写后回读验收。
- **V1.0**：将旧版 `heat_probe.py` 启发式逻辑固化为本地技能。
