# Changelog - interview-matrix-evaluator

## v1.4 (2026-06-10)
- 引入 `sub_type` 概念：当 `job_family=MKT` 且 `sub_type=MKT_LD` 时，雷达维度切换为来自飞书 Wiki SSOT（`https://bytedance.larkoffice.com/wiki/RwIfw3qSeivTYnkI7mLcYODNntg?sheet=sBvNjO` → `2B MKT人才画像2605`）的 4 个专属能力维度：`会讲故事，专业长板显著。 / 会打仗 / 会算账 / 强领导力`。
- 保留原有通用 6 维作为 `default` 兜底，并在 `SKILL.md`、`prompt_template.md`、`schema.json` 与运行时校验脚本中同步升级。
- 细化 `hire_recommendation` 枚举为：`建议录用 / 推进补面（指定补面问题） / 可保留观望 / 暂缓 / 不建议录用`。
- 新增顶层输出字段 `followup_interview`，用于承接候选人补面优先级、补面问题与待验证维度。
- 同步更新 `scripts/validate_matrix_output.py`，新增 `sub_type`、MKT LD 雷达模型与 `followup_interview` 的运行时断言。

## v1.3 (2026-06-09)
- 新增岗位序列门禁：`decision_anchor.job_family` 变为必填，且只允许 `BD / MKT`。
- 在 `scripts/validate_matrix_output.py` 中加入 `validate_decision_anchor()`，若岗位序列缺失或越界则直接熔断。
- 在 `prompt_template.md` 中补齐岗位断言规则，要求所有 `candidate_packets[*].scanner_output.input_alignment.job_family` 与本次横评的 `job_family` 保持一致，否则停止排序。

## v1.2 (2026-05-25)
- 在输出结构的末尾增加一个独立模块 `interviewer_feedback`（给面试官的改进建议）。
- 要求 AI 基于录音中面试官的表现（如提问技巧、时间把控、追问深度、诱导性提问等）给出 1-2 条切实可行的改进建议。
- 更新了 `SKILL.md`、`prompt_template.md`、`schema.json` 和 `example_output.json` 以适配此变更。

## v1.1 (2026-05-24)
- 首次正式发布。
- 新增 `example_output.json`，提供多候选人横向矩阵评审的标准样例。
- 新增 `scripts/validate_matrix_output.py`，对候选人数、默认雷达维度、风险矩阵枚举、排名连续性与 top pick 一致性做运行时校验。
- 完成技能说明、Prompt 模板、Schema、示例输出与发布入库链路的首版闭环。
