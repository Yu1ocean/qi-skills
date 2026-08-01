---
name: aime-dreaming
description: Aime 认知压缩与 Wiki 图谱回写技能，负责运行 Dreaming Cycle、维护本地知识图谱快照、生成拓扑可视化，并通过 lark-cli docs +fetch/+update 将最新 Cycle 同步到 Aime 乐园 Wiki。适用于用户要求执行/修复 Aime-Dreaming、补跑 post_dreaming_hook、更新 Wiki 拓扑页、排查 execute_wiki_swap 或归档认知图谱运行结果时使用。
author: 于奇楠
---

version: 1.0
skill_id: SKL-2608-AIME-DREAMING

# Aime-Dreaming 认知压缩与 Wiki 回写技能

把 Aime 的长期记忆、每日巡检和技能运行信号压缩成可追踪的知识图谱，并把最新图谱状态回写到 Aime 乐园 Wiki。核心原则是：后端快照、前台 Wiki、CONTEXT 与 PATROL 日志必须同频，禁止只生成 manifest 就宣称完成。

## Common Rationalizations（常见借口库）

以下借口一旦出现，视为准备制造“幽灵图谱”或“伪 ACK”：

- “manifest 已经生成，Wiki 前台晚点再补。”
- “lark_download / MCP 工具坏了，今天就先跳过前台回写。”
- “拓扑没变化，所以不需要更新首页 Cycle 与 Timeline。”
- “只改脚本不跑 py_compile / dry-run 验证也可以。”
- “手动修复了飞书页面，不需要回写 CONTEXT.md 和 PATROL.log。”

## Red Flags（危险信号）

出现任意情况时必须熔断、诊断或转入兜底链路，不得宣称闭环：

- `execute_wiki_swap.py` 重新出现旧 `lark_download` / `update_lark_doc` toolset 依赖。
- Wiki 拓扑页或 Aime 乐园首页没有完成写后读校验，就输出“已更新”。
- `wiki_update_manifest.json` 的 `status` 不是 `wiki_updated`，或缺少 `topology_doc_update=success` / `parent_homepage_update=success`。
- `graph_after_dreaming.json`、`CONTEXT.md`、`PATROL.log` 三者对同一 Cycle 的记录不一致。
- SVG / HTML 渲染失败后没有明确兜底说明，却继续替换前台图。

## Verification（强制验收清单）

一次 Dreaming 或修复任务只有同时满足以下条件，才允许标记成功：

1. **脚本健康**：涉及代码变更时，至少通过 `python3 -m py_compile scripts/execute_wiki_swap.py scripts/post_dreaming_hook.py`。
2. **旧依赖清零**：对 `scripts/execute_wiki_swap.py` 执行关键字检查，确认不再依赖旧 `mcp_lark_lark_download.py` / `mcp_lark_update_lark_doc.py` 路径。
3. **Manifest 闭环**：目标 `wiki_update_manifest.json` 写入 `status=wiki_updated`，并记录 `executed_at`、`topology_doc_update`、`parent_homepage_update`。
4. **RAW 读后写**：通过 `lark-cli docs +fetch --api-version v2 --as user` 回捞拓扑页与首页，确认前台 Cycle、生成时间、最新快照和 Timeline 与本地 manifest 一致。
5. **本地记忆同步**：`CONTEXT.md` 与 `PATROL.log` 已追加或更新本轮闭环记录，避免前台和后端记忆分叉。

## 📌 技能简介

`aime-dreaming` 是 Aime 长期认知压缩循环的操作入口。它维护 `projects/Aime-Dreaming` 的图谱快照、巡检证据、拓扑可视化与 Wiki 前台回写链路，确保每一轮 Dreaming Cycle 都能从本地证据落到用户可见的 Aime 乐园 Wiki。

## 🔑 触发词

- 核心关键词：
  - Aime-Dreaming
  - Dreaming Cycle
  - execute_wiki_swap
  - post_dreaming_hook
  - Aime 乐园首页
  - Wiki 拓扑回写
  - 认知图谱快照
