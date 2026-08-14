#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sync Feishu/Lark Bitable records to the US AM stats detail Sheet.

Default source/target:
- Bitable: MPN9bUhBTaUsgcsrN92m2Oq0yde / tblZerjwuSM5rOG3
- Sheet:   XZoSsAwObh72kPtn3DLmWJ4AyWc / VM2reD (明细)

Design notes:
- All Feishu reads/writes go through AIME's customized lark-cli path.
- Bitable pagination is handled explicitly by offset + limit.
- Sheet overwrite is implemented as: clear target range -> CSV write -> RAW read-back.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple


BITABLE_TOKEN = "MPN9bUhBTaUsgcsrN92m2Oq0yde"
TABLE_ID = "tblZerjwuSM5rOG3"
SHEET_TOKEN = "XZoSsAwObh72kPtn3DLmWJ4AyWc"
DETAIL_SHEET_ID = "VM2reD"

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DRIFT_LOG_DIR = SKILL_DIR / "output" / "schema_drift"

FIELD_ALIASES: Dict[str, List[str]] = {
    # Upstream renamed the post-July onboarded count in v1.4.
    "新增入驻数": ["7月后新增入驻数"],
    # Upstream renamed the historical salable metric to the shorter current-stock label.
    "历史入驻新增可售": ["可售数"],
}
OPTIONAL_SOURCE_COLUMNS = {"USAM", "历史入驻新增可售"}
NULL_FALLBACK = "NULL"

INDUSTRY_MAP: Dict[str, str] = {
    "Fashion": "服饰服配",
    "FMCG": "快消生活",
    "Sports & Lifestyle": "运动潮奢",
    "Electronics": "3C家电",
    "Home & Textiles": "日用家纺",
    "Automotive & Tools": "汽摩工具",
    "Furniture & Home Improvements": "家具家装",
}

# SourceID and 序号 are intentionally excluded. J 列为每日同步日期。
OUTPUT_COLUMNS: List[str] = [
    "US行业",
    "USAM",
    "线索数",
    "可联系",
    "已触达",
    "有意愿",
    "新增入驻数",
    "新增入驻可售",
    "历史入驻新增可售",
    "更新日期",
]

PAGE_SIZE = 100

TREND_METRICS: List[str] = [
    "线索数",
    "可联系",
    "已触达",
    "有意愿",
    "新增入驻数",
    "新增入驻可售",
    "历史入驻新增可售",
]
TREND_OUTPUT_START_CELL = "A17"
TREND_READBACK_RANGE = "A17:I30"


def validate_trend_contract(values: List[List[Any]]) -> None:
    """Runtime gate before trend side effects: fixed headers, non-overlap with A1:K15 summary formulas."""
    if not values or len(values[0]) != 9:
        raise ValueError("Trend payload must have exactly 9 columns")
    expected_prefix = ["趋势类型", "日期/周", *TREND_METRICS]
    if values[0] != expected_prefix:
        raise ValueError(f"Unexpected trend header: {values[0]}")
    if TREND_OUTPUT_START_CELL != "A17":
        raise ValueError("Trend output start must stay at A17 to avoid existing A1:K15 formulas/parameters")


