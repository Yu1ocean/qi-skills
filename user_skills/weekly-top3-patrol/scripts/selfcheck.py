"""
selfcheck.py — Weekly Top3 Patrol 三层护栏自检

L1 认知层：检查 SKILL.md 顶部是否含 Common Rationalizations / Red Flags / Verification
L2 默认层：检查关键默认值（豁免名单、CHAT key、dry-run 默认）是否合规
L3 断言层：检查代码层硬过滤是否生效；检查 chat registry 加载是否做了关键字断言

退出码：
  0 — 全部通过
  1 — 任一层失败
"""

from __future__ import annotations
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(HERE))


def check_l1_cognitive() -> tuple[bool, list[str]]:
    """L1 认知层：SKILL.md 顶部三件套"""
    errs = []
    skill_md = SKILL_DIR / "SKILL.md"
    if not skill_md.exists():
        return False, ["SKILL.md 未找到"]
    content = skill_md.read_text(encoding="utf-8")
    for kw in ("Common Rationalizations", "Red Flags", "Verification"):
        if kw not in content:
            errs.append(f"L1 缺少必要小节：{kw}")
    return len(errs) == 0, errs


def check_l2_defaults() -> tuple[bool, list[str]]:
    """L2 默认层：关键默认值合规"""
    errs = []
    from exemption_filter import EXEMPT_EMAILS
    canary = "jiaoyanchen@bytedance.com"
    if canary not in EXEMPT_EMAILS:
        errs.append(f"L2 默认豁免名单缺失：{canary}")

    # CHAT key 默认值
    from chat_registry_loader import load_chat
    try:
        chat = load_chat("task_patrol_broadcast")
        if not chat.get("chat_id", "").startswith("oc_"):
            errs.append("L2 task_patrol_broadcast.chat_id 格式异常")
    except Exception as e:
        errs.append(f"L2 CHAT_REGISTRY 加载失败：{e}")

    return len(errs) == 0, errs


def check_l3_runtime_guards() -> tuple[bool, list[str]]:
    """L3 断言层：运行时硬熔断生效"""
    errs = []

    # 1. 豁免名单 invariant
    from exemption_filter import assert_exemption_invariant, is_exempt
    try:
        assert_exemption_invariant()
    except RuntimeError as e:
        errs.append(f"L3 豁免名单 invariant 失败：{e}")

    if not is_exempt("jiaoyanchen@bytedance.com"):
        errs.append("L3 is_exempt(jiaoyanchen) 应为 True")
    if is_exempt("zhangsan@example.com"):
        errs.append("L3 is_exempt(zhangsan) 应为 False")
    # 大小写不敏感
    if not is_exempt("JIAOYANCHEN@bytedance.com"):
        errs.append("L3 is_exempt 应大小写不敏感")

    # 2. CHAT_REGISTRY 关键字断言（错误的 expected_keywords 必须 raise）
    from chat_registry_loader import load_chat
    try:
        load_chat("task_patrol_broadcast",
                  expected_keywords=["NOT_EXIST_KEYWORD_xxx"])
        errs.append("L3 CHAT_REGISTRY 关键字断言未生效（应 raise）")
    except ValueError:
        pass  # 正确

    # 3. interval_intersect 自检
    from datetime import datetime, timedelta, timezone
    from interval_intersect import find_common_slot
    cst = timezone(timedelta(hours=8))
    ws = datetime(2026, 5, 25, 16, 0, tzinfo=cst)
    we = datetime(2026, 5, 25, 22, 0, tzinfo=cst)
    busy_a = [
        {"start_time": "2026-05-25T16:00:00+08:00",
         "end_time": "2026-05-25T17:00:00+08:00"},
    ]
    busy_b = []
    slot = find_common_slot(busy_a, busy_b, ws, we, 15)
    if slot is None or slot[0] != datetime(2026, 5, 25, 17, 0, tzinfo=cst):
        errs.append(f"L3 interval_intersect 自检失败：slot={slot}")

    return len(errs) == 0, errs


def main() -> int:
    print("=" * 60)
    print("Weekly Top3 Patrol — Three-Layer Guardrail Selfcheck")
    print("=" * 60)

    all_ok = True
    for name, fn in [
        ("L1 (认知层)", check_l1_cognitive),
        ("L2 (默认层)", check_l2_defaults),
        ("L3 (断言层)", check_l3_runtime_guards),
    ]:
        ok, errs = fn()
        if ok:
            print(f"  ✅ {name}  PASS")
        else:
            all_ok = False
            print(f"  ❌ {name}  FAIL")
            for e in errs:
                print(f"     - {e}")

    print("=" * 60)
    if all_ok:
        print("✅ ALL GUARDRAILS PASS — Skill ready for forge & deploy.")
        return 0
    else:
        print("❌ FAILED — 请修复后再发布。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
