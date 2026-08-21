#!/usr/bin/env python3
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, List, Set, Tuple

SPREADSHEET_TOKEN = "KF9Wsp1WZhviWZtrndXcqD0tnmp"
SHEET_ID = "1ixXmX"
HEADER = [
    "log_id",
    "name",
    "departure_city",
    "destination_city",
    "departure_time",
    "return_time",
    "booking_time",
    "approval_time",
    "reason",
    "source_channel",
    "booking_lead_days",
    "is_booked_before_approval",
    "is_over_cabin_policy",
    "is_hotel_over_policy",
    "duplicate_booking_flag",
    "is_first_time_destination",
    "over_policy_reason",
    "hotel_total_amount",
    "hotel_standard_amount",
    "seat_class",
    "cabin_class",
    "source_subject",
    "source_message_id",
    "source_sent_at",
]


def run(cmd: List[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result.stdout


def parse_cli_json(raw: str) -> Any:
    lines = []
    for line in raw.splitlines():
        if line.startswith("[Metrics"):
            continue
        if "proxy detected" in line:
            continue
        if "command started:" in line or "command finished:" in line:
            continue
        if line.startswith("\x1b"):
            continue
        lines.append(line)
    text = "\n".join(lines).strip()
    start_obj = text.find("{")
    start_arr = text.find("[")
    starts = [idx for idx in [start_obj, start_arr] if idx >= 0]
    if starts:
        text = text[min(starts):]
    return json.loads(text)


def normalize_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else text


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_name(value: Any) -> str:
    text = normalize_text(value)
    return text.replace("徵", "徽")


def normalize_bool(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return "TRUE"
    if text in {"false", "0", "no"}:
        return "FALSE"
    return ""


def normalize_number(value: Any) -> Any:
    if value is None or value == "":
        return ""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if abs(value - int(value)) < 1e-9 else round(value, 1)
    text = str(value).strip()
    if not text:
        return ""
    try:
        num = float(text)
        return int(num) if abs(num - int(num)) < 1e-9 else round(num, 1)
    except Exception:
        return text


def build_rows(trips: List[dict], start_index: int) -> List[List[Any]]:
    rows = []
    prefix = time.strftime("TRV_%y%m%d_")
    for idx, trip in enumerate(trips, start=start_index):
        row = [
            f"{prefix}{idx:04d}",
            trip.get("name") or "",
            trip.get("departure_city") or "",
            trip.get("destination_city") or "",
            normalize_date(trip.get("departure_time")),
            normalize_date(trip.get("return_time")),
            normalize_date(trip.get("booking_time")),
            normalize_date(trip.get("approval_time")),
            "",
            trip.get("source_channel") or "",
            normalize_number(trip.get("booking_lead_days")),
            normalize_bool(trip.get("is_booked_before_approval")),
            normalize_bool(trip.get("is_over_cabin_policy")),
            normalize_bool(trip.get("is_hotel_over_policy")),
            normalize_bool(trip.get("duplicate_booking_flag")),
            normalize_bool(trip.get("is_first_time_destination")),
            trip.get("over_policy_reason") or "",
            normalize_number(trip.get("hotel_total_amount")),
            normalize_number(trip.get("hotel_standard_amount")),
            trip.get("seat_class") or "",
            trip.get("cabin_class") or "",
            trip.get("source_subject") or "",
            trip.get("source_message_id") or "",
            normalize_date(trip.get("source_sent_at")),
        ]
        rows.append(row)
    return rows


def fetch_existing_sheet_rows() -> List[List[Any]]:
    raw = run([
        "lark-cli", "sheets", "+read",
        "--spreadsheet-token", SPREADSHEET_TOKEN,
        "--sheet-id", SHEET_ID,
        "--range", "A1:X5000",
        "--value-render-option", "ToString",
    ])
    payload = parse_cli_json(raw)
    return payload.get("data", {}).get("valueRange", {}).get("values", [])


def build_business_key(*, name: Any, departure_city: Any, destination_city: Any, departure_time: Any, return_time: Any, booking_time: Any, source_subject: Any = "") -> Tuple[str, ...]:
    return (
        normalize_name(name),
        normalize_text(departure_city),
        normalize_text(destination_city),
        normalize_date(departure_time),
        normalize_date(return_time),
        normalize_date(booking_time),
        normalize_text(source_subject),
    )


def extract_existing_indexes(rows: List[List[Any]]) -> Tuple[Set[str], Set[Tuple[str, ...]]]:
    source_ids: Set[str] = set()
    business_keys: Set[Tuple[str, ...]] = set()
    for row in rows[1:]:
        if not row or not any(cell not in (None, "") for cell in row):
            continue
        if len(row) > 22 and normalize_text(row[22]):
            source_ids.add(normalize_text(row[22]))
        business_keys.add(build_business_key(
            name=row[1] if len(row) > 1 else "",
            departure_city=row[2] if len(row) > 2 else "",
            destination_city=row[3] if len(row) > 3 else "",
            departure_time=row[4] if len(row) > 4 else "",
            return_time=row[5] if len(row) > 5 else "",
            booking_time=row[6] if len(row) > 6 else "",
            source_subject=row[21] if len(row) > 21 else "",
        ))
    return source_ids, business_keys


def fetch_existing_log_ids() -> List[str]:
    values = fetch_existing_sheet_rows()
    return [str(row[0]).strip() for row in values if row and row[0]]


def canonicalize_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    upper = text.upper()
    if upper in {"TRUE", "FALSE"}:
        return upper
    try:
        num = float(text)
        if abs(num - int(num)) < 1e-9:
            return str(int(num))
        return str(round(num, 1))
    except Exception:
        return text


def expected_for_compare(row: List[Any]) -> List[str]:
    result = [canonicalize_cell(item) for item in row]
    while result and result[-1] == "":
        result.pop()
    return result


def actual_for_compare(values: List[Any]) -> List[str]:
    result = [canonicalize_cell(item) for item in values]
    while result and result[-1] == "":
        result.pop()
    return result


def append_and_verify(row: List[Any]) -> dict:
    append_raw = run([
        "lark-cli", "sheets", "+append",
        "--spreadsheet-token", SPREADSHEET_TOKEN,
        "--sheet-id", SHEET_ID,
        "--range", "A1:X1",
        "--values", json.dumps([row], ensure_ascii=False),
    ])
    append_payload = parse_cli_json(append_raw)
    updated_range = (
        append_payload.get("data", {}).get("updated_range")
        or append_payload.get("updated_range")
        or append_payload.get("data", {}).get("updates", {}).get("updatedRange")
    )
    if not updated_range:
        raise RuntimeError(f"append succeeded but updated_range missing: {append_raw}")
    time.sleep(2)
    read_raw = run([
        "lark-cli", "sheets", "+read",
        "--spreadsheet-token", SPREADSHEET_TOKEN,
        "--range", updated_range,
        "--value-render-option", "ToString",
    ])
    read_payload = parse_cli_json(read_raw)
    values = read_payload.get("data", {}).get("valueRange", {}).get("values", [])
    actual_row = actual_for_compare(values[0] if values else [])
    expected_row = expected_for_compare(row)
    if actual_row != expected_row:
        raise RuntimeError(
            "RAW readback mismatch\n"
            f"updated_range={updated_range}\n"
            f"expected={expected_row}\n"
            f"actual={actual_row}"
        )
    return {
        "updated_range": updated_range,
        "raw_readback": values[0] if values else [],
        "log_id": row[0],
        "source_message_id": row[22],
    }


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: travel_backfill_write_sheet.py <travel_dashboard.json> <audit_output.json>")
    json_path = Path(sys.argv[1])
    audit_output = Path(sys.argv[2])
    data = json.loads(json_path.read_text(encoding="utf-8"))
    trips = data.get("trips", [])
    existing_rows = fetch_existing_sheet_rows()
    existing_log_ids = [str(row[0]).strip() for row in existing_rows if row and row[0]]
    existing_source_ids, existing_business_keys = extract_existing_indexes(existing_rows)
    start_index = len(existing_log_ids) + 1

    pending_trips = []
    skipped_duplicates = []
    staged_source_ids = set(existing_source_ids)
    staged_business_keys = set(existing_business_keys)
    for trip in trips:
        source_id = normalize_text(trip.get("source_message_id"))
        business_key = build_business_key(
            name=trip.get("name"),
            departure_city=trip.get("departure_city"),
            destination_city=trip.get("destination_city"),
            departure_time=trip.get("departure_time"),
            return_time=trip.get("return_time"),
            booking_time=trip.get("booking_time"),
            source_subject=trip.get("source_subject") or "",
        )
        duplicate_reason = None
        if source_id and source_id in staged_source_ids:
            duplicate_reason = "source_message_id"
        elif business_key in staged_business_keys:
            duplicate_reason = "business_key"
        if duplicate_reason:
            skipped_duplicates.append({
                "duplicate_reason": duplicate_reason,
                "source_message_id": source_id,
                "business_key": list(business_key),
                "name": trip.get("name") or "",
                "departure_city": trip.get("departure_city") or "",
                "destination_city": trip.get("destination_city") or "",
                "departure_time": normalize_date(trip.get("departure_time")),
            })
            continue
        pending_trips.append(trip)
        if source_id:
            staged_source_ids.add(source_id)
        staged_business_keys.add(business_key)

    rows = build_rows(pending_trips, start_index=start_index)
    results = []
    for row in rows:
        results.append(append_and_verify(row))
    audit_output.parent.mkdir(parents=True, exist_ok=True)
    audit_output.write_text(
        json.dumps(
            {
                "header": HEADER,
                "input_trip_count": len(trips),
                "row_count": len(rows),
                "rows_written": rows,
                "skipped_duplicates": skipped_duplicates,
                "verification": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "row_count": len(rows), "skipped_duplicate_count": len(skipped_duplicates), "audit_output": str(audit_output.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
