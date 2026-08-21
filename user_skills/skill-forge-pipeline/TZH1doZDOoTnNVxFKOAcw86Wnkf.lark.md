# aime-dreaming 技能说明文档

<callout emoji="✅">
**发布锚点：**Skill ID：`SKL-2608-AIME-DREAMING`；版本：`v1.0`；维护人：于奇楠。该技能用于把 Aime-Dreaming 的认知压缩、图谱快照和 Wiki 前台回写链路标准化。
</callout>

## 📌 技能简介

`aime-dreaming` 是 Aime 长期认知压缩循环的操作入口。它维护 `projects/Aime-Dreaming` 的图谱快照、巡检证据、拓扑可视化与 Wiki 前台回写链路，确保每一轮 Dreaming Cycle 都能从本地证据落到用户可见的 Aime 乐园 Wiki。

## 🔑 触发词

- **核心关键词：**Aime-Dreaming、Dreaming Cycle、execute_wiki_swap、post_dreaming_hook、Aime 乐园首页、Wiki 拓扑回写、认知图谱快照。
- **典型指令：**“补跑今天的 Aime-Dreaming Wiki 回写，并确认 RAW 校验。”
- **典型指令：**“修复 execute_wiki_swap.py 的 lark-cli 链路，然后归档发布。”
- **典型指令：**“检查 Dreaming Cycle 最新快照是否已经同步到 Aime 乐园首页。”

## 📖 功能描述

| 模块 | 能力 |
|-|-|
| 认知压缩 | 读取长期记忆、每日巡检和技能运行信号，维护 Dreaming Cycle 图谱快照。 |
| 图谱可视化 | 生成或复用拓扑 SVG / HTML 产物，支撑 Aime 乐园前台展示。 |
| Wiki 回写 | 通过 `lark-cli docs +fetch / +update --api-version v2 --as user` 更新拓扑页与 Aime 乐园首页。 |
| 零信任验收 | 检查 manifest、前台 RAW 回捞、CONTEXT.md 与 PATROL.log，避免只生成后端文件却未同步前台。 |

## ⚙️ 核心架构 / SOP / 约束条件

1. 读取 `references/project-context.md`、`references/patrol-log.md` 以及目标日期下的 `wiki_update_manifest.json`。
2. 常规运行 `python3 scripts/post_dreaming_hook.py --cycle-date YYYYMMDD --execute-wiki-swap`；仅补前台时运行 `python3 scripts/execute_wiki_swap.py output/dreaming_YYYYMMDD/wiki_update_manifest.json`。
3. 飞书文档更新必须使用 AIME 定制版 `lark-cli docs` 原生链路，并显式传 `--api-version v2 --as user`。
4. 验收时检查 `status=wiki_updated`、`topology_doc_update=success`、`parent_homepage_update=success`，并回捞前台页面确认 Cycle、生成时间、最新快照与 Timeline 一致。

## 🛡️ 验收标准

- **脚本健康：**涉及代码变更时，至少通过 `python3 -m py_compile scripts/execute_wiki_swap.py scripts/post_dreaming_hook.py`。
- **旧依赖清零：**`execute_wiki_swap.py` 不再依赖旧 `lark_download` / `update_lark_doc` toolset。
- **前后台同频：**后端 manifest、飞书 Wiki 前台、`CONTEXT.md` 与 `PATROL.log` 对同一 Cycle 的记录一致。

## 📖 案例实录 (Best Practice)

**用户输入：**

```text
补跑今天的 Aime-Dreaming Wiki 回写，并确认 RAW 校验。
```

**标准输出：**

```text
已读取目标 manifest，执行 execute_wiki_swap.py 完成拓扑页与 Aime 乐园首页更新；manifest 已写入 wiki_updated，拓扑页和首页 RAW 回捞确认 Cycle / 生成时间 / 最新快照 / Timeline 一致，CONTEXT.md 与 PATROL.log 已同步记录。
```

## 更新日志

| 版本 | 日期 | 变更 |
|-|-|-|
| v1.0 | 2026-08-01 | 首次标准 Skill 化入库；固化 `execute_wiki_swap.py` 从旧 toolset 迁移到 `lark-cli docs +fetch / +update` 的修复成果。 |

<figure view-type="Card"><source name="aime-dreaming.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ODkyZmVjYTQyZWQwNDYzNDRkMzY0MDM3OWEyYWUwNGNfZjdlNDFlOTczMDBkNzhlY2JlOGMxNjQzMWNmYTA1YTNfSUQ6NzY2ODg2OTI4NTM4MDM3NzU1OF8xNzg1NTQ3Nzc1OjE3ODU1NTEzNzVfVjM" mime="application/zip" size="95694" token="DVtgbn7AFojGylx0uqicwKg2nVh"/></figure>