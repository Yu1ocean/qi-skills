# Changelog

## v1.3 - 2026-06-09
- 新增岗位前置门禁：`schema.json` 强制要求 `input_alignment.job_family`，并限制为 `BD / MKT` 两档枚举。
- 在 `scripts/validate_output.py` 中加入 `JOB_FAMILY_PROMPT_ROUTES` 路由字典，按岗位映射 `prompts/bd_model.md` / `prompts/mkt_model.md`；若无法匹配则抛出明确 `ValueError` 熔断。
- 在 `prompt_template.md` 中新增岗位门禁 SOP 与开头回显：`> 当前按 XX 岗位能力模型执行深度扫描。`
- 新增 `prompts/bd_model.md` 与 `prompts/mkt_model.md` 两套岗位能力模型 Prompt 片段。

## v1.2 - 2026-05-24
- 通过 `skill-forge-pipeline-v4` 完成正式锻造发布。
- 通过 `cda_guardrails_selfcheck.py` 补齐并验证 L1/L2/L3 三层护栏。
- 补齐 `scripts/validate_output.py` 作为运行时物理熔断器。
- 完成飞书说明文档创建、zip 挂载与专属技能清单 SSOT 同步。
- 清理文件中的 Draft 标识，统一版本号到 `1.2`。

## v0.2 - 2026-05-24
- 新增 `byte_style_rubric.md`，将“字节范”评估拆成 6 个可打分维度与观察锚点。
- 新增 `example_output.json`，提供一份完整结构化样例，便于后续压测与 prompt 对齐。
- 回写 `SKILL.md` 产物清单，补齐 Rubric 与示例输出资产。

## v0.1 - 2026-05-23
- 初始化 `interview-hologram-scanner` 草案技能。
- 起草四段式工作流版 Prompt 模板。
- 新增结构化输出 `schema.json`。
- 将“最终结论”拆为两部分：业务能力四档枚举 + 字节范（ByteStyle）打分。
