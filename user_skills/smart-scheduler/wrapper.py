import datetime
from scripts.suggest_timeslots import classify_timeslots, parse_time

candidate_windows = [(
    datetime.datetime.fromisoformat("2026-04-29T01:00:00+08:00").replace(tzinfo=None),
    datetime.datetime.fromisoformat("2026-04-29T07:00:00+08:00").replace(tzinfo=None)
)]

busy_map = {
    "Kay": [
        (datetime.datetime.fromisoformat("2026-04-29T04:00:00").replace(tzinfo=None), datetime.datetime.fromisoformat("2026-04-29T04:30:00").replace(tzinfo=None)),
        (datetime.datetime.fromisoformat("2026-04-29T05:30:00").replace(tzinfo=None), datetime.datetime.fromisoformat("2026-04-29T06:00:00").replace(tzinfo=None)),
        (datetime.datetime.fromisoformat("2026-04-29T00:30:00").replace(tzinfo=None), datetime.datetime.fromisoformat("2026-04-29T01:15:00").replace(tzinfo=None))
    ],
    "Yu Qinan": []
}

res = classify_timeslots(candidate_windows, 30, busy_map, {}, preemption_enabled=False)
for slot in res["absolute_free"][:3]:
    print(slot["start"], slot["end"])
