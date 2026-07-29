"""测试 patrol.py 的真实发送门禁、周度幂等锁与卡片渲染。"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from patrol import (  # noqa: E402
    _already_booked_this_week,
    _require_real_send_confirmation,
    build_l0_card,
)


CST = timezone(timedelta(hours=8))


def test_weekly_idempotency_lock_hits_same_email():
    week_log = {
        "week": "2026-W24",
        "mode_b_bookings": [
            {
                "name": "张三",
                "email": "zhangsan@example.com",
                "event_id": "evt_1",
            }
        ],
    }
    user = {"name": "张三", "email": "zhangsan@example.com"}
    hit = _already_booked_this_week(week_log, user)
    assert hit is not None
    assert hit["event_id"] == "evt_1"


def test_require_real_send_confirmation_blocks_without_flag():
    try:
        _require_real_send_confirmation(False, "B")
    except RuntimeError as exc:
        assert "--confirm-real-send" in str(exc)
    else:
        raise AssertionError("expected RuntimeError when confirm flag missing")


def test_build_l0_card_binds_user_name_with_slot_label():
    plan = {
        "week": "2026-W24",
        "pending_users": [],
        "scheduled": [
            {
                "user": {"name": "张三"},
                "reserved_slot": {
                    "start_time": datetime(2026, 6, 8, 18, 0, tzinfo=CST).isoformat(),
                    "end_time": datetime(2026, 6, 8, 18, 15, tzinfo=CST).isoformat(),
                },
                "event_result": {},
            }
        ],
        "unresolvable": [],
    }
    card = build_l0_card(plan)
    texts = [
        element.get("text", {}).get("content", "")
        for element in card["dsl"]["body"]["elements"]
        if element.get("text")
    ]
    merged = "\n".join(texts)
    assert "张三：" in merged
    assert "18:00" in merged and "18:15" in merged


if __name__ == "__main__":
    test_weekly_idempotency_lock_hits_same_email()
    test_require_real_send_confirmation_blocks_without_flag()
    test_build_l0_card_binds_user_name_with_slot_label()
    print("3/3 passed")
