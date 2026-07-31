<title>skill-heatmap-generator 技能说明</title>

<figure view-type="Card"><source name="skill-heatmap-generator.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OWJhMzUxMGI4YzE4ZjgwOTNjM2Q2N2I4NDM4ZmZjMmFfNDIwZTc4MGMzNjY5MDcyZTY4YmE1MmJkNTQxZWYwZGFfSUQ6NzY0MTc5MTM1MDYwMjIyMjUyM18xNzg1NDc0MDkyOjE3ODU0Nzc2OTJfVjM" mime="application/zip" size="13218" token="NnVXbaNEMo6o4uxN3LdcOd83nuf"/></figure>

# skill-heatmap-generator 飞书说明文档

> 关联技能目录：`user_skills/skill-heatmap-generator/`维护：于奇楠 (yuqinan@bytedance.com)同步说明：本文档版本号由 `skill-forge-pipeline-v4` 流水线自动同步覆写。

## 📌 技能简介

`skill-heatmap-generator` 用于刷新 **Skill Registry 飞书 Wiki 文档**中的「近 30 天使用次数」热度榜：

- 复用 v1 兼容口径（slug 启发式 + MCP 写回 + RAW 回读）；
- 不依赖任何业务私有的统计 SDK，只调标准库与内置 MCP 包装器；
- 写入前后强制走 RAW 校验（写 → 等 2s → 读回核对），保证数字与既有热榜口径一致。

**默认目标文档：** `https://bytedance.larkoffice.com/docx/AKmddboNJos7RcxGiOlcoWCvnjd`

## 🔑 触发词

- 核心关键词：

  - Skill Registry 热度
  - 技能热度榜
  - 近 30 天使用次数刷新
  - skill-heatmap-generator
  - generate_skill_heatmap
- 典型指令示例：

  > 刷新一下 Skill Registry 那张技能热度榜用 skill-heatmap-generator 把近 30 天的使用次数顶上去我新加了几个技能，请重新跑一遍 heatmap，并写回那个 docx

## ⚙️ 核心架构 / SOP / 约束条件

### 输入

- 默认目标：`https://bytedance.larkoffice.com/docx/AKmddboNJos7RcxGiOlcoWCvnjd`
- 可选参数详见 `scripts/generate_skill_heatmap.py --help`

### 关键模块

- **slug 启发式（v1 兼容）**：保持既有热度榜口径不动，避免数字漂移；
- **MCP 写回**：通过内置 `mcp_lark_update_lark_doc` 把热度榜段落写回 docx，确保用户身份（非 Bot）落点；
- **RAW 回读**：写入后强制 `sleep 2` → 重新下载 docx → 抽样比对核心 row，发现差异立即熔断。

### 约束 (Guardrails)

- 严禁修改 `scripts/generate_skill_heatmap.py` 既有的 v1 兼容口径；
- 严禁直接 `requests` 飞书 OpenAPI，只能走 MCP；
- 所有飞书写入必须 `include_secrets=true`，且经过 `bytedcli-auth` 身份穿透。

### 输出

- 目标 Wiki 文档中的热度榜段落更新为最新 30 天使用数；
- 终端打印 RAW 回读结果（行级一致性结论）；
- 失败时立刻 `raise`，并在终端显式给出 stderr 关键片段。

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：

  ```Plain Text
  我刚刚新加了 3 个技能，麻烦把 Skill Registry 的热度榜重新跑一下，
  默认目标文档不用换。
  
  ```
- 🤖 标准输出：

  ```Plain Text
  cd user_skills/skill-heatmap-generator \
    && python3 scripts/generate_skill_heatmap.py
  
  → slug 启发式扫描完成，新增 3 条记录
  → MCP 写回 docx：AKmddboNJos7RcxGiOlcoWCvnjd
  → RAW 回读 success=true（与刚写入数据逐行一致）
  
  ```

## 📦 关联资产

- 源码目录：`user_skills/skill-heatmap-generator/`
- 入口脚本：`scripts/generate_skill_heatmap.py`
- 依赖装载：`.aime/setup/setup.sh`（仅标准库 + MCP 包装器）
- 打包排除：`.skillignore`（`output/`、`__pycache__/`、`_release/`）

<figure view-type="Card"><source name="skill-heatmap-generator.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OTU3NGE5NTZiNjNhMmQwZGJjYmEyMDNlNzA1NWE2ZTFfYjlhZmYwNWZkMmY0NWMzMjllZDU5M2E3MzRiMThkMGNfSUQ6NzY2ODU1Mjk4MDcyNzQ4MzMyMV8xNzg1NDc0MTMwOjE3ODU0Nzc3MzBfVjM" mime="application/zip" size="26171" token="BbDsbHaqdocLwlxhtW6c8E5InUe"/></figure>

<figure view-type="Card"><source name="skill-heatmap-generator.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZjU4OWNlOWJjMjMwMjViMGUyMTBkMmRiNWZjNWE3YTNfM2QyOTdmZDM4YTllOTE4ODBkOTcxNzIzMWVmYzRhNzhfSUQ6NzY2ODU1MzE1NDQ3Nzk2ODU4OV8xNzg1NDc0MTcwOjE3ODU0Nzc3NzBfVjM" mime="application/zip" size="26171" token="TnMIbXP2co8CU6xkaN1cjhrnnNe"/></figure>