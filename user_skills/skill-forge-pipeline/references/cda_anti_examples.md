# CDA Guardrails 反例库（CDA Anti-Examples）

> 本文件为 **Forge 阶段 `CDA-Guardrails-Selfcheck`** 的配套反例库：当自检失败时，直接对照“正例修正”代码片段做修复。

## 反例 1：`title_prefix` 默认空 → 规则要求加【预占】但默认没给 → 被绕过

- **症状**：子 Agent 创建日程/文档时没带【预占】前缀。
- **根因**：规则与默认参数脱节；模型会依赖默认值。

### 正例修正（默认层 + 断言层）

```python
DEFAULT_TITLE_PREFIX = "【预占】"

class GuardrailViolation(ValueError):
    pass

def validate_title(title: str) -> None:
    if not title.startswith(DEFAULT_TITLE_PREFIX):
        raise GuardrailViolation(f"title must start with {DEFAULT_TITLE_PREFIX}")
```

---

## 反例 2：核心红线埋在文档中部 → Attention 被稀释

- **症状**：模型执行时跳过“先盘候选、再建会”的流程。
- **根因**：红线在长文档中段，注意力易漂移；执行压力下更容易“先做再说”。

### 正例修正（认知层 + 默认层）

```markdown
## Red Flags（危险信号）
- 未完成候选时段确认（pick）前，禁止创建任何日历事件。

## Verification（强制验收清单）
- 必须先输出候选时段列表并获得用户显式确认，再进行创建。
```

---

## 反例 3：只写“严禁 XX”，没写“典型借口有哪些” → 子 Agent 会找新借口

- **症状**：模型用“时间紧/用户大概就这个意思/先把会建了再改”等话术合理化违规。
- **根因**：禁止性规则没有覆盖模型的“自我辩护空间”。

### 正例修正（认知层三件套）

```markdown
## Common Rationalizations（常见借口库）
- "先做了再说，后面再补校验。"
- "这次看起来风险不大，可以跳过确认。"

## Red Flags（危险信号）
- 出现"先/稍后/大概/我猜"且没有回读证据 → 立刻熔断。

## Verification（强制验收清单）
- 写后即读（RAW）并贴出原始数组/回读证据，否则不算完成。
```
