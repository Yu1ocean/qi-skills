---
name: video-script
description: 结构化拆解优质视频脚本的方法论，支持分析叙事结构、黄金前三秒钩子、情绪曲线、信息密度、转化动作，并输出可复用脚本模板与 AB 实验建议。适用于爆款视频复盘、短视频脚本优化、内容方法论沉淀、达人口播/剧情/测评/带货视频拆解等场景。
author: 于奇楠
---

version: 1.3
# 视频脚本（Video Script）

把“一个视频为什么有效”拆成可复用的方法论资产，而不是停留在主观夸赞。

## Common Rationalizations（常见借口库）

以下借口一旦出现，视为准备绕过结构化拆解：

- “这个视频感觉不错，直接总结成几句经验就行。”
- “没有完整数据，先把播放高归因为脚本优秀。”
- “前三秒没啥特别的，但整体感觉很顺，先忽略开场。”
- “情绪曲线太抽象，随便写个高潮点就行。”
- “先给模板，回头再补证据和时间轴。”
- “这个视频属于玄学爆款，没法拆。”
- “先出拆解结论，创建时间以后补。”
- “拿不到发布时间就先留空，反正拆解的是脚本结构不是时效。”
- “publish_time 是 NULL，那就填今天 / 填 0 / 留空串。”
- “视频是哪年发的不影响方法论，下游归档自己去查。”

## Red Flags（危险信号）

出现任意一条，必须降级结论或显式标注待验证：

- 没有视频原文、逐字稿或时间轴证据，却把效果归因写成确定事实。
- 只分析标题和封面，没有分析开场、主体推进、收口与 CTA。
- 只给笼统结论（如“节奏好”“很有共鸣”），没有拆到具体句子、片段或结构作用。
- 把平台分发、题材红利、投流影响全部误归因为脚本优势。
- 没有给出可复用模板或下一轮实验建议，只做描述性复盘。
- 输出结构缺 `created_at` 字段（视频原始发布时间）。
- `created_at` 解析失败时填了空串 / `None` / `0` / 今天，而不是字符串 `NULL`。
- `publish_time` 为 NULL 时未尝试 video_id snowflake 反解就直接判定不可知。
- 输出的 `created_at` 字段名或格式与下游 `script-archive` 不一致，导致二次清洗。

## Verification（强制验收清单）

当你宣称“视频脚本拆解完成”时，必须同时满足：

1. **输入判定清楚**：明确当前基于视频链接、逐字稿、脚本文案还是主题假设进行分析。
2. **结构完整**：至少覆盖钩子、主体推进、情绪曲线、信息密度、收口 / CTA 五部分。
3. **证据可回溯**：关键判断能回到原句、原片段或明确的时间段。
4. **结论可复用**：沉淀出可迁移的方法论，而不是只描述这个视频本身。
5. **行动可执行**：给出脚本模板、可替换写法或 AB 实验建议。
6. **created_at 与时效状态字段完整性验收**：输出结构必须含 `created_at`
   （`YYYY-MM-DD` 或字符串 `NULL`）、`created_at_source` 与 `freshness_status`
   （`✅ 时效内` / `⚠️ 历史存量` / `❓ 待核实` 三态之一），且已通过
   `assert_case_created_at()` 断言；缺失或格式非法即熔断，不得交付给下游归档。

## 何时使用

当用户要做以下事情时触发：

- 拆解一个好视频为什么有效
- 结构化总结爆款视频的方法论
- 从视频 / 逐字稿中抽取脚本结构和叙事套路
- 优化短视频脚本、口播提纲、带货话术或内容节奏
- 把零散视频观察沉淀为团队可复用 SOP

## 输入类型与默认处理

### 输入 A：视频链接或本地视频
优先按“时间轴拆解”路径处理，识别开场、转折、高潮、收口。

若视频时长较长，或直接分析工具返回 `AIME Server exit status 1`、超时、空结果等不稳定信号，不要重复盲撞同一路径；自动降级为“超长视频自动切片分析兜底”路径：先把视频按固定时长切片，再逐段分析，最后合成统一 case JSON 与脚本拆解结论。

### 输入 B：逐字稿或脚本文案
优先按“文案结构拆解”路径处理，重点分析句子顺序、信息密度和钩子设计。

### 输入 C：只有主题，没有现成素材
不要假装在复盘现有爆款；改为输出“方法论框架 + 脚本模板 + 实验建议”。

## Defaults（合规默认值）