def _coerce_number(value: Any) -> float:
    if value in (None, "", NULL_FALLBACK):
        return 0.0
    text = str(value).strip().replace(",", "")
    if not text or text.upper() == NULL_FALLBACK:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _parse_m_d(value: Any, *, default_year: int | None = None) -> date | None:
    """Parse M/D, YYYY/M/D or YYYY-MM-DD update dates used by historical backfills."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    year = default_year or datetime.now().year
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d", "%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            if "%Y" not in fmt:
                return date(year, parsed.month, parsed.day)
            return parsed.date()
        except ValueError:
            continue
    return None


def _aggregate_rows_by_date(rows: Iterable[Dict[str, Any]]) -> Dict[date, Dict[str, float]]:
    aggregated: Dict[date, Dict[str, float]] = defaultdict(lambda: {metric: 0.0 for metric in TREND_METRICS})
    current_year = datetime.now().year
    for row in rows:
        day = _parse_m_d(row.get("更新日期"), default_year=current_year)
        if day is None:
            continue
        for metric in TREND_METRICS:
            aggregated[day][metric] += _coerce_number(row.get(metric))
    return aggregated


def _records_to_detail_rows(records: List[Dict[str, Any]], update_date: str | None = None) -> List[Dict[str, Any]]:
    """Convert current Bitable records to detail-shaped dict rows for trend fallback on same-day sync."""
    date_value = update_date or today_m_d()
    rows: List[Dict[str, Any]] = []
    for record in records:
        row: Dict[str, Any] = {}
        for column in OUTPUT_COLUMNS:
            row[column] = date_value if column == "更新日期" else resolve_source_value(record, column)
        rows.append(row)
    return rows


def compute_7day_trend(detail_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compute daily metric totals for the latest 7 calendar days present in historical detail rows."""
    aggregated = _aggregate_rows_by_date(detail_rows)
    if not aggregated:
        return []
    end_day = max(aggregated)
    start_day = end_day - timedelta(days=6)
    result: List[Dict[str, Any]] = []
    for offset in range(7):
        day = start_day + timedelta(days=offset)
        metrics = aggregated.get(day, {metric: 0.0 for metric in TREND_METRICS})
        result.append({"日期": f"{day.month}/{day.day}", **{metric: metrics[metric] for metric in TREND_METRICS}})
    return result


