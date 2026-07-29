---
name: interview-matrix-evaluator
description: 对候选人评估结果做横向矩阵比较并输出排序与权衡结论。适用于校准会、评审会、同岗位多人对比和终局录用决策场景。
author: 于奇楠
---

version: 1.4
# interview-matrix-evaluator

用于把多个 `interview-hologram-scanner` 的标准化输出，压缩成一份可供评审会快速决策的“候选人矩阵对比结论”。

## 技能简介
- 解决问题：把多位候选人的分散扫描结果，统一映射到同一 JD / 北极星指标下，避免“各说各话”式拍脑袋比较。
- 适用对象：招聘经理、业务负责人、校准面评人、候选人评审会主持人。
- 核心收益：输出可解释的横向排序、长短板差异、零信任盲区横评、补面建议与最终录用顺位。

## 触发场景
在以下场景使用本 Skill：
- 已拿到 2 份及以上 `interview-hologram-scanner` 标准化 JSON，需要做横向比较。
- 需要在统一 JD、统一业务北极星指标下，对同岗位候选人做终局校准。
- 需要把“谁排第 1、为什么不是第 2”讲清楚，而不是只给模糊推荐。
- 需要显式标注证据稀薄区、信息盲区、补面缺口和误判风险，避免强行排序。

## Common Rationalizations（常见借口库）
- “A 候选人感觉更稳，就先排第一。”
- “不同面试官标准不一样，但大概能比较。”
- “有些字段没给也没关系，我先脑补一个总评。”
- “排序先给出来，权衡理由后面再补。”
- “风险矩阵太麻烦，先只看平均分。”
- “MKT 画像太长了，先沿用默认 6 维就行。”

## Red Flags（危险信号）
- 输入不是 `interview-hologram-scanner` 结构化 JSON，却直接进入横评。
- 不同候选人的 JD / 北极星口径不一致，却直接做总分比较。
- `job_family=MKT` 且 `sub_type=MKT_LD` 时，仍沿用通用 6 维雷达而未切换到 MKT LD 专属画像维度。
- 只比较分数，不比较证据密度、风险暴露和盲区大小。
- 直接输出录用顺位，但没有说明关键 trade-off。
- 缺失数据未标 `NULL`，而是被隐式补齐。

## Verification（强制验收清单）
宣称“矩阵评审完成”时，必须同时满足：
1. 输入候选人数 ≥ 2，且每份输入都能识别为 `interview-hologram-scanner` 的标准化 JSON。
2. 统一评审锚点已明确记录：`job_family`、`sub_type`、JD、业务北极星指标、必须能力项、风险阈值；未知项必须标记 `NULL`。
3. 全部候选人输入中的 `scanner_output.input_alignment.job_family` 与当前 `decision_anchor.job_family` 一致；若不一致必须先熔断，不得继续排序。
4. 当 `job_family=MKT` 且 `sub_type=MKT_LD` 时，能力雷达必须切换为以下 4 个画像维度：`会讲故事，专业长板显著。 / 会打仗 / 会算账 / 强领导力`；其余场景使用默认 6 维。
5. 已输出候选人能力雷达叠图所需的统一维度分，并明确每位候选人的长板 / 短板。
6. 已输出零信任横评：证据稀薄区、逻辑盲区、口径漂移、关键风险。
7. 最终结果必须包含：
   - `ranking`：明确顺位 `1, 2, 3...`
   - `hire_recommendation`：`建议录用 / 推进补面（指定补面问题） / 可保留观望 / 暂缓 / 不建议录用`
   - `core_tradeoff_reason`：说明“为什么这个候选人排在这个位置”
   - `followup_interview`：输出是否需要补面、补什么、补哪几个维度
   - `interviewer_feedback`：为面试官提供切实可行的改进建议
8. 所有缺失字段统一写 `NULL`，禁止脑补。

## Defaults（合规默认值）
- 默认分析语言：`zh-CN`
- 默认允许的岗位序列：`BD / MKT`
- 默认最小候选人数：`2`
- 默认 `sub_type`：`NULL`
- 默认雷达维度（default fallback）：业务理解、结构化拆解、数据敏感度、推动力、协同影响力、学习迭代力
- 默认 MKT LD 专属雷达维度（来自人才画像 SSOT）：会讲故事，专业长板显著。 / 会打仗 / 会算账 / 强领导力
- 默认排序优先级：业务匹配度 > 证据密度 > 风险暴露 > 字节范 > 潜力弹性
- 默认缺失值占位：`NULL`
- 默认 hire recommendation 枚举：`建议录用 / 推进补面（指定补面问题） / 可保留观望 / 暂缓 / 不建议录用`