- `DEFAULT_OUTPUT_BLOCKS = 6`：默认输出“视频画像 / 结构拆解 / 高效原因 / 风险短板 / 方法论 / AB 实验”六段。
- `DEFAULT_HOOK_WINDOW_SECONDS = 3`：默认优先检查前 3 秒钩子。
- `DEFAULT_ANALYSIS_MODE = "evidence_first"`：有素材时默认做证据型拆解；无素材时降级为模板型输出。
- `DEFAULT_EXPERIMENT_VARIABLES = 1`：每轮 AB 实验默认只改 1 个变量。
- `DEFAULT_METRICS = ["3秒留存", "完整播放率", "互动率", "点击率/转化率"]`：默认观察指标。
- `DEFAULT_CONFIDENCE_LABEL = "基于有限样本判断"`：素材不完整时默认显式打标。
- `DEFAULT_CREATED_AT_NULL = "NULL"`：`created_at` 解析失败时的唯一合法填充值（字符串 `NULL`，非空串 / None / 0）。
- `DEFAULT_FRESH_CUTOFF_DAYS = 90`：≤90 天判 `✅ 时效内`，>90 天判 `⚠️ 历史存量`。
- `DEFAULT_DATE_FORMAT = "%Y-%m-%d"`：`created_at` 统一日期格式，与下游 `script-archive` 对齐。

## 默认输出结构

### 时效元数据（强制字段）

# [FIELD-CREATED_AT-v1] 创建时间字段，来源平台 publish_time，禁止删除

每条拆解结果的输出结构都必须携带以下三个字段，作为脚本案例的**时效元数据**：

| 字段 | 含义 | 取值 |
|---|---|---|
| `created_at` | 视频原始发布时间 | `YYYY-MM-DD`；解析失败为字符串 `NULL` |
| `created_at_source` | 时间来源溯源 | `publish_time` / `metadata` / `snowflake` / `NULL` |
| `freshness_status` | 时效状态 | `✅ 时效内`（≤90 天）/ `⚠️ 历史存量`（>90 天）/ `❓ 待核实` |

解析优先级（由技能自包含模块 `scripts/created_at_resolver.py` 承接，口径与
`hot-radar/pub_date_guard.py` 同源）：

1. 平台 `publish_time`（含 `publish_date` / `pub_date` / `timestamp` / `upload_date`）；
2. `metadata` 内同名字段；
3. **缺失时走 snowflake 反解**：从 `video_id` 或视频 URL 抽取 ID，取高 32 位反解 unix 秒；
4. 仍失败 → 字符串 `NULL`。**严禁**空串 / `None` / `0` / 今天。

为什么必须在拆解阶段就带上：下游 `script-archive` 归档时需要按时效分层。若这里
留空，归档端只能拿到「不知道多久以前」的案例 —— 这正是本轮 P0 审计发现的
「入库样本中位年龄 436 天、74.4% 超 90 天」的根因之一。字段名与格式两侧已对齐，
下游可直接消费，无需二次清洗。

注入与校验脚本：

```bash
# 注入（原地 / 输出到新目录）
python3 scripts/attach_created_at.py --input-dir output/cases --in-place

# 只校验（缺字段即非 0 退出）
python3 scripts/attach_created_at.py --input-dir output/cases --verify-only
```

始终优先输出以下六段：

1. **视频画像**：类型、目标受众、核心承诺、预期转化动作
2. **时间轴 / 结构拆解**：按片段说明每一段在做什么
3. **高效原因**：这个视频为什么能留人、推动观看或触发转化
4. **风险与短板**：什么地方可能掉人、失真、啰嗦或转化弱
5. **可复用方法论**：抽象成脚本原则、钩子公式、节奏框架
6. **AB 实验建议**：下一版具体改哪一处、验证什么指标

## 标准 SOP

### Step 1：判定任务形态
先确认是在做“复盘现有视频”，还是“生成未来脚本方法论”。

- 有现成素材 → 做证据型拆解
- 只有主题 → 做模板型输出

### Step 2：建立视频画像
最少回答以下四个问题：

- 这条视频在跟谁说话？
- 它承诺了什么价值？
- 它想让用户产生什么动作？
- 它更像口播、剧情、测评、带货还是知识型？

### Step 3：拆黄金前三秒
优先判断开场是否使用以下任一机制：

- **反差**：打破预期
- **利益**：先给收益承诺
- **悬念**：制造信息缺口
- **身份**：锁定特定人群
- **冲突**：直接抛矛盾

如果前三秒不强，不要硬吹；直接指出问题，并给出替代钩子。

### Step 4：拆主体推进逻辑
判断主体采用了哪种常见结构：

