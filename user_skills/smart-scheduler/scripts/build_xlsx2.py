import datetime
from build_availability_xlsx import build_availability_xlsx

# Build the data
candidate_windows = [
    (
        datetime.datetime(2026, 4, 30, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8))),
        datetime.datetime(2026, 4, 30, 19, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8))),
    )
]

def parse_iso_time(t_str):
    return datetime.datetime.fromisoformat(t_str)

busy_map = {
    "yuqinan": [],
    "liuxiaolong.vito": [],
    "xiachunyu": []
}

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


from suggest_timeslots import suggest_timeslots
top_slots = suggest_timeslots(candidate_windows, 30, busy_map)

build_availability_xlsx(top_slots, list(busy_map.keys()), busy_map, "availability.xlsx")
