# 向上汇报规律库

version: 1
last_updated: 2026-06-18
status: active

## Active Rules

### R1 判断先行，不是进度汇报
- status: active
- definition: 向上汇报优先回答“现在怎么判断”，而不是只汇报过程动作。
- why_it_matters: 领导需要先知道判断与决策含义，才能理解后续动作是否必要。
- action_prompt: 开头先给结论，再补动作、背景与过程。
- scoring_anchor:
  - 2分：结论前置，管理意义清楚
  - 1分：有判断但位置靠后
  - 0分：只有动作和过程
- example_positive: 当前判断是，SKM+Hipo 招商已进入可规模化推进阶段。
- example_negative: 这周我们推进了招商沟通，并持续跟进了多方反馈。

### R2 分工描述是管理信号
- status: active
- definition: 汇报中的分工信息，不只是执行细节，更是责任与资源是否覆盖的管理信号。
- why_it_matters: 管理者会借此判断责任归属、协同是否到位、资源是否还缺口。
- action_prompt: 清楚写出谁负责什么、协同对象是谁、资源是否覆盖关键环节。
- scoring_anchor:
  - 2分：责任与协同都清晰
  - 1分：提到分工但不够完整
  - 0分：完全没有分工视角
- example_positive: BD 负责重点品牌，运营负责达人承接，策略侧同步判断资源优先级。
- example_negative: 团队都在推进相关工作。

### R3 数字要有锚
- status: active
- definition: 数字必须挂在变化、时间节点和业务目标上，才能形成有效管理信息。
- why_it_matters: 领导关心的不是孤立数字，而是数字对应的进展、时点与业务意义。
- action_prompt: 尽量使用“变化 + 时间节点 + 支撑目标”的表达公式。
- scoring_anchor:
  - 2分：三要素齐全
  - 1分：数字存在但锚点不完整
  - 0分：没有数字或数字失真
- example_positive: 截至本周，首轮触达品牌数较上周提升 30%，已覆盖本阶段重点目标池的 70%。
- example_negative: 我们触达了很多品牌，反馈不错。

### R4 三层比五条清单更清晰
- status: active
- definition: 好的向上汇报更强调层次、优先级和因果关系，而不是平铺清单。
- why_it_matters: 管理者需要快速看懂主次顺序，而不是自己从并列信息里找重点。
- action_prompt: 尽量把表达整理成“总判断 → 关键分层 → 具体支撑”三层结构。
- scoring_anchor:
  - 2分：层次清晰，优先级明确
  - 1分：有分点但结构仍松散
  - 0分：信息平铺，没有主次
- example_positive: 当前先看供给响应，再看资源覆盖，最后看下周动作。
- example_negative: 第一，第二，第三，第四，第五……但各点权重相同。

### R5 诊断语气建立信任
- status: active
- definition: 先给出自己的诊断，再说解法，会让汇报更像在帮助领导做判断。
- why_it_matters: 诊断感代表独立思考，动作则应服务于这个判断，而不是替代判断。
- action_prompt: 先说“问题本质/阶段判断/风险诊断”，再说动作安排。
- scoring_anchor:
  - 2分：先诊断后行动
  - 1分：有诊断意识但顺序不稳
  - 0分：只有动作，没有诊断
- example_positive: 当前不是执行速度问题，而是优先级和资源聚焦问题，因此下周动作会先收缩战线。
- example_negative: 下周我们会继续推进、继续跟进、继续优化。

## Proposed Rules

> 默认把新规律先放在这里，待跨样本验证后再升格为 Active。

- 暂无

## Conflict Notes

> 当组织规范与通用规律冲突时，在这里记录“冲突内容 / 建议处理方式 / 适用边界”。

- 暂无
