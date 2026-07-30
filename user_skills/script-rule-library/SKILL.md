---
name: script-rule-library
description: 脚本规则库管理技能，负责从热门剧本台账和 hot-script-precipitation 输出中聚合方法论信号，维护飞书 Bitable「脚本规则库」主表，并按品类、场景、平台等维度为 video-script 返回结构化规则列表。
author: 于奇楠
---

version: 1.0
skill_id: SKL-2607-SRL

# 脚本规则库管理技能（script-rule-library）

把每日热门剧本里的“方法论信号”沉淀成可查询、可迭代、可被 `video-script` 调用的规则库，而不是让洞察散落在日报、台账和人工记忆里。

## Common Rationalizations（常见借口库）

以下借口一旦出现，视为准备绕过规则库数据契约：

- “先把今天的信号总结一下，频次以后再算。”
- “Bitable 字段差不多就行，少几个维度不影响查询。”
- “规则名相似就算同一条，不需要稳定主键。”
- “找不到品类或场景时先留空，后续人工补。”
- “给 `video-script` 一段自然语言总结就够了，不需要结构化字段。”
- “今天 hot-script-precipitation 没跑完，也按经验补一批规则。”

## Red Flags（危险信号）

出现任意一条，必须熔断、降级或写入 DLQ：

- 未读取热门剧本台账或 hot-script-precipitation 结构化输出，就更新规则频次。
- 更新已有飞书 Bitable 前没有读取 Base / Table / Field schema。
- 缺少 `rule_id`、`rule_name`、`methodology_signal`、`frequency`、`source_batch_id` 等核心字段。
- 找不到来源时写空字符串、`None` 或主观补写，而不是 `NULL` / `[MISSING: ...]`。
- 查询规则时只返回自然语言，不返回可被 `video-script` 直接消费的 JSON。
- 把视频下载、截图或脚本生成逻辑放进本技能。

## Verification（强制验收清单）

当你宣称“脚本规则库已更新 / 查询完成”时，必须同时满足：

1. **输入来源可追溯**：每条新增或更新规则都能回到 `source_batch_id`、`source_record_id` 或热门剧本台账行。
2. **Schema 合同成立**：写入前已确认 Bitable 主表字段，输出行与字段一一对齐。
3. **频次计算可复核**：聚合口径明确为“按规则归一键统计出现次数”，并保留原始信号列表。
4. **幂等更新成立**：相同 `rule_id` 或 `dedupe_key` 只更新频次和最近观测时间，不重复插入。
5. **下游可消费**：面向 `video-script` 的查询结果必须包含 `rules[]` JSON，且每条规则含适用条件、写法建议、证据与风险提示。
6. **边界清楚**：不下载视频、不截图、不生成最终脚本；对应任务分别交给 `yt-dlp-media-downloader` 与 `video-script`。

## 📌 技能简介

`script-rule-library` 是「内容反馈蒸馏规则库」的操作入口。它从 hot-script-precipitation 的每日新增样本中提取方法论信号，统计高频规则，维护飞书 Bitable「脚本规则库」主表，并在需要写脚本时按品类、场景、平台、目标动作返回结构化规则清单。

## 🔑 触发词

- 核心关键词：
  - 脚本规则库
  - 内容反馈蒸馏规则库
  - 规则频次更新
  - 方法论信号聚合
  - 按品类查询脚本规则
  - 给 video-script 取规则
- 典型指令示例：
  > 把今天热门剧本沉淀出来的方法论信号同步到脚本规则库。
  > 查询 US 女装直播切片可用的前三秒钩子规则，给 video-script 用。

## 何时使用

当任务满足以下任一条件时触发：

- 需要读取 hot-script-precipitation / 热门剧本台账输出，并统计方法论信号频次。
- 需要新增、修改、查询飞书 Bitable「脚本规则库」规则条目。
- 需要每日自动更新规则频次，并保持规则库主表幂等。
- 需要按品类、场景、平台、视频类型、目标动作查询规则，作为 `video-script` 的输入。

## 技能边界

本技能只负责“规则库管理”。它不负责视频下载、封面截图、画面抽帧、音频转写，这些任务由 `yt-dlp-media-downloader`、`media-fetcher` 或其他媒体摄入技能处理。它也不负责生成最终脚本、达人口播稿或营销文案，这些任务由 `video-script` 或 `product-copywriting` 处理。

