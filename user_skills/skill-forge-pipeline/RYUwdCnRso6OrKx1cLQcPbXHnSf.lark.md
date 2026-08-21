# 知识归档 script-archive

<figure view-type="Card"><source name="script-archive.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YTcwOTk0NzI0YWFkNmVjZjg3YzdhMDRmOGVjYWQwZDFfYWJlMWE0YjJjNWZjMzM4Nzc4N2Y1Mzg2ZWE5NzQ1MWJfSUQ6NzY3NjQ2ODgyNjE0OTY3MDEzMF8xNzg3MzE3MTgxOjE3ODczMjA3ODFfVjM" mime="application/zip" size="14680" token="EX7fb4ii4oHZrUx4HHHcOj6qnkc"/></figure>

## 📌 技能简介

`script-archive` 负责把多条 `video-script` 拆解结果，聚合成长期可复用的知识资产。

它的输出不是单一总结，而是三件套：飞书案例合集内容稿（`.lark.md`）、视频脚本台账（`.csv`）和批次摘要（`.json`）。随后再通过 `lark` MCP + `feishu-doc-writing-guide` 安全落地到飞书 Docx / Sheet / Base。

## 🔑 触发词

- 核心关键词：

  - 爆款案例合集
  - 视频脚本台账
  - 方法论沉淀
  - 多条 video-script 汇总
  - 脚本归档
- 典型指令示例：

  > 把这批 video-script 结果整理成一份飞书案例合集，再配一个视频脚本台账。帮我把爆款视频拆解结果沉淀成可复用的方法论文档和表格。

## ⚙️ 核心架构 / SOP / 约束条件

### 1. 输入是多条案例，不是单条长总结

支持三种输入方式：

- 一个目录里的多个 JSON
- 多个显式传入的 JSON 文件
- 一个 manifest 文件，内部带 `files` 列表

### 2. 先归一化，再聚合

每条案例聚合前，统一抽出：

- `platform`
- `market`
- `category`
- `account_name`
- `video_title`
- `video_url`
- `video_type_tags`
- `hook_summary`
- `methodology_summary`
- `risk_summary`
- `experiment_summary`
- `source_json`

缺失字段显式写 `NULL`，禁止静默留空。

### 3. 本地先成三件套

本地先生成：

1. `.lark.md`：案例合集正文稿
2. `.csv`：视频脚本台账
3. `.json`：批次摘要

<callout emoji="💡">
`script-archive` 的关键不是“写一段总结”，而是 **先把案例归一化成长期资产，再去写飞书**。没有本地三件套，就不允许宣称归档完成。
</callout>

### 4. 再走飞书落地

如需正式写飞书，必须按顺序：

1. 用 `mcp_lark_create_lark_doc` 创建案例合集 Docx
2. 用 `mcp_lark_create_lark_table` 把 `ledger.csv` 转成 Sheet / Base
3. 若更新旧资产，必须走 `feishu-doc-writing-guide` 的 RAW 写后即读和幂等校验

### 5. 运行脚本

```Bash
python3 scripts/build_archive_bundle.py \
  --input-dir output/video_script_results \
  --output-dir output/archive_bundle \
  --report-file script_archive_report.lark.md \
  --ledger-file video_script_ledger.csv \
  --summary-file script_archive_summary.json

```

### 6. 验收标准

判定“案例归档完成”前，至少满足：

- 至少读取 1 条合法 `video-script` 结果
- 本地三件套都已生成
- 台账每行都有稳定主键
- 方法论总结可回溯到案例证据
- 若已写飞书，必须保留 MCP + RAW 验收痕迹

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：

  ```Plain Text
  我这里有 8 条 video-script 结果，帮我汇成一份爆款案例合集和视频脚本台账。
  
  ```
- 🤖 标准输出：

  ```Plain Text
  已先把 8 条 JSON 归一化，再生成本地 .lark.md 内容稿、ledger.csv 与 summary.json。
  如果需要飞书落地，会继续走 MCP + feishu-doc-writing-guide，把案例合集写成 Docx、台账转成 Sheet/Base，并保留 RAW 回读校验。
  
  ```

## 附：本次首发范围

- 当前版本：`0.1`（发布链路会升迁到正式首发版本）
- 技能目录：`script-archive/`
- 主要脚本：`scripts/build_archive_bundle.py`