import sys
import datetime
from suggest_timeslots import (
    suggest_timeslots,
    build_default_candidate_windows,
    parse_time,
    build_option_string
)

user_id = "ou_900ddd9ff611254a74ac32adafc016b4"
cp_id = "ou_f03941220cff5d4c2845bb0ee62c68c5"

# Target date
target_date = datetime.date(2026, 5, 9)

# Busy slots for User (于奇楠)
busy_user = [
    (datetime.datetime(2026, 5, 9, 5, 30), datetime.datetime(2026, 5, 9, 6, 0)),
    (datetime.datetime(2026, 5, 9, 14, 0), datetime.datetime(2026, 5, 9, 15, 0)),
    (datetime.datetime(2026, 5, 9, 17, 0), datetime.datetime(2026, 5, 9, 17, 30)),
]

# Busy slots for CP (Cherry Gao)
busy_cp = [
    (datetime.datetime(2026, 5, 9, 12, 0), datetime.datetime(2026, 5, 9, 12, 45)),
    (datetime.datetime(2026, 5, 9, 18, 40), datetime.datetime(2026, 5, 9, 21, 10)),
]

busy_map = {
    "于奇楠": busy_user,
    "Cherry Gao": busy_cp
}

# Build candidate windows (10:00 - 19:00)
# P0: 对方时区未权威获取时，必须显式传 None 并熔断，禁止默认 fallback。
candidate_windows = build_default_candidate_windows(
    [target_date],
    user_tz="Asia/Shanghai",
    counterpart_tz=None
)

# Find 1-hour slots
print("--- 1 Hour Slots ---")
slots_1h = suggest_timeslots(candidate_windows, 60, busy_map)
for i, s in enumerate(slots_1h, 1):
    opt = build_option_string(i, s[0], s[1], coverage=(1.0 - s[2]/len(busy_map)))
    print(f"Option: {opt}")

# Find 30-min slots
print("\n--- 30 Min Slots ---")
slots_30m = suggest_timeslots(candidate_windows, 30, busy_map)
for i, s in enumerate(slots_30m, 1):
    opt = build_option_string(i, s[0], s[1], coverage=(1.0 - s[2]/len(busy_map)))
    print(f"Option: {opt}")
