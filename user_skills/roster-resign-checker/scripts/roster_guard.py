#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Roster Resign Checker — L3 运行时物理护栏 (Runtime Guardrails)

本脚本把 SKILL.md 里的红线固化成"副作用发生前必须通过"的物理断言：

1. **禁止删除红线**：本技能只读 + 通知，绝不执行任何删除。任何被判定为
   删除类的动作（delete/remove/清空/移除成员等）都会被 `assert` + `raise`
   物理熔断，防止技能越权。
2. **私信不发群聊红线**：通知只允许走 P2P 私信；一旦目标是群聊(chat/group)
   立即熔断。
3. **疑似离职判定器**：把"在职/疑似离职/需人工确认"的判定逻辑固化成可复用
   的纯函数，避免 Agent 每次凭感觉判断导致误删风险。

用法（供技能执行时按需调用）：

    python3 scripts/roster_guard.py --self-test
    python3 scripts/roster_guard.py --assert-action notify_p2p --notify-target ou_xxx
    python3 scripts/roster_guard.py --classify '{"email":"a@b.com","department":"BD","is_activated":true}'
"""
from __future__ import annotations

import argparse
import json
import sys


class RosterGuardViolation(RuntimeError):
    """L3 物理熔断异常：任何越权/违规动作都以此异常中断流程。"""


# ---- L2 合规默认值 (Defaults) ----
DEFAULT_NOTIFY_USER = "yuqinan"
DEFAULT_ALLOWED_ACTIONS = ("read_sheet", "read_contact", "notify_p2p", "report")
# 删除类动作关键字：只要命中即判定为越权删除，必须熔断
DELETE_ACTION_KEYWORDS = (
    "delete", "remove", "del_", "drop", "clear", "purge",
    "删除", "移除", "清空", "清除", "踢出", "下线成员",
)
# 群聊目标特征：私信通知严禁命中这些前缀/关键字
GROUP_TARGET_MARKERS = ("oc_", "chat", "group", "群", "chat_id")


def _is_delete_action(action: str) -> bool:
    a = (action or "").strip().lower()
    return any(kw in a for kw in DELETE_ACTION_KEYWORDS)


def validate_action_allowed(action: str) -> str:
    """L3 断言：动作必须落在只读+通知白名单内，且绝不能是删除类。

    命中删除关键字 → 立即 raise（这是本技能的最高红线）。
    不在白名单 → 同样 raise，防止技能被误用于越权写操作。
    """
    if _is_delete_action(action):
        raise RosterGuardViolation(
            f"❌ 越权红线：本技能禁止任何删除操作，检测到删除类动作 `{action}`。"
            f"删除必须由主进程在用户明确确认后另行下发。"
        )
    if action not in DEFAULT_ALLOWED_ACTIONS:
        raise RosterGuardViolation(
            f"❌ 动作 `{action}` 不在只读+通知白名单 {DEFAULT_ALLOWED_ACTIONS} 内，已熔断。"
        )
    assert action in DEFAULT_ALLOWED_ACTIONS
    return action


def validate_notify_target_is_p2p(target: str) -> str:
    """L3 断言：通知目标必须是个人（P2P 私信），严禁群聊。"""
    t = (target or "").strip()
    if not t:
        raise RosterGuardViolation("❌ 通知目标为空，无法确认为私信目标，已熔断。")
    low = t.lower()
    if any(m in low for m in GROUP_TARGET_MARKERS):
        raise RosterGuardViolation(
            f"❌ 通知红线：疑似群聊目标 `{target}`，本技能只允许私信个人，已熔断。"
        )
    return t


def classify_member(record: dict) -> dict:
    """把单个成员记录判定为 在职保留 / 疑似离职建议删除 / 无法判断需人工。

    判定规则（与 SKILL.md SOP 完全一致）：
    - 在职：email + department 齐全 且 is_activated=True
    - 疑似离职：email/department/个人档案全空，或 is_activated=False(账号注销)
    - 其余：需人工确认
    """
    email = (record.get("email") or "").strip()
    dept = (record.get("department") or "").strip()
    activated = record.get("is_activated")

    profile_empty = not email and not dept and not (record.get("profile") or "").strip()

    if email and dept and activated is True:
        status, reason = "在职保留", "邮箱+部门齐全且 is_activated=true"
    elif profile_empty or activated is False:
        status, reason = (
            "疑似离职建议删除",
            "邮箱/部门/档案全空" if profile_empty else "账号已注销 is_activated=false",
        )
    else:
        status, reason = "无法判断需人工", "关键字段缺失且无法确认账号状态"

    return {"name": record.get("name", ""), "status": status, "reason": reason}


def _self_test() -> int:
    # 删除动作必须熔断
    for bad in ("delete_member", "remove_row", "清空名单", "踢出成员"):
        try:
            validate_action_allowed(bad)
        except RosterGuardViolation:
            pass
        else:
            raise AssertionError(f"删除动作 {bad} 未被熔断")
    # 白名单动作放行
    assert validate_action_allowed("notify_p2p") == "notify_p2p"
    # 群聊目标必须熔断
    for grp in ("oc_123abc", "chat_id_xxx", "运营群"):
        try:
            validate_notify_target_is_p2p(grp)
        except RosterGuardViolation:
            pass
        else:
            raise AssertionError(f"群聊目标 {grp} 未被熔断")
    # P2P 目标放行
    assert validate_notify_target_is_p2p("ou_realpersonopenid") == "ou_realpersonopenid"
    # 分类器
    assert classify_member({"email": "a@b.com", "department": "BD", "is_activated": True})["status"] == "在职保留"
    assert classify_member({"email": "", "department": "", "is_activated": False})["status"] == "疑似离职建议删除"
    assert classify_member({"email": "a@b.com", "department": "", "is_activated": None})["status"] == "无法判断需人工"
    print("✅ roster_guard self-test PASSED（删除熔断/群聊熔断/分类器 全部通过）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Roster Resign Checker L3 运行时护栏")
    parser.add_argument("--self-test", action="store_true", help="运行内置自检")
    parser.add_argument("--assert-action", help="断言某动作是否被允许（删除类会熔断）")
    parser.add_argument("--notify-target", help="断言通知目标是否为 P2P 私信目标")
    parser.add_argument("--classify", help="传入单条成员 JSON，输出三分类结果")
    args = parser.parse_args()

    if args.self_test:
        return _self_test()

    if args.assert_action:
        validate_action_allowed(args.assert_action)
        if args.notify_target:
            validate_notify_target_is_p2p(args.notify_target)
        print(f"✅ 动作 `{args.assert_action}` 合规放行")
        return 0

    if args.notify_target:
        validate_notify_target_is_p2p(args.notify_target)
        print(f"✅ 通知目标 `{args.notify_target}` 判定为 P2P 私信，合规放行")
        return 0

    if args.classify:
        print(json.dumps(classify_member(json.loads(args.classify)), ensure_ascii=False))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RosterGuardViolation as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
