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
from datetime import datetime
from typing import Any, Dict, List, Sequence, Tuple


BITABLE_TOKEN = "MPN9bUhBTaUsgcsrN92m2Oq0yde"
TABLE_ID = "tblZerjwuSM5rOG3"
SHEET_TOKEN = "XZoSsAwObh72kPtn3DLmWJ4AyWc"
DETAIL_SHEET_ID = "VM2reD"

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


def build_sheet_values(records: List[Dict[str, Any]], update_date: str | None = None) -> List[List[Any]]:
    """Reorder Bitable records into the exact Sheet output order, including header row and update date."""
    date_value = update_date or today_m_d()
    values: List[List[Any]] = [OUTPUT_COLUMNS]
    for record in records:
        values.append([
            record.get("US行业", ""),
            record.get("USAM", ""),
            record.get("线索数", ""),
            record.get("可联系", ""),
            record.get("已触达", ""),
            record.get("有意愿", ""),
            record.get("新增入驻数", ""),
            record.get("新增入驻可售", ""),
            record.get("历史入驻新增可售", ""),
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


def sync_bitable_to_sheet(
    bitable_token: str = BITABLE_TOKEN,
    table_id: str = TABLE_ID,
    sheet_token: str = SHEET_TOKEN,
    sheet_id: str = DETAIL_SHEET_ID,
) -> Dict[str, Any]:
    """Pull all Bitable records, translate industry names, overwrite VM2reD, then RAW-read A1:J3."""
    validate_sync_contract(bitable_token, table_id, sheet_token, sheet_id)
    records, source_fields = fetch_all_bitable_records(bitable_token, table_id)

    required_source_columns = [column for column in OUTPUT_COLUMNS if column != "更新日期"]
    missing = [column for column in required_source_columns if column not in source_fields]
    if missing:
        raise ValueError(f"Missing required Bitable fields: {missing}; source_fields={source_fields}")

    values = build_sheet_values(records)
    clear_sheet_range(sheet_token, sheet_id)
    write_values_to_sheet(sheet_token, sheet_id, values)

    time.sleep(2)
    readback = raw_readback(sheet_token, sheet_id, "A1:J3")

    return {
        "records_fetched": len(records),
        "rows_written_including_header": len(values),
        "data_rows_written": max(len(values) - 1, 0),
        "source_fields": source_fields,
        "output_columns": OUTPUT_COLUMNS,
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
