#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

DEFAULT_REGISTRY_SPREADSHEET_URL = "https://bytedance.sg.larkoffice.com/sheets/ECQ0sDwmbhDex9tcUSjlkU7Bgdh"
DEFAULT_REGISTRY_SHEET_NAME = "Global_ID_Registry"
DEFAULT_RAW_SLEEP_SECONDS = 2
DEFAULT_MAX_RETRIES = 3
DEFAULT_DLQ_PATH = Path(__file__).resolve().parents[1] / "assets/dlq/global_id_allocator_dlq.jsonl"
DEFAULT_LARK_SHEETS_CLI = Path(__file__).resolve().parents[3] / "inner_skills/lark-sheets/bin/lark-sheets-cli"

CATEGORY_FORMAT_REGISTRY = {
    "DOC": {"date_fmt": "%y%m", "seq_width": 3},
    "BUG": {"date_fmt": "%y%m", "seq_width": 4},
    "WK": {"date_fmt": "%y%m", "seq_width": 2},
    "SYS": {"date_fmt": "%y%m", "seq_width": 3},
    "KNO": {"date_fmt": "%y%m", "seq_width": 3},
}


class GuardrailViolation(RuntimeError):
    pass


def validate_category_registered(category: str) -> bool:
    assert isinstance(category, str) and category, "category must be a non-empty string"
    if category not in CATEGORY_FORMAT_REGISTRY:
        raise ValueError(
            f"[GUARDRAIL-FAIL] Category '{category}' is NOT registered in CATEGORY_FORMAT_REGISTRY. "
            f"Registered = {sorted(CATEGORY_FORMAT_REGISTRY)}. 严禁猜测格式，请先声明。"
        )
    return True


assert_category_registered = validate_category_registered


def get_date_key(category: str, now: datetime | None = None) -> str:
    validate_category_registered(category)
    now = now or datetime.now()
    return now.strftime(CATEGORY_FORMAT_REGISTRY[category]["date_fmt"])


def format_id(category: str, date_key: str, seq: int) -> str:
    validate_category_registered(category)
    width = CATEGORY_FORMAT_REGISTRY[category]["seq_width"]
    return f"{category}-{date_key}-{seq:0{width}d}"


def resolve_lark_sheets_cli() -> str:
    if DEFAULT_LARK_SHEETS_CLI.exists():
        return str(DEFAULT_LARK_SHEETS_CLI)
    fallback = shutil.which("lark-cli")
    if fallback:
        return fallback
    raise FileNotFoundError(
        f"lark-sheets cli not found: {DEFAULT_LARK_SHEETS_CLI}; global fallback 'lark-cli' also missing"
    )


def extract_json_payload(raw: str) -> dict:
    ansi_clean = re.sub(r"\x1b\[[0-9;]*m", "", raw)
    match = re.search(r"(\{[\s\S]*\})", ansi_clean)
    if not match:
        raise RuntimeError(f"failed to parse lark-sheets output: {raw}")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"failed to parse lark-sheets output: {raw}") from exc


def run_lark_sheets(args: list[str]) -> dict:
    cli = resolve_lark_sheets_cli()
    completed = subprocess.run(
        [cli] + args,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"lark-sheets failed: {' '.join(args)}\nstdout={completed.stdout}\nstderr={completed.stderr}"
        )
    try:
        payload = extract_json_payload(completed.stdout)
    except RuntimeError as exc:
        raise RuntimeError(str(exc)) from exc
    if not payload.get("ok"):
        raise RuntimeError(f"lark-sheets returned not ok: {payload}")
    return payload


def resolve_sheet(url: str, sheet_name: str) -> tuple[str, int]:
    info = run_lark_sheets(["sheets", "+info", "--url", url])
    sheets = info["data"]["sheets"]["sheets"]
    for sheet in sheets:
        if sheet["title"] == sheet_name:
            return sheet["sheet_id"], int(sheet["grid_properties"]["row_count"])
    raise GuardrailViolation(f"sheet not found: {sheet_name}")