- 问题 → 原因 → 解法
- 冲突 → 转折 → 反转
- 观点 → 证据 → 结论
- 痛点 → 产品 / 方案 → 结果
- 案例 → 提炼 → 方法论

拆解时说明：每一段的任务是什么，它如何推动用户继续看下去。

### Step 5：识别情绪曲线与信息密度
至少标出：

- 起点：用户为什么愿意停留
- 拉升点：哪里开始更有兴趣/紧张/期待/爽感/共鸣
- 高潮点：最值得记住的一句或一幕
- 收口：结论、反转、CTA 或余味

同时判断哪些段落信息密度高、哪些段落拖沓。

### Step 6：拆转化动作
如果视频存在明确商业或行动目标，必须回答：

- CTA 出现在什么位置？
- CTA 是直接下指令，还是通过结果展示自然引导？
- 有没有证据、案例、对比或身份背书增强信任？
- 是否存在“内容很好看，但不转化”的结构断层？

### Step 7：提炼方法论，不要只写观后感
把上一步观察抽象成规则，优先沉淀为：

- 钩子公式
- 结构骨架
- 金句写法
- 节奏原则
- CTA 放置原则

需要更多细项时，读取 `references/analysis-checklist.md`

### Step 8：输出可复用模板与实验建议
如果用户想复用，至少给出一版可套用的脚本骨架。常见模板和钩子公式见 `references/script-templates.md`

AB 实验建议遵循两条原则：

- 一次只改一个变量
- 指标与改动一一对应（如 3 秒留存、完整播放率、互动率、点击率）

### Step 9：超长视频自动切片分析兜底
当视频直接分析失败，尤其出现 `AIME Server exit status 1`、超时、服务端退出、返回空 JSON、时长超过单次稳定分析窗口等情况时，必须触发本兜底路径，禁止对同一原视频连续重复调用失败工具超过 1 次。

执行规则：

1. **先记录失败信号**：保留原始视频路径 / URL、时长、失败命令或工具名、错误摘要，写入 DLQ 或任务日志，便于复盘。
2. **物理切片**：将原视频切成连续片段，默认每段 120-180 秒；若视频节奏很密，可缩短到 60-90 秒。切片必须保留顺序编号，如 `part1.mp4`、`part2.mp4`。
3. **逐段分析**：分别对每个切片执行视频理解 / 画面与口播分析，输出片段级 JSON。每段至少包含：`part_index`、`source_range`、`hook_or_scene`、`key_events`、`script_signals`、`cta_signals`、`risk_notes`。
4. **统一合成 case JSON**：按原时间顺序合并所有片段，生成单条视频级 case。合成时必须把相对时间映射回全片时间轴，避免片段内 `00:10` 被误读为全片 `00:10`。
5. **降级标记**：最终结论必须标注 `analysis_mode: segmented_fallback`，并说明“基于切片分析合成”。如果某个切片失败，保留 `missing_segments`，不要补写不存在的证据。
6. **恢复标准输出**：切片合成后，仍按默认六段结构输出：视频画像 / 时间轴拆解 / 高效原因 / 风险短板 / 可复用方法论 / AB 实验建议。

推荐 case JSON 字段：

```json
{
  "analysis_mode": "segmented_fallback",
  "source_video": "<video_path_or_url>",
  "created_at": "2026-08-01",
  "created_at_source": "snowflake",
  "freshness_status": "✅ 时效内",
  "duration_seconds": null,
  "segments": [
    {
      "part_index": 1,
      "source_range": "00:00-02:00",
      "hook_or_scene": "",
      "key_events": [],
      "script_signals": [],
      "cta_signals": [],
      "risk_notes": []
    }
  ],
  "merged_timeline": [],
  "missing_segments": [],
  "confidence_label": "基于切片分析合成"
}
```

## Runtime Assertions（运行时断言）

在真正给出结论前，执行以下断言；任一失败都要降级或中断，不得假装完成：