## Runtime Assertions（运行时物理熔断）
- 执行前必须运行 `python3 scripts/validate_matrix_output.py <output_json_path>`，对最终 JSON 做结构、岗位锚点、雷达维度与关键枚举校验。
- 若 `meta.candidate_count < 2`、`decision_anchor.job_family` 缺失或不是 `BD / MKT`、默认/专属雷达维度缺失、`ranking` 不连续、`hire_recommendation` 越界，必须 `raise` 并熔断。
- 若 `job_family=MKT` 且 `sub_type=MKT_LD`，但 `radar_overlay.dimensions[*].dimension_name` 不等于 MKT LD 专属维度集合，必须 `raise`。
- 若 `top_pick_candidate_id` 不在 `ranking_result` 中，或 `followup_interview.candidate_id` 非 `NULL` 但不在 `ranking_result` 中，也必须 `raise` 并拒绝继续交付。

## 输入定义
### 必填输入
1. 至少 2 份 `interview-hologram-scanner` 的标准化 JSON
2. `job_family`（仅允许 `BD` 或 `MKT`）
3. 统一评审基准（至少包含以下其一，建议全部提供）：
   - JD / Role Expectation
   - 业务北极星指标
   - must-have 能力项

### 可选输入
1. `sub_type`（当前用于识别 `MKT_LD`，未指定时使用 default fallback）
2. 面试轮次权重 / 面试官权重
3. 风险容忍度（例如：强执行优先、稳定性优先、成长性优先）
4. 候选人来源、级别、目标市场（UK/EU/JP/Global）

## 工作流
### 1. 岗位门禁断言与锚点统一
- 第一步先断言 `job_family`，只允许 `BD / MKT`。
- 校验所有输入文件是否来自 `interview-hologram-scanner`。
- 对齐 `job_family`、`sub_type`、JD、北极星指标、must-have 能力项与排序口径。
- 若发现候选人输入中的岗位序列不一致，必须显式熔断，不得继续比较。
- 若发现口径不一致，必须显式指出，并在结论中降低置信度。

### 2. 能力维度归一化与雷达叠图
- 默认使用通用 6 维：业务理解、结构化拆解、数据敏感度、推动力、协同影响力、学习迭代力。
- 当 `job_family=MKT` 且 `sub_type=MKT_LD` 时，切换为 MKT LD 专属 4 维：会讲故事，专业长板显著。 / 会打仗 / 会算账 / 强领导力。
- 从每位候选人的 radar、STAR 证据、final_conclusion 中提取统一比较维度。
- 输出同维度对比结果，明确谁的长板最强、谁的短板最危险。
- 若原始维度缺失，保留 `NULL`，不得造分。

### 3. 零信任风险横评
- 横向比较每位候选人的逻辑盲区、基准漂移、证据稀薄区与 follow-up 缺口。
- 形成风险矩阵：严重度 × 不确定性 × 业务影响。
- 标注哪些排序结论是“已证实 / 高概率 / 待验证”。

### 4. 排序决策与权衡理由
- 基于统一 JD / 北极星指标，输出候选人录用顺位 `1, 2, 3...`。
- 对每位候选人给出 `hire_recommendation` 与 `core_tradeoff_reason`。
- 必须显式说明：为什么第 1 名胜过第 2 名，为什么第 2 名不是第 1 名。
- 当证据不足但尚有潜力时，允许输出 `推进补面（指定补面问题）`，并同时产出 `followup_interview`。

## 输出结构建议
1. 评审 meta
2. 决策锚点卡（JD / 北极星 / must-have / 权重 / sub_type）
3. 候选人摘要矩阵
4. 能力雷达叠图数据
5. 长短板差异总结
6. 零信任风险矩阵
7. 排名结果
8. 核心 trade-off 与最终建议
9. 补面建议（followup_interview）
10. 给面试官的改进建议 (interviewer_feedback)

## 产物清单
- `prompt_template.md`：主 Prompt 模板
- `schema.json`：结构化输出 Schema
- `example_output.json`：标准结构化输出样例
- `scripts/validate_matrix_output.py`：运行时输出校验脚本
- `CHANGELOG.md`：版本变更记录

## 更新日志（本地）
- `v0.1`：完成首版草稿，补齐矩阵评审 Prompt 与 Schema。
- `v1.1`：进入首次正式发布，新增 example output、运行时校验脚本与发布入库链路。
- `v1.2`：在输出结构末尾增加“给面试官的改进建议”模块。
- `v1.3`：新增岗位序列门禁与 `decision_anchor.job_family` 必填约束。
- `v1.4`：引入 `sub_type` 与 MKT LD 专属雷达维度，细化录用建议枚举，并新增 `followup_interview` 输出结构。

## 使用要求
- 最终结果只输出符合 `schema.json` 的 JSON。
- 若输入文件并非本 Skill 预期结构，先熔断并说明缺口，不要硬排。
- 当排序依据冲突时，优先引用统一 JD / 北极星指标；无法定夺时输出并列风险与待补问题，不强行制造确定性。
- 当 `job_family=MKT` 且 `sub_type=MKT_LD` 时，以飞书 Wiki SSOT（`https://bytedance.larkoffice.com/wiki/RwIfw3qSeivTYnkI7mLcYODNntg?sheet=sBvNjO` → `2B MKT人才画像2605`）为唯一画像来源，不得回退到历史记忆版本。
