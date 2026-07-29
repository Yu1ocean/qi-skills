#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

SHEET_URL = "https://bytedance.larkoffice.com/sheets/KF9Wsp1WZhviWZtrndXcqD0tnmp?sheet=1ixXmX"
SHEET_ID = "1ixXmX"
READ_RANGE = "A1:X400"
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
PLACEHOLDER_NAME_MAP = {
    "yuqinan@bytedance.com": "于奇楠",
}
LOG_ID_RE = re.compile(r"TRV_(\d{6})_(\d{4})$")


def run(cmd: List[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return proc.stdout


def parse_lark_json(text: str) -> Dict[str, Any]:
    start = text.find("{")
    if start < 0:
        raise ValueError(f"No JSON object found in output: {text[:200]}")
    return json.loads(text[start:])


def read_sheet(sheet_url: str, sheet_id: str) -> List[List[Any]]:
    output = run([
        "lark-cli", "sheets", "+read",
        "--url", sheet_url,
        "--sheet-id", sheet_id,
        "--range", READ_RANGE,
        "--format", "json",
    ])
    data = parse_lark_json(output)
    return data["data"]["valueRange"]["values"]


def write_row(sheet_url: str, sheet_id: str, row_index: int, values: List[Any]) -> Dict[str, Any]:
    output = run([
        "lark-cli", "sheets", "+write",
        "--url", sheet_url,
        "--sheet-id", sheet_id,
        "--range", f"A{row_index}:X{row_index}",
        "--values", json.dumps([values], ensure_ascii=False),
        "--format", "json",
    ])
    return parse_lark_json(output)


def write_cell(sheet_url: str, sheet_id: str, cell: str, value: Any) -> Dict[str, Any]:
    output = run([
        "lark-cli", "sheets", "+write",
        "--url", sheet_url,
        "--sheet-id", sheet_id,
        "--range", cell,
        "--values", json.dumps([[value]], ensure_ascii=False),
        "--format", "json",
    ])
    return parse_lark_json(output)


def normalize_cell_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return value


def normalize_nullable_marker(value: Any) -> Any:
    if value is None:
        return "None"
    return value


def trip_to_row(trip: Dict[str, Any], log_id: str) -> List[Any]:
    return [
        log_id,
        trip.get("name") or "",
        trip.get("departure_city") or "",
        trip.get("destination_city") or "",
        trip.get("departure_time") or "",
        trip.get("return_time") or "",
        trip.get("booking_time") or "",
        trip.get("approval_time") or "",
        "BOOKING_NOTICE_UNDISCLOSED",
        trip.get("source_channel") or "",
        trip.get("booking_lead_days") if trip.get("booking_lead_days") is not None else "",
        normalize_nullable_marker(trip.get("is_booked_before_approval")),
        normalize_nullable_marker(trip.get("is_over_cabin_policy")),
        normalize_nullable_marker(trip.get("is_hotel_over_policy")),
        bool(trip.get("duplicate_booking_flag")) if trip.get("duplicate_booking_flag") is not None else False,
        bool(trip.get("is_first_time_destination")) if trip.get("is_first_time_destination") is not None else False,
        trip.get("over_policy_reason") or "",
        trip.get("hotel_total_amount") if trip.get("hotel_total_amount") is not None else "",
        trip.get("hotel_standard_amount") if trip.get("hotel_standard_amount") is not None else "",
        trip.get("seat_class") or "",
        trip.get("cabin_class") or "",
        trip.get("source_subject") or "",
        trip.get("source_message_id") or "",
        trip.get("source_sent_at") or "",
    ]


def get_existing_rows(values: List[List[Any]]) -> List[Tuple[int, List[Any]]]:
    rows: List[Tuple[int, List[Any]]] = []
    for idx, row in enumerate(values[1:], start=2):
        padded = (row + [""] * len(HEADER))[: len(HEADER)]
        if any(cell not in (None, "") for cell in padded):
            rows.append((idx, padded))
    return rows


def get_next_seq(existing_rows: List[Tuple[int, List[Any]]]) -> int:
    max_seq = 0
    for _, row in existing_rows:
        match = LOG_ID_RE.match(str(row[0]))
        if match:
            max_seq = max(max_seq, int(match.group(2)))
    return max_seq + 1


def build_log_id(source_sent_at: str, seq: int) -> str:
    digits = re.sub(r"[^0-9]", "", source_sent_at or "")
    if len(digits) >= 8:
        day = digits[2:8]
    else:
        day = "000000"
    return f"TRV_{day}_{seq:04d}"


def collect_missing_trips(prod: Dict[str, Any], existing_rows: List[Tuple[int, List[Any]]]) -> List[Dict[str, Any]]:
    existing_msgs = {str(row[22]) for _, row in existing_rows if str(row[22])}
    missing: List[Dict[str, Any]] = []
    for trip in prod.get("trips") or []:
        msg = str(trip.get("source_message_id") or "")
        if not msg or msg in existing_msgs:
            continue
        missing.append(trip)
    missing.sort(key=lambda item: ((item.get("source_sent_at") or ""), (item.get("departure_time") or ""), (item.get("name") or ""), (item.get("source_message_id") or "")))
    return missing


def collect_name_placeholder_updates(existing_rows: List[Tuple[int, List[Any]]]) -> List[Tuple[str, Any]]:
    updates: List[Tuple[str, Any]] = []
    for row_idx, row in existing_rows:
        current_name = str(row[1] or "")
        if current_name in PLACEHOLDER_NAME_MAP:
            updates.append((f"B{row_idx}", PLACEHOLDER_NAME_MAP[current_name]))
    return updates


def verify_written_rows(values: List[List[Any]], written_rows: Dict[int, List[Any]]) -> Dict[int, Dict[str, Any]]:
    result: Dict[int, Dict[str, Any]] = {}
    for row_idx, expected in written_rows.items():
        if row_idx - 1 < 0 or row_idx - 1 >= len(values):
            result[row_idx] = {"ok": False, "reason": "row_out_of_range", "actual": None}
            continue
        actual = (values[row_idx - 1] + [""] * len(HEADER))[: len(HEADER)]
        result[row_idx] = {
            "ok": actual == expected,
            "actual": actual,
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync travel dashboard trips into Feishu travel log sheet")
    parser.add_argument("--input-json", default="output/travel_dashboard.prod.json")
    parser.add_argument("--sheet-url", default=SHEET_URL)
    parser.add_argument("--sheet-id", default=SHEET_ID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backfill-all-missing", action="store_true")
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args()

    prod = json.loads(Path(args.input_json).read_text())
    sheet_values = read_sheet(args.sheet_url, args.sheet_id)
    if not sheet_values or sheet_values[0][: len(HEADER)] != HEADER:
        raise SystemExit(json.dumps({"ok": False, "error": "sheet header mismatch"}, ensure_ascii=False))

    existing_rows = get_existing_rows(sheet_values)
    placeholder_updates = collect_name_placeholder_updates(existing_rows)
    missing = collect_missing_trips(prod, existing_rows)
    if not args.backfill_all_missing:
        increment_path = Path("output/travel_dashboard.daily_increment.json")
        increment_ids = set()
        if increment_path.exists():
            increment_payload = json.loads(increment_path.read_text())
            increment_ids = {
                str(t.get("source_message_id") or "")
                for t in (increment_payload.get("trips") or [])
                if str(t.get("source_message_id") or "")
            }
        if increment_ids:
            missing = [trip for trip in missing if str(trip.get("source_message_id") or "") in increment_ids]

    next_seq = get_next_seq(existing_rows)
    rows_to_write: List[Tuple[int, List[Any]]] = []
    append_preview: List[Dict[str, Any]] = []
    next_row_index = len(existing_rows) + 2
    for trip in missing:
        log_id = build_log_id(str(trip.get("source_sent_at") or trip.get("departure_time") or ""), next_seq)
        next_seq += 1
        row = [normalize_cell_value(v) for v in trip_to_row(trip, log_id)]
        rows_to_write.append((next_row_index, row))
        next_row_index += 1
        append_preview.append({
            "row_index": rows_to_write[-1][0],
            "log_id": log_id,
            "name": row[1],
            "departure_city": row[2],
            "destination_city": row[3],
            "departure_time": row[4],
            "return_time": row[5],
            "source_message_id": row[22],
        })

    result: Dict[str, Any] = {
        "ok": True,
        "placeholder_name_updates": placeholder_updates,
        "missing_trip_count": len(rows_to_write),
        "append_preview": append_preview,
        "applied": False,
    }

    if args.print_only or not args.apply:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    for cell, value in placeholder_updates:
        write_cell(args.sheet_url, args.sheet_id, cell, value)

    append_result = []
    written_rows: Dict[int, List[Any]] = {}
    if rows_to_write:
        latest_values = read_sheet(args.sheet_url, args.sheet_id)
        for row_index, row in rows_to_write:
            current = []
            if row_index - 1 < len(latest_values):
                current = (latest_values[row_index - 1] + [""] * len(HEADER))[: len(HEADER)]
            if any(cell not in (None, "") for cell in current):
                raise SystemExit(json.dumps({
                    "ok": False,
                    "error": f"target row not empty before write: row {row_index}",
                    "current_row": current,
                }, ensure_ascii=False))
            write_result = write_row(args.sheet_url, args.sheet_id, row_index, row)
            append_result.append({"row_index": row_index, "result": write_result})
            written_rows[row_index] = [normalize_cell_value(v) for v in row]

    time.sleep(3)
    after_values = read_sheet(args.sheet_url, args.sheet_id)
    verified_rows = verify_written_rows(after_values, written_rows)
    verified_placeholder_updates = []
    refreshed_rows = get_existing_rows(after_values)
    refreshed_lookup = {idx: row for idx, row in refreshed_rows}
    for cell, value in placeholder_updates:
        row_idx = int(re.sub(r"[^0-9]", "", cell))
        row = refreshed_lookup.get(row_idx)
        verified_placeholder_updates.append({
            "cell": cell,
            "expected": value,
            "actual": row[1] if row else None,
            "ok": bool(row and row[1] == value),
        })

    result.update({
        "applied": True,
        "append_result": append_result,
        "verified_rows": verified_rows,
        "verified_rows_ok": all(item.get("ok") for item in verified_rows.values()) if verified_rows else True,
        "verified_placeholder_updates": verified_placeholder_updates,
    })
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