```python

def validate_input(material_type, has_evidence):
    if material_type not in {"video", "transcript", "script", "topic_only"}:
        raise ValueError("未知输入类型，禁止直接输出结论")
    if material_type != "topic_only" and not has_evidence:
        raise ValueError("缺少可回溯证据，禁止做证据型拆解")


def validate_structure(blocks):
    required = {"视频画像", "结构拆解", "高效原因", "风险与短板", "可复用方法论", "AB实验建议"}
    if not required.issubset(set(blocks)):
        raise ValueError("输出结构不完整，必须返工")


def validate_claims(has_timestamps, confidence_label):
    allowed_degraded_labels = {"基于有限样本判断", "基于切片分析合成"}
    if not has_timestamps and confidence_label not in allowed_degraded_labels:
        raise ValueError("缺少时间轴证据时，必须显式降级口径")


# [FIELD-CREATED_AT-v1] 创建时间字段，来源平台 publish_time，禁止删除
# 实现位于 scripts/created_at_resolver.py / scripts/attach_created_at.py
def assert_case_created_at(case):
    value = case.get("created_at")
    if value is None or str(value).strip() in {"", "0", "None"}:
        raise ValueError("created_at 为空/None/0，必须为 YYYY-MM-DD 或字符串 NULL")
    if str(value) != "NULL" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
        raise ValueError("created_at 格式非法，必须为 YYYY-MM-DD")
    if not str(case.get("freshness_status", "")).strip():
        raise ValueError("缺少 freshness_status 字段")


def validate_segmented_fallback(analysis_mode, segments, missing_segments):
    if analysis_mode == "segmented_fallback":
        if not segments:
            raise ValueError("切片兜底模式必须保留至少一个片段级分析结果")
        for segment in segments:
            required = {"part_index", "source_range", "key_events", "script_signals"}
            if not required.issubset(set(segment.keys())):
                raise ValueError("片段级 JSON 字段不完整，禁止合成最终结论")
        if missing_segments is None:
            raise ValueError("切片兜底模式必须显式声明 missing_segments，可为空数组")
```

只有断言通过，才继续输出正式结论。

## 类型分支

### 口播知识型
重点看：开场承诺、观点排序、金句密度、结论收束。

### 剧情反转型
重点看：冲突建立、误导设计、反转时机、情绪释放。

### 测评对比型
重点看：问题定义是否清楚、比较维度是否稳定、结论是否对人群分层。

### 带货种草型
重点看：痛点唤醒、卖点展示、信任建立、CTA 时机。

### 知识干货型
重点看：信息压缩能力、结构清晰度、案例支撑与可执行性。

## 输出口径要求

- 没有数据，就不要伪造播放原因或转化率。
- 可以判断“脚本可能贡献了什么”，不能把平台流量因素偷换成脚本结论。
- 如果素材不完整，明确标注“基于有限样本判断”。
- 结论尽量写成“观察 → 作用 → 可复用规则”的三段式。

## 推荐表达模板

### 1. 视频画像
- 类型：
- 目标受众：
- 核心承诺：
- 目标动作：

### 2. 结构拆解
- 开场：
- 主体第 1 段：
- 主体第 2 段：
- 高潮：
- 收口 / CTA：

### 3. 方法论提炼
- 钩子原则：
- 结构原则：
- 情绪原则：
- 转化原则：

### 4. 下一轮实验
- 实验变量：
- 预计影响指标：
- 验证方式：

## 按需读取的参考资料

- `references/analysis-checklist.md`：需要更细颗粒度拆解时读取。
- `references/script-templates.md`：需要直接输出脚本模板、钩子公式或 AB 实验模板时读取。
- `scripts/created_at_resolver.py`：创建时间解析与时效分类的技能自包含实现。
- `scripts/attach_created_at.py`：给 case JSON 注入 / 校验 `created_at` 元数据。

## Changelog

- **v1.3 (2026-08-21)**：输出结构新增「创建时间（created_at）」时效元数据字段。
  - 新增技能自包含模块 `scripts/created_at_resolver.py`（`resolve_created_at` /
    `classify_freshness` / `extract_video_id` / `decode_snowflake_date`），snowflake
    反解口径与 `hot-radar/pub_date_guard.py` 同源。
  - 新增 `scripts/attach_created_at.py`：给 case JSON 注入并断言 `created_at` /
    `created_at_source` / `freshness_status`，支持 `--in-place` / `--output-dir` / `--verify-only`。
  - 字段名与格式与下游 `script-archive` 两侧对齐（`YYYY-MM-DD`，缺失为字符串 `NULL`），
    避免二次清洗。
  - 来源：`ledger_year_audit_20260821 / DEC-20260821（热门剧本沉淀 P0 治理）`。

- **v1.2 (2026-06-14)**：补齐“超长视频自动切片分析兜底”SOP。直接分析遇到 `AIME Server exit status 1`、超时、空结果或超出稳定窗口时，自动转为切片分析 → 片段级 JSON → 合成 case JSON，避免同类样本反复卡死。
- **v1.1 (2026-06-08)**：首发版本。定义“视频画像 → 时间轴拆解 → 方法论抽象 → 模板重构 → 实验建议”的主流程，补齐前三秒钩子、情绪曲线、CTA 与复用模板口径。