def read_values(url: str, sheet_id: str, range_str: str) -> list[list]:
    result = run_lark_sheets([
        "sheets",
        "+read",
        "--url",
        url,
        "--sheet-id",
        sheet_id,
        "--range",
        range_str,
    ])
    return result.get("data", {}).get("valueRange", {}).get("values", [])


def write_values(url: str, sheet_id: str, range_str: str, values: list[list]) -> None:
    run_lark_sheets([
        "sheets",
        "+write",
        "--url",
        url,
        "--sheet-id",
        sheet_id,
        "--range",
        range_str,
        "--values",
        json.dumps(values, ensure_ascii=False),
    ])


def normalize_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def write_dlq(category: str, error_message: str, context: dict) -> Path:
    DEFAULT_DLQ_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "category": category,
        "error": error_message,
        "context": context,
    }
    with DEFAULT_DLQ_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return DEFAULT_DLQ_PATH


def allocate_id(category: str, dry_run: bool = False) -> str:
    validate_category_registered(category)
    registry_url = os.environ.get("AIME_OMNI_REGISTRY_URL", DEFAULT_REGISTRY_SPREADSHEET_URL)
    sheet_id, row_count = resolve_sheet(registry_url, DEFAULT_REGISTRY_SHEET_NAME)
    rows = read_values(registry_url, sheet_id, f"A1:E{row_count}")

    target_row_number = None
    current_seq = 0
    current_date_key = get_date_key(category)
    for index, row in enumerate(rows[1:], start=2):
        row_category = normalize_cell(row[0] if len(row) > 0 else "")
        if row_category == category:
            target_row_number = index
            db_date_key = normalize_cell(row[2] if len(row) > 2 else "")
            current_seq = int(normalize_cell(row[3] if len(row) > 3 else 0) or 0) if db_date_key == current_date_key else 0
            break

    if target_row_number is None:
        raise GuardrailViolation(
            f"category '{category}' is declared in CATEGORY_FORMAT_REGISTRY but missing in {DEFAULT_REGISTRY_SHEET_NAME}"
        )

    new_seq = current_seq + 1
    issued_id = format_id(category, current_date_key, new_seq)
    updated_at = datetime.now().strftime("%Y/%m/%d %H:%M")
    write_range = f"C{target_row_number}:E{target_row_number}"
    expected_values = [[current_date_key, str(new_seq), updated_at]]

    if dry_run:
        return issued_id

    last_error = None
    for _ in range(DEFAULT_MAX_RETRIES):
        try:
            write_values(registry_url, sheet_id, write_range, expected_values)
            time.sleep(DEFAULT_RAW_SLEEP_SECONDS)
            readback = read_values(registry_url, sheet_id, write_range)
            if not readback:
                raise GuardrailViolation(f"empty readback for range {write_range}")
            normalized = [[normalize_cell(cell) for cell in row] for row in readback]
            if normalized[0] != expected_values[0]:
                raise GuardrailViolation(
                    f"RAW readback mismatch for {write_range}: expected={expected_values[0]} actual={normalized[0]}"
                )
            return issued_id
        except Exception as exc:  # noqa: PERF203
            last_error = exc
            time.sleep(DEFAULT_RAW_SLEEP_SECONDS)

    raise RuntimeError(f"max retries exceeded while allocating {category}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("category", help="编号前缀，例如 DOC / BUG / WK / SYS / KNO")
    parser.add_argument("--dry-run", action="store_true", help="只计算编号，不执行写入")
    args = parser.parse_args()

    category = args.category.upper().strip()
    try:
        issued_id = allocate_id(category, dry_run=args.dry_run)
        print(issued_id)
        return 0
    except Exception as exc:  # noqa: PERF203
        dlq_path = write_dlq(category, str(exc), {"dry_run": args.dry_run})
        print(f"Error: {exc}\nDLQ: {dlq_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
