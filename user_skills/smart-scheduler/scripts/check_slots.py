
import datetime
import json
from scripts.suggest_timeslots import classify_timeslots, parse_time

def run():
    # Candidates: 17:30 - 18:00 (within 16:51-18:00)
    # And 20:00 - 23:59
    windows = [
        (datetime.datetime(2026, 4, 27, 16, 52), datetime.datetime(2026, 4, 27, 18, 0)),
        (datetime.datetime(2026, 4, 27, 20, 0), datetime.datetime(2026, 4, 27, 23, 59))
    ]
    
    # Busy items from tool output
    # Note: 11:20-22:22 is the train ticket
    busy_items = [
        (datetime.datetime(2026, 4, 27, 16, 0), datetime.datetime(2026, 4, 27, 16, 30)),
        (datetime.datetime(2026, 4, 27, 16, 30), datetime.datetime(2026, 4, 27, 17, 0)),
        (datetime.datetime(2026, 4, 27, 17, 0), datetime.datetime(2026, 4, 27, 17, 30)),
        (datetime.datetime(2026, 4, 27, 18, 0), datetime.datetime(2026, 4, 27, 18, 30)),
        (datetime.datetime(2026, 4, 27, 11, 20), datetime.datetime(2026, 4, 27, 22, 22)),
    ]
    
    # We treat the train ticket as "tentative" or "preemptable" for the sake of the user's request?
    # No, the tool says it's "confirmed" and "busy". 
    # But let's see what classify_timeslots says if we put the train ticket in tentative_map.
    
    hard_busy = [
        (datetime.datetime(2026, 4, 27, 16, 0), datetime.datetime(2026, 4, 27, 16, 30)),
        (datetime.datetime(2026, 4, 27, 16, 30), datetime.datetime(2026, 4, 27, 17, 0)),
        (datetime.datetime(2026, 4, 27, 17, 0), datetime.datetime(2026, 4, 27, 17, 30)),
        (datetime.datetime(2026, 4, 27, 18, 0), datetime.datetime(2026, 4, 27, 18, 30)),
    ]
    
    tentative = [
        {
            "start": datetime.datetime(2026, 4, 27, 11, 20),
            "end": datetime.datetime(2026, 4, 27, 22, 22),
            "title": "Train Ticket D2283",
            "weight": 0.5 # Give it lower weight since it's just travel
        }
    ]
    
    busy_map = {
        "Yu Qinan": hard_busy,
        "Huang Yizhuo": hard_busy
    }
    
    tentative_map = {
        "Yu Qinan": tentative,
        "Huang Yizhuo": tentative
    }
    
    result = classify_timeslots(windows, 20, busy_map, tentative_map, preemption_sensitivity=1.0)
    
    # Format output for easier reading
    output = {
        "absolute_free": [],
        "preemptable": []
    }
    
    for s in result["absolute_free"]:
        output["absolute_free"].append({"start": s["start"].strftime("%H:%M"), "end": s["end"].strftime("%H:%M")})
        
    for s in result["preemptable"]:
        output["preemptable"].append({
            "start": s["start"].strftime("%H:%M"), 
            "end": s["end"].strftime("%H:%M"),
            "weight": s["total_conflict_weight"]
        })
        
    print(json.dumps(output, indent=2))

if __name__ == "__main__":
    run()
