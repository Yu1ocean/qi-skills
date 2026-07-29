import datetime
from suggest_timeslots import classify_timeslots, parse_time

w1 = (parse_time("2026-04-28 08:00"), parse_time("2026-04-28 10:00"))
w2 = (parse_time("2026-04-29 08:00"), parse_time("2026-04-29 10:00"))

busy_map = {
    "yuqinan": [],
    "kayqi": [
        (parse_time("2026-04-28 08:30"), parse_time("2026-04-28 09:15")),
        (parse_time("2026-04-28 09:00"), parse_time("2026-04-28 09:30")),
        (parse_time("2026-04-28 09:30"), parse_time("2026-04-28 10:00")),
        (parse_time("2026-04-29 08:30"), parse_time("2026-04-29 09:30")),
        (parse_time("2026-04-29 09:30"), parse_time("2026-04-29 11:00")),
    ]
}

res = classify_timeslots([w1, w2], 30, busy_map, {}, preemption_enabled=True, preemption_sensitivity=1.0)

for s in res["absolute_free"]:
    print(s["start"], s["end"])