## Defaults（合规默认值）

- `DEFAULT_BASE_NAME = "脚本规则库"`
- `DEFAULT_TABLE_NAME = "主表"`
- `DEFAULT_NULL = "NULL"`
- `DEFAULT_RULE_STATUS = "active"`
- `DEFAULT_MIN_FREQUENCY_FOR_PROMOTION = 2`
- `DEFAULT_DEDUPE_FIELDS = ["normalized_rule_key", "category", "scenario", "platform"]`
- `DEFAULT_QUERY_LIMIT = 20`
- `DEFAULT_OUTPUT_FORMAT = "video_script_rules_json"`

## 数据契约

### 输入：hot-script-precipitation 每日输出

推荐输入为 JSON / CSV / Sheet 行，至少包含以下字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `batch_id` | 是 | 每日采集批次，如 `SAR_20260730` |
| `record_id` | 是 | 热门剧本台账稳定主键 |
| `platform` | 是 | TikTok / 抖音 / 其他 |
| `market` | 是 | US / UK / JP / EU4 / Global 等 |
| `category` | 是 | 女装、配饰、美妆等 |
| `scenario` | 否 | 直播切片、短视频种草、测评、剧情等；缺失写 `NULL` |
| `methodology_signals` | 是 | 方法论信号数组或分隔字符串 |
| `source_url` | 否 | 原视频或案例链接；缺失写 `NULL` |
| `observed_at` | 是 | 观测日期或批次时间 |

### Bitable 主表字段

飞书 Bitable「脚本规则库」主表必须至少维护以下字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `rule_id` | text | 稳定主键，推荐 `SRL-YYYYMMDD-xxxx` |
| `rule_name` | text | 人类可读规则名 |
| `normalized_rule_key` | text | 归一化去重键 |
| `rule_type` | select | hook / structure / proof / emotion / cta / risk |
| `platform` | multi_select | 适用平台 |
| `market` | multi_select | 适用市场 |
| `category` | multi_select | 适用品类 |
| `scenario` | multi_select | 适用场景 |
| `methodology_signal` | text | 原始或归一后的方法论信号 |
| `frequency` | number | 累计出现频次 |
| `last_observed_at` | date | 最近观测日期 |
| `source_batch_id` | text | 最近来源批次 |
| `source_record_ids` | text | 来源台账记录列表，JSON 字符串 |
| `evidence_notes` | text | 支撑案例摘要 |
| `usage_guidance` | text | 供脚本生成时使用的写法建议 |
| `risk_notes` | text | 使用边界与误用风险 |
| `status` | select | active / watch / deprecated |
| `updated_at` | datetime | 最近更新时间 |

### 输出：供 video-script 消费的规则 JSON

查询规则必须输出可机器消费的结构：

```json
{
  "query_context": {
    "platform": "TikTok",
    "market": "US",
    "category": "女装",
    "scenario": "直播切片",
    "objective": "提升前三秒留存"
  },
  "rules": [
    {
      "rule_id": "SRL-20260730-0001",
      "rule_name": "结果画面前置",
      "rule_type": "hook",
      "frequency": 12,
      "usage_guidance": "开场先展示最终效果，再解释过程。",
      "evidence_notes": "近 7 日多个服饰案例出现结果前置结构。",
      "risk_notes": "若效果画面不够强，容易变成普通展示。",
      "source_batch_id": "SAR_20260730"
    }
  ],
  "null_fields": [],
  "generated_at": "YYYY-MM-DD HH:mm:ss"
}
```

## ⚙️ 核心架构 / SOP / 约束条件

### Step 1：读取输入并锁定口径

先确认输入来自热门剧本台账、hot-script-precipitation manifest、CSV/JSON 文件，还是飞书表格行。读取后必须校验 `batch_id`、`record_id`、`methodology_signals` 三个核心字段；缺失任一字段则写入 DLQ，不进入主表更新。

### Step 2：归一化方法论信号

将同义信号归并为稳定 `normalized_rule_key`。例如“结果先行”“先给效果画面”“效果画面前置”归一为 `result-first-hook`。归一时必须保留原始信号列表，禁止只保存人工改写后的结论。

