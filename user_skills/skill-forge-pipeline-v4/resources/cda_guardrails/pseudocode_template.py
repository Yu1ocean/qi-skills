# CDA Guardrails - 伪代码模板（可复制粘贴）

class GuardrailViolation(ValueError):
    """当输入/默认值/运行时断言不满足合规约束时，必须 raise。"""


def validate_inputs(params):
    """L2 + L3：合规默认值兜底 + 运行时断言（失败即 raise）。"""

    # 1) 合规默认值兜底（必要时）
    # params.title_prefix = params.title_prefix or "【预占】"

    # 2) 关键约束断言
    # if not params.title.startswith("【预占】"):
    #     raise GuardrailViolation("title must start with 【预占】")

    # 3) 失败即 raise（禁止只 log）
    return


def perform_side_effects(params):
    """副作用发生的最后一跳：必须保证 validate_inputs 已通过。"""
    return


def main():
    params = load_params()  # noqa: F821
    validate_inputs(params)
    perform_side_effects(params)
