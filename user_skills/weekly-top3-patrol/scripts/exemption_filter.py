"""
exemption_filter.py — 豁免名单代码层硬过滤模块

【强契约】此处的 EXEMPT_EMAILS 是单一真相源，禁止通过 CLI / 配置文件覆盖。
任何对豁免名单的修改必须显式 commit 此文件，并经过 tests/test_exemption_filter.py 验收。
"""

from __future__ import annotations
from typing import Iterable, Set


# ===== 豁免名单（唯一真相源 / Code-Level Hard Filter）=====
# 修改前请确认：tests/test_exemption_filter.py 已同步更新
EXEMPT_EMAILS: Set[str] = frozenset({
    "jiaoyanchen@bytedance.com",  # 焦彦晨 — 永久豁免（业务方决议）
    "gaochuan.cherry@bytedance.com",  # Cherry Gao — 豁免（业务方决议）
    "wanghaotian.666@bytedance.com",  # 王皓田 — 豁免（业务方决议）
    "huangyizhuo.1992@bytedance.com",  # 黄忆卓 Amy — 豁免（业务方决议）
    "zhanxinyi.0729@bytedance.com",  # 詹欣意 — 豁免（业务方决议）
})


def is_exempt(email: str | None) -> bool:
    """判定一个 email 是否在豁免名单内。空值默认非豁免（即应该被巡检到）。

    Note: 大小写不敏感、自动 strip 空白；防止配置不规范导致漏过滤。
    """
    if not email:
        return False
    normalized = email.strip().lower()
    return normalized in {e.lower() for e in EXEMPT_EMAILS}


def filter_pending(users: Iterable[dict], email_field: str = "email") -> list[dict]:
    """对一组用户记录批量过滤豁免名单。

    Args:
        users: 用户记录迭代器，每条记录至少含 `email_field` 字段
        email_field: 邮箱字段名，默认 'email'

    Returns:
        非豁免用户列表（保持原顺序）
    """
    result = []
    for u in users:
        email = u.get(email_field) if isinstance(u, dict) else None
        if not is_exempt(email):
            result.append(u)
    return result


def assert_exemption_invariant() -> None:
    """L3 运行时断言：jiaoyanchen 必须永远在豁免名单中。

    这是物理熔断，任何代码 / 配置变更若导致 jiaoyanchen 被剔除，将立即 raise。
    """
    canary = "jiaoyanchen@bytedance.com"
    if not is_exempt(canary):
        raise RuntimeError(
            f"[CRITICAL] 豁免名单契约被破坏：{canary} 不在 EXEMPT_EMAILS 中。"
            f"请检查 exemption_filter.EXEMPT_EMAILS 是否被错误修改。"
        )


if __name__ == "__main__":
    # 自检入口：python3 scripts/exemption_filter.py
    assert_exemption_invariant()
    print("[OK] 豁免名单契约校验通过：jiaoyanchen 已正确豁免。")
    print(f"[INFO] 当前豁免名单 ({len(EXEMPT_EMAILS)} 人): {sorted(EXEMPT_EMAILS)}")