### Step 3：聚合统计频次

按 `normalized_rule_key + category + scenario + platform` 统计出现频次，同时记录来源 `record_id` 列表和最近观测日期。若同一记录内重复出现同一信号，只计 1 次，避免单条案例放大频次。

### Step 4：读取 Bitable Schema 后再写入

所有增改查必须先读取飞书 Bitable 主表字段结构。若目标 Base / Table 未指定，允许按技能配置或用户上下文自动新建；若要更新已有 Base 但上下文没有目标链接，必须向用户确认目标链接。

### Step 5：幂等 Upsert 规则条目

以 `normalized_rule_key + category + scenario + platform` 作为默认去重键。命中已有规则时只更新 `frequency`、`last_observed_at`、`source_batch_id`、`source_record_ids`、`evidence_notes` 与 `updated_at`；未命中时创建新 `rule_id`。任何写入后必须做 RAW 读回校验。

### Step 6：每日自动更新

接收 hot-script-precipitation 每日新增数据后，执行 `daily_update`：读取新增批次、聚合频次、Upsert Bitable、输出更新摘要。若当天输入为空，只记录 `no_new_records`，不得主观补规则。

### Step 7：规则查询与下游交付

按 `platform`、`market`、`category`、`scenario`、`objective` 过滤规则，默认优先返回 `status=active` 且 `frequency` 高的规则。输出必须同时包含人类摘要和 `rules[]` JSON，供 `video-script` 直接引用。

## Runtime Assertions（运行时断言）

```python
def validate_hot_script_row(row):
    required = ["batch_id", "record_id", "methodology_signals"]
    missing = [key for key in required if not row.get(key)]
    if missing:
        raise ValueError(f"热门剧本输入缺少核心字段: {missing}")


def validate_bitable_schema(fields):
    required = {"rule_id", "normalized_rule_key", "frequency", "source_batch_id", "updated_at"}
    missing = required - set(fields)
    if missing:
        raise ValueError(f"脚本规则库主表缺少字段: {sorted(missing)}")


def validate_query_output(payload):
    if "rules" not in payload or not isinstance(payload["rules"], list):
        raise ValueError("查询输出必须包含 rules[]")
    for rule in payload["rules"]:
        for key in ["rule_id", "rule_name", "rule_type", "frequency", "usage_guidance"]:
            if key not in rule:
                raise ValueError(f"规则输出缺少字段: {key}")
```

## 推荐脚本

```bash
python3 scripts/manage_rules.py aggregate \
  --input-path output/hot_script_signals.json \
  --output-path output/rule_frequency_summary.json

python3 scripts/manage_rules.py query \
  --rules-path output/rule_frequency_summary.json \
  --category 女装 \
  --scenario 直播切片 \
  --platform TikTok \
  --output-path output/video_script_rules.json
```

## 异常处理

| 异常 | 处理方式 | 是否继续 |
|---|---|---|
| 输入缺少核心字段 | 写入 DLQ，标记 `[MISSING: FIELD]` | 跳过该行 |
| Bitable schema 缺字段 | 熔断并提示补字段 | 不继续写入 |
| 飞书权限 403 / 404 | 熔断，不新建影子 Base | 不继续写入 |
| 同义规则无法归并 | 保留原始信号，`status=watch` | 可写入观察态 |
| 每日输入为空 | 输出 `no_new_records` 摘要 | 不更新频次 |

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：
  ```text
  把今天 SAR_20260730 的热门剧本方法论信号同步到脚本规则库，并查询 US 女装直播切片可用的规则给 video-script。
  ```
- 🤖 标准输出：
  ```text
  已读取 SAR_20260730 新增记录，按 normalized_rule_key 聚合后更新脚本规则库主表；命中 US / 女装 / 直播切片规则 8 条，已返回 rules[] JSON，可直接交给 video-script 作为生成约束。
  ```

## Changelog

| 版本 | 日期 | 变更 | Owner |
|---|---|---|---|
| v1.0 | 2026-07-30 | 首次锻造：封装方法论信号聚合、Bitable 主表维护、每日频次更新与规则查询能力 | 于奇楠 / Aime |