def compute_4week_trend(detail_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compute Monday-Sunday natural-week metric totals for the latest 4 weeks in historical detail rows."""
    aggregated = _aggregate_rows_by_date(detail_rows)
    if not aggregated:
        return []
    latest = max(aggregated)
    latest_week_start = latest - timedelta(days=latest.weekday())
    result: List[Dict[str, Any]] = []
    for week_offset in range(3, -1, -1):
        week_start = latest_week_start - timedelta(days=7 * week_offset)
        week_end = week_start + timedelta(days=6)
        totals = {metric: 0.0 for metric in TREND_METRICS}
        for day, metrics in aggregated.items():
            if week_start <= day <= week_end:
                for metric in TREND_METRICS:
                    totals[metric] += metrics[metric]
        result.append({"自然周": f"{week_start.month}/{week_start.day}-{week_end.month}/{week_end.day}", **totals})
    return result


def build_trend_values(detail_rows: List[Dict[str, Any]]) -> List[List[Any]]:
    values: List[List[Any]] = [["趋势类型", "日期/周", *TREND_METRICS]]
    for item in compute_7day_trend(detail_rows):
        values.append(["近7天", item["日期"], *[item[metric] for metric in TREND_METRICS]])
    for item in compute_4week_trend(detail_rows):
        values.append(["近4周", item["自然周"], *[item[metric] for metric in TREND_METRICS]])
    validate_trend_contract(values)
    return values


def read_detail_rows_from_sheet(sheet_token: str = SHEET_TOKEN, sheet_id: str = DETAIL_SHEET_ID) -> List[Dict[str, Any]]:
    payload = raw_readback(sheet_token, sheet_id, "A1:J10000")
    csv_text = payload.get("data", {}).get("annotated_csv", "")
    if not csv_text.strip():
        return []
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return []
    header = [cell.strip() for cell in rows[0]]
    result: List[Dict[str, Any]] = []
    for raw in rows[1:]:
        if not any(str(cell).strip() for cell in raw):
            continue
        result.append({header[idx]: raw[idx].strip() if idx < len(raw) else "" for idx in range(len(header))})
    return result


def write_trend_values_to_summary(sheet_token: str, summary_sheet_id: str, values: List[List[Any]]) -> Dict[str, Any]:
    validate_trend_contract(values)
    csv_text = values_to_csv(values)
    _run_lark_cli(
        [
            "sheets",
            "+cells-clear",
            "--spreadsheet-token",
            sheet_token,
            "--sheet-id",
            summary_sheet_id,
            "--range",
            TREND_READBACK_RANGE,
            "--scope",
            "content",
            "--yes",
        ]
    )
    _run_lark_cli(
        [
            "sheets",
            "+cells-set-style",
            "--spreadsheet-token",
            sheet_token,
            "--sheet-id",
            summary_sheet_id,
            "--range",
            TREND_READBACK_RANGE,
            "--number-format",
            "0",
        ]
    )
    _run_lark_cli(
        [
            "sheets",
            "+csv-put",
            "--spreadsheet-token",
            sheet_token,
            "--sheet-id",
            summary_sheet_id,
            "--start-cell",
            TREND_OUTPUT_START_CELL,
            "--csv",
            "-",
        ],
        stdin_text=csv_text,
    )
    time.sleep(2)
    return raw_readback(sheet_token, summary_sheet_id, TREND_READBACK_RANGE)


def validate_sync_contract(
    bitable_token: str = BITABLE_TOKEN,
    table_id: str = TABLE_ID,
    sheet_token: str = SHEET_TOKEN,
    sheet_id: str = DETAIL_SHEET_ID,
) -> None:
    """Validate side-effect targets and output schema before any destructive write."""
    defaults = {
        "bitable_token": (bitable_token, BITABLE_TOKEN),
        "table_id": (table_id, TABLE_ID),
        "sheet_token": (sheet_token, SHEET_TOKEN),
        "sheet_id": (sheet_id, DETAIL_SHEET_ID),
    }
    mismatches = [name for name, (actual, expected) in defaults.items() if actual != expected]
    if mismatches:
        raise ValueError(f"Unsafe sync target override detected: {mismatches}")
    required_output_columns = [
        "US行业",
        "USAM",
        "线索数",
        "可联系",
        "已触达",
        "有意愿",
        "新增入驻数",
        "新增入驻可售",
        "历史入驻新增可售",
        "更新日期",
    ]
    if OUTPUT_COLUMNS != required_output_columns:
        raise ValueError(f"Unexpected OUTPUT_COLUMNS contract: {OUTPUT_COLUMNS}")


def today_m_d() -> str:
    """Return today's date in M/D format, e.g. 7/29."""
    now = datetime.now()
    return f"{now.month}/{now.day}"


def _run_lark_cli(args: Sequence[str], *, stdin_text: str | None = None) -> str:
    """Run lark-cli and return stdout, raising a readable error on failure."""
    cmd = ["lark-cli", *args]
    proc = subprocess.run(
        cmd,
        input=stdin_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "lark-cli command failed\n"
            f"command: {' '.join(cmd)}\n"
            f"exit_code: {proc.returncode}\n"
            f"stdout: {proc.stdout}\n"
            f"stderr: {proc.stderr}"
        )
    return proc.stdout


def _extract_json_object(stdout: str) -> Dict[str, Any]:
    """Extract the JSON envelope even when runtime metrics are printed around it."""
    text = stdout.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError(f"No JSON object found in lark-cli stdout: {stdout}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse lark-cli JSON stdout: {stdout}") from exc


def _run_lark_cli_json(args: Sequence[str], *, stdin_text: str | None = None) -> Dict[str, Any]:
    payload = _extract_json_object(_run_lark_cli([*args, "--format", "json"], stdin_text=stdin_text))
    if not payload.get("ok", False):
        raise RuntimeError(f"lark-cli returned non-ok envelope: {json.dumps(payload, ensure_ascii=False)}")
    return payload


def _normalize_cell(value: Any) -> Any:
    """Normalize Bitable cell values into Sheet-friendly scalar values."""
    if value is None:
        return ""
    if isinstance(value, list):
        return "；".join(str(item) for item in value if item is not None)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _translate_industry(value: Any) -> str:
    """Translate US行业 values from English to Chinese using the confirmed hard-coded mapping."""
    normalized = str(_normalize_cell(value)).strip()
    if not normalized:
        return ""
    parts = [part.strip() for part in normalized.replace(",", "；").split("；") if part.strip()]
    translated = [INDUSTRY_MAP.get(part, part) for part in parts]
    return "；".join(translated)


def fetch_all_bitable_records(bitable_token: str = BITABLE_TOKEN, table_id: str = TABLE_ID) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Fetch all records from Bitable using offset pagination and return field-mapped rows."""
    offset = 0
    all_rows: List[Dict[str, Any]] = []
    field_order: List[str] = []

    while True:
        envelope = _run_lark_cli_json(
            [
                "base",
                "+record-list",
                "--base-token",
                bitable_token,
                "--table-id",
                table_id,
                "--limit",
                str(PAGE_SIZE),
                "--offset",
                str(offset),
            ]
        )
        data = envelope.get("data", {})
        fields = data.get("fields", [])
        raw_rows = data.get("data", [])
        if not field_order:
            field_order = list(fields)

        for raw_row in raw_rows:
            row = {field: _normalize_cell(raw_row[idx]) if idx < len(raw_row) else "" for idx, field in enumerate(fields)}
            if "US行业" in row:
                row["US行业"] = _translate_industry(row["US行业"])
            all_rows.append(row)

        if not data.get("has_more", False):
            break
        offset += PAGE_SIZE

    return all_rows, field_order


def resolve_source_value(record: Dict[str, Any], output_column: str) -> Any:
    """Resolve output value from canonical field, alias, or explicit NULL fallback."""
    if output_column == "更新日期":
        raise ValueError("更新日期 is generated locally and must not be resolved from Bitable")
    if output_column in record:
        return record.get(output_column, "")
    for alias in FIELD_ALIASES.get(output_column, []):
        if alias in record:
            return record.get(alias, "")
    if output_column in OPTIONAL_SOURCE_COLUMNS:
        return NULL_FALLBACK
    return ""


def build_sheet_values(records: List[Dict[str, Any]], update_date: str | None = None) -> List[List[Any]]:
    """Reorder Bitable records into the exact Sheet output order, including header row and update date."""
    date_value = update_date or today_m_d()
    values: List[List[Any]] = [OUTPUT_COLUMNS]
    for record in records:
        values.append([
            resolve_source_value(record, "US行业"),
            resolve_source_value(record, "USAM"),
            resolve_source_value(record, "线索数"),
            resolve_source_value(record, "可联系"),
            resolve_source_value(record, "已触达"),
            resolve_source_value(record, "有意愿"),
            resolve_source_value(record, "新增入驻数"),
            resolve_source_value(record, "新增入驻可售"),
            resolve_source_value(record, "历史入驻新增可售"),
            date_value,
        ])
    return values


def values_to_csv(values: List[List[Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(values)
    return output.getvalue()


def clear_sheet_range(sheet_token: str, sheet_id: str, clear_range: str = "A1:J10000") -> None:
    """Clear the target Sheet range before overwriting values."""
    _run_lark_cli(
        [
            "sheets",
            "+cells-clear",
            "--spreadsheet-token",
            sheet_token,
            "--sheet-id",
            sheet_id,
            "--range",
            clear_range,
            "--scope",
            "content",
            "--yes",
        ]
    )


def write_values_to_sheet(sheet_token: str, sheet_id: str, values: List[List[Any]]) -> None:
    csv_text = values_to_csv(values)
    _run_lark_cli(
        [
            "sheets",
            "+csv-put",
            "--spreadsheet-token",
            sheet_token,
            "--sheet-id",
            sheet_id,
            "--start-cell",
            "A1",
            "--csv",
            "-",
        ],
        stdin_text=csv_text,
    )


def raw_readback(sheet_token: str, sheet_id: str, read_range: str = "A1:J3") -> Dict[str, Any]:
    """Read back a target range as RAW CSV for validation and reporting."""
    stdout = _run_lark_cli(
        [
            "sheets",
            "+csv-get",
            "--spreadsheet-token",
            sheet_token,
            "--sheet-id",
            sheet_id,
            "--range",
            read_range,
            "--include-row-prefix=false",
            "--format",
            "json",
        ]
    )
    return _extract_json_object(stdout)


def inspect_schema_drift(source_fields: List[str]) -> Dict[str, Any]:
    """Compare expected output fields with actual Bitable fields before writing."""
    drift_items: List[Dict[str, Any]] = []
    required_missing: List[str] = []
    for column in [item for item in OUTPUT_COLUMNS if item != "更新日期"]:
        if column in source_fields:
            continue
        alias_hit = next((alias for alias in FIELD_ALIASES.get(column, []) if alias in source_fields), None)
        if alias_hit:
            drift_items.append({
                "column": column,
                "status": "renamed",
                "mapped_from": alias_hit,
                "action": "use_alias",
            })
        elif column in OPTIONAL_SOURCE_COLUMNS:
            drift_items.append({
                "column": column,
                "status": "deleted_or_not_granted",
                "mapped_from": None,
                "action": f"write_{NULL_FALLBACK}_fallback",
            })
        else:
            required_missing.append(column)
            drift_items.append({
                "column": column,
                "status": "missing_required",
                "mapped_from": None,
                "action": "hard_fail_before_write",
            })
    return {
        "expected_fields": [item for item in OUTPUT_COLUMNS if item != "更新日期"],
        "actual_fields": source_fields,
        "aliases": FIELD_ALIASES,
        "optional_fields": sorted(OPTIONAL_SOURCE_COLUMNS),
        "drift_items": drift_items,
        "required_missing": required_missing,
    }


def write_schema_drift_log(drift_report: Dict[str, Any]) -> str | None:
    """Persist an explicit schema drift warning when upstream fields do not match the contract."""
    if not drift_report.get("drift_items"):
        return None
    DRIFT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = DRIFT_LOG_DIR / f"schema_drift_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    payload = {
        "status": "schema_drift_detected",
        "detected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **drift_report,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def sync_bitable_to_sheet(
    bitable_token: str = BITABLE_TOKEN,
    table_id: str = TABLE_ID,
    sheet_token: str = SHEET_TOKEN,
    sheet_id: str = DETAIL_SHEET_ID,
) -> Dict[str, Any]:
    """Pull all Bitable records, translate industry names, overwrite VM2reD, then RAW-read A1:J3."""
    validate_sync_contract(bitable_token, table_id, sheet_token, sheet_id)
    records, source_fields = fetch_all_bitable_records(bitable_token, table_id)

    schema_drift = inspect_schema_drift(source_fields)
    schema_drift_log = write_schema_drift_log(schema_drift)
    if schema_drift["required_missing"]:
        raise ValueError(
            "Missing required Bitable fields: "
            f"{schema_drift['required_missing']}; source_fields={source_fields}; "
            f"schema_drift_log={schema_drift_log}"
        )

    values = build_sheet_values(records)
    trend_values = build_trend_values(_records_to_detail_rows(records))
    clear_sheet_range(sheet_token, sheet_id)
    write_values_to_sheet(sheet_token, sheet_id, values)

    time.sleep(2)
    readback = raw_readback(sheet_token, sheet_id, "A1:J3")

    return {
        "records_fetched": len(records),
        "rows_written_including_header": len(values),
        "data_rows_written": max(len(values) - 1, 0),
        "source_fields": source_fields,
        "schema_drift": schema_drift,
        "schema_drift_log": schema_drift_log,
        "output_columns": OUTPUT_COLUMNS,
        "trend_preview_rows": trend_values[:4],
        "trend_output_start_cell": TREND_OUTPUT_START_CELL,
        "raw_readback_A1_J3": readback,
    }


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync US AM Bitable stats to a Feishu/Lark detail Sheet.")
    parser.add_argument("--bitable-token", default=BITABLE_TOKEN, help="Bitable/Base token")
    parser.add_argument("--table-id", default=TABLE_ID, help="Bitable table id")
    parser.add_argument("--sheet-token", default=SHEET_TOKEN, help="Target Sheet spreadsheet token")
    parser.add_argument("--sheet-id", default=DETAIL_SHEET_ID, help="Target worksheet id")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    result = sync_bitable_to_sheet(args.bitable_token, args.table_id, args.sheet_token, args.sheet_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
