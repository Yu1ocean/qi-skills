"""测试豁免名单代码层硬过滤。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from exemption_filter import (  # noqa: E402
    EXEMPT_EMAILS,
    is_exempt,
    filter_pending,
    assert_exemption_invariant,
)


def test_jiaoyanchen_must_be_exempt():
    """焦彦晨 永久豁免 — 这是业务方决议的强契约。"""
    assert is_exempt("jiaoyanchen@bytedance.com") is True


def test_jiaoyanchen_in_constant():
    assert "jiaoyanchen@bytedance.com" in EXEMPT_EMAILS


def test_cherry_gao_must_be_exempt():
    """Cherry Gao 豁免 — 业务方决议。"""
    assert is_exempt("gaochuan.cherry@bytedance.com") is True


def test_wang_haotian_must_be_exempt():
    """王皓田 豁免 — 业务方决议。"""
    assert is_exempt("wanghaotian.666@bytedance.com") is True


def test_huangyizhuo_amy_must_be_exempt():
    """黄忆卓 Amy 豁免 — 业务方决议。"""
    assert is_exempt("huangyizhuo.1992@bytedance.com") is True


def test_xinyi_zhan_must_be_exempt():
    """詹欣意 豁免 — 业务方决议。"""
    assert is_exempt("zhanxinyi.0729@bytedance.com") is True


def test_others_not_exempt():
    assert is_exempt("zhangsan@example.com") is False
    assert is_exempt("lisi@bytedance.com") is False


def test_case_insensitive():
    assert is_exempt("JIAOYANCHEN@bytedance.com") is True
    assert is_exempt("Jiaoyanchen@bytedance.COM") is True
    assert is_exempt("HUANGYIZHUO.1992@BYTEDANCE.COM") is True


def test_strip_whitespace():
    assert is_exempt("  jiaoyanchen@bytedance.com  ") is True


def test_none_or_empty_not_exempt():
    """空值默认非豁免（即应被巡检到）— 防止漏过滤。"""
    assert is_exempt(None) is False
    assert is_exempt("") is False


def test_filter_pending_removes_exempt():
    users = [
        {"name": "张三", "email": "zhangsan@example.com"},
        {"name": "焦彦晨", "email": "jiaoyanchen@bytedance.com"},
        {"name": "黄忆卓Amy", "email": "huangyizhuo.1992@bytedance.com"},
        {"name": "詹欣意", "email": "zhanxinyi.0729@bytedance.com"},
        {"name": "李四", "email": "lisi@example.com"},
    ]
    result = filter_pending(users)
    assert len(result) == 2
    assert all(
        u["email"] not in {"jiaoyanchen@bytedance.com", "huangyizhuo.1992@bytedance.com", "zhanxinyi.0729@bytedance.com"}
        for u in result
    )
    # 顺序保留
    assert [u["name"] for u in result] == ["张三", "李四"]


def test_assert_invariant_passes():
    """L3 物理熔断在正常情况下不应 raise。"""
    assert_exemption_invariant()  # 不应抛异常


if __name__ == "__main__":
    # 简易自跑（无 pytest 依赖）
    import inspect
    funcs = [f for n, f in globals().items() if n.startswith("test_") and callable(f)]
    failed = 0
    for f in funcs:
        try:
            f()
            print(f"  ✅ {f.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ❌ {f.__name__}  {e}")
        except Exception as e:
            failed += 1
            print(f"  💥 {f.__name__}  {type(e).__name__}: {e}")
    print(f"\n{len(funcs) - failed}/{len(funcs)} passed")
    sys.exit(0 if failed == 0 else 1)