- 典型指令示例：
  > 补跑今天的 Aime-Dreaming Wiki 回写，并确认 RAW 校验。
  > 修复 execute_wiki_swap.py 的 lark-cli 链路，然后归档发布。
  > 检查 Dreaming Cycle 最新快照是否已经同步到 Aime 乐园首页。

## 合规默认值 / Defaults

- 默认项目工作区：`projects/Aime-Dreaming/`
- 默认核心脚本目录：`scripts/`
- 默认输出目录：`output/dreaming_YYYYMMDD/`
- 默认拓扑页：`https://bytedance.larkoffice.com/wiki/ZV5fwlNqBiuu4GkNHj2cG27PnWc`
- 默认 Aime 乐园首页：`https://bytedance.larkoffice.com/wiki/JHExwPicJiHc6fkApxZcUMumncg`
- 默认飞书写入身份：`lark-cli docs --api-version v2 --as user`
- 默认执行权限：涉及飞书读取/更新时，必须通过 `bash` 工具设置 `include_secrets=true`

## ⚙️ 核心架构 / SOP / 约束条件

### 1. 读取上下文

执行前先读取：

- `references/project-context.md`：当前图谱状态、目标 Wiki 节点、历史 Cycle 记录。
- `references/patrol-log.md`：巡检和闭环运行日志。
- 目标日期下的 `output/dreaming_YYYYMMDD/wiki_update_manifest.json` 与 `graph_after_dreaming.json`。

### 2. 运行或补跑 Dreaming 后置链路

常规入口：

```bash
python3 scripts/post_dreaming_hook.py --cycle-date YYYYMMDD --execute-wiki-swap
```

仅补跑 Wiki 前台回写时：

```bash
python3 scripts/execute_wiki_swap.py output/dreaming_YYYYMMDD/wiki_update_manifest.json
```

如需回填历史 Timeline：

```bash
python3 scripts/execute_wiki_swap.py output/dreaming_YYYYMMDD/wiki_update_manifest.json --backfill-start-cycle <cycle_number>
```

### 3. 飞书回写链路

`execute_wiki_swap.py` 必须使用 AIME 定制版 `lark-cli` 的原生文档能力：

- 读取：`lark-cli docs +fetch --api-version v2 --as user --doc <url> --doc-format markdown --detail with-ids --format json`
- 更新：`lark-cli docs +update --api-version v2 --as user --doc <url> --command block_replace|block_insert_after --block-id <id> --content <markdown> --doc-format markdown --format json`

不要回退到已下线的旧 MCP 路径。遇到 `config/not_configured` 或权限错误时，按 AIME 定制版 lark-cli 运行时问题处理，不做公版安装、登录或 auth 初始化。

### 4. 验收与回写

执行后必须检查：

1. `wiki_update_manifest.json` 的 `status` 与两个 doc update 字段。
2. 拓扑页标题是否已更新到目标 Cycle。
3. Aime 乐园首页概览、统计表、最新快照、Timeline 是否与 manifest 一致。
4. `CONTEXT.md` 与 `PATROL.log` 是否记录本轮真实执行结果。

## 技能边界

本技能只负责 Aime-Dreaming 认知压缩、图谱快照、拓扑可视化和 Wiki 回写链路。它不负责通用飞书文档写作、普通业务报告生成、视频下载或脚本规则库维护；对应任务应使用 `feishu-doc-writing-guide`、`periodic-report-generator`、`yt-dlp-media-downloader` 或 `script-rule-library`。

## 更新日志

- **v1.0｜2026-08-01**：首次标准 Skill 化入库。固化 `execute_wiki_swap.py` 从旧 `lark_download` toolset 迁移到 `lark-cli docs +fetch / +update` 的修复成果，并把 Aime-Dreaming 的运行、回写与 RAW 验收口径纳入技能说明。