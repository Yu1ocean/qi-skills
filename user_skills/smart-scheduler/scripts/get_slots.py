import datetime
from suggest_timeslots import classify_timeslots, build_default_candidate_windows, build_option_string
import json

# Define dates to check
dates = [datetime.date(2026, 4, 30)]

# Generate candidate windows for BJT (10:00-19:00 default)
# P0: 未实拿到对方时区时，允许在此处显式传 None，以触发权威熔断报错。
candidate_windows = build_default_candidate_windows(dates=dates, counterpart_tz=None)

def parse_iso_time(t_str):
    return datetime.datetime.fromisoformat(t_str)

# Busy map parsing from API result
busy_map = {
    "yuqinan": [],
    "liuxiaolong.vito": [],
    "xiachunyu": []
}

# Add events for yuqinan
events_yuqinan = [
    {"start_time": "2026-04-30T17:00:00+08:00", "end_time": "2026-04-30T17:30:00+08:00"},
    {"start_time": "2026-04-30T13:30:00+08:00", "end_time": "2026-04-30T14:00:00+08:00"},
    {"start_time": "2026-04-30T09:00:00+08:00", "end_time": "2026-04-30T09:30:00+08:00"},
    {"start_time": "2026-04-30T11:00:00+08:00", "end_time": "2026-04-30T12:00:00+08:00"},
    {"start_time": "2026-04-30T17:00:00+08:00", "end_time": "2026-04-30T17:30:00+08:00"},
    {"start_time": "2026-04-30T07:00:00+08:00", "end_time": "2026-04-30T08:00:00+08:00"},
    {"start_time": "2026-04-30T16:00:00+08:00", "end_time": "2026-04-30T16:30:00+08:00"},
    {"start_time": "2026-04-30T10:30:00+08:00", "end_time": "2026-04-30T12:00:00+08:00"},
    {"start_time": "2026-04-30T02:00:00+08:00", "end_time": "2026-04-30T03:00:00+08:00"},
    {"start_time": "2026-04-30T15:00:00+08:00", "end_time": "2026-04-30T16:00:00+08:00"},
    {"start_time": "2026-04-30T14:30:00+08:00", "end_time": "2026-04-30T16:00:00+08:00"},
    {"start_time": "2026-04-30T13:30:00+08:00", "end_time": "2026-04-30T14:30:00+08:00"}
]
for e in events_yuqinan:
    busy_map["yuqinan"].append((parse_iso_time(e["start_time"]), parse_iso_time(e["end_time"])))

# Add events for liuxiaolong.vito (ou_d9ea1d62e1886a8e65e3f86cd9f7b326)
events_vito = [
    {"start_time": "2026-04-30T21:00:00+08:00", "end_time": "2026-04-30T22:00:00+08:00"},
    {"start_time": "2026-04-30T22:30:00+08:00", "end_time": "2026-04-30T23:00:00+08:00"},
    {"start_time": "2026-04-30T22:30:00+08:00", "end_time": "2026-04-30T23:00:00+08:00"},
    {"start_time": "2026-04-30T23:00:00+08:00", "end_time": "2026-04-30T23:30:00+08:00"},
    {"start_time": "2026-04-30T10:30:00+08:00", "end_time": "2026-04-30T12:00:00+08:00"},
    {"start_time": "2026-04-30T20:30:00+08:00", "end_time": "2026-04-30T21:00:00+08:00"},
    {"start_time": "2026-04-30T19:00:00+08:00", "end_time": "2026-04-30T20:00:00+08:00"},
    {"start_time": "2026-04-30T15:30:00+08:00", "end_time": "2026-04-30T16:00:00+08:00"},
    {"start_time": "2026-04-30T20:00:00+08:00", "end_time": "2026-04-30T21:00:00+08:00"},
    {"start_time": "2026-04-30T20:30:00+08:00", "end_time": "2026-04-30T21:30:00+08:00"},
    {"start_time": "2026-04-30T12:00:00+08:00", "end_time": "2026-04-30T13:30:00+08:00"},
    {"start_time": "2026-04-30T18:00:00+08:00", "end_time": "2026-04-30T19:00:00+08:00"},
    {"start_time": "2026-04-30T16:00:00+08:00", "end_time": "2026-04-30T16:30:00+08:00"},
    {"start_time": "2026-04-30T00:30:00+08:00", "end_time": "2026-04-30T01:30:00+08:00"},
    {"start_time": "2026-04-30T09:45:00+08:00", "end_time": "2026-04-30T10:15:00+08:00"},
    {"start_time": "2026-04-30T17:00:00+08:00", "end_time": "2026-04-30T17:30:00+08:00"},
    {"start_time": "2026-04-30T14:30:00+08:00", "end_time": "2026-04-30T16:00:00+08:00"},
    {"start_time": "2026-04-30T13:30:00+08:00", "end_time": "2026-04-30T14:30:00+08:00"},
    {"start_time": "2026-04-30T08:45:00+08:00", "end_time": "2026-04-30T09:45:00+08:00"},
    {"start_time": "2026-04-30T14:45:00+08:00", "end_time": "2026-04-30T15:15:00+08:00"}
]
for e in events_vito:
    busy_map["liuxiaolong.vito"].append((parse_iso_time(e["start_time"]), parse_iso_time(e["end_time"])))

# Add events for xiachunyu (ou_6c70ae770e15cbea5f29d590de12b26d)
events_xia = [
    {"start_time": "2026-04-30T19:00:00+08:00", "end_time": "2026-04-30T20:00:00+08:00"},
    {"start_time": "2026-04-30T16:30:00+08:00", "end_time": "2026-04-30T17:00:00+08:00"},
    {"start_time": "2026-04-30T07:58:00+08:00", "end_time": "2026-04-30T08:22:00+08:00"},
    {"start_time": "2026-04-30T15:42:00+08:00", "end_time": "2026-04-30T17:02:00+08:00"},
    {"start_time": "2026-04-30T17:00:00+08:00", "end_time": "2026-04-30T17:30:00+08:00"},
    {"start_time": "2026-04-30T16:00:00+08:00", "end_time": "2026-04-30T16:30:00+08:00"}
]
for e in events_xia:
    busy_map["xiachunyu"].append((parse_iso_time(e["start_time"]), parse_iso_time(e["end_time"])))

res = classify_timeslots(candidate_windows, 30, busy_map, {}, preemption_enabled=True, preemption_sensitivity=1.0)

print("=== ABSOLUTE FREE ===")
for i, s in enumerate(res["absolute_free"], 1):
    opt = build_option_string(i, s["start"], s["end"], coverage=1.0)
    print(f"Option: {opt}")

print("\n=== PREEMPTABLE ===")
for i, s in enumerate(res["preemptable"], len(res["absolute_free"]) + 1):
    coverage = 1.0 - (len(s["preemption_targets"]) / len(busy_map))
    opt = build_option_string(i, s["start"], s["end"], coverage=coverage, note="可抢占")
    print(f"Option: {opt}")
