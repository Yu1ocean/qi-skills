#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sheet writer helpers for multi-source-sync.

v2.0 adds dual-sheet + diff-patch helpers while keeping v1.x full-overwrite APIs.
Hard constraints kept:
1. row 1 header lock
2. never use +values-append
3. RAW readback after write
"""

from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple


class SheetWriterError(RuntimeError):
    """Raised on sheet contract violation or write/readback mismatch."""


MAX_DEFAULT_ROWS = 10000


def _col_letter(index: int) -> str:
    if index < 0:
        raise ValueError(f"Negative column index: {index}")
    result = ""
    n = index
    while True:
        result = chr(ord("A") + (n % 26)) + result
        n = n // 26 - 1
        if n < 0:
            break
    return result


def _extract_json_object(stdout: str) -> Dict[str, Any]:
    text = stdout.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise SheetWriterError(f"No JSON object in lark-cli stdout: {stdout[:500]}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SheetWriterError(f"Failed to parse lark-cli JSON: {exc}\nstdout={stdout[:800]}")


def _run_lark_cli(args: Sequence[str], stdin_text: Optional[str] = None) -> str:
    args_str = " ".join(str(a) for a in args)
    assert "values-append" not in args_str, (
        "Illegal shortcut: +values-append is banned by multi-source-sync contract."
    )
    cmd = ["lark-cli", *args]
    proc = subprocess.run(cmd, input=stdin_text, text=True, capture_output=True)
    if proc.returncode != 0:
        raise SheetWriterError(
            f"lark-cli failed. exit={proc.returncode}\n"
            f"cmd: {' '.join(cmd)}\nstdout={proc.stdout[:800]}\nstderr={proc.stderr[:800]}"
        )
    return proc.stdout


def _run_lark_cli_json(args: Sequence[str], stdin_text: Optional[str] = None) -> Dict[str, Any]:
    stdout = _run_lark_cli([*args, "--format", "json"], stdin_text=stdin_text)
    payload = _extract_json_object(stdout)
    if not payload.get("ok", False):
        raise SheetWriterError(f"lark-cli envelope not ok: {json.dumps(payload, ensure_ascii=False)}")
    return payload


def _parse_csv_text(text: str) -> List[List[str]]:
    if not (text or "").strip():
        return []
    return list(csv.reader(io.StringIO(text)))


def _values_to_csv(rows: List[List[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in rows:
        writer.writerow(["" if v is None else v for v in row])
    return buffer.getvalue()


def read_range_matrix(sheet_url: str, sheet_id: str, range_str: str) -> List[List[str]]:
    payload = _run_lark_cli_json(
        [
            "sheets",
            "+csv-get",
            "--url",
            sheet_url,
            "--sheet-id",
            sheet_id,
            "--range",
            range_str,
            "--include-row-prefix=false",
        ]
    )
    data = payload.get("data", {}) or {}
    annotated_csv = data.get("annotated_csv") or data.get("csv") or ""
    return _parse_csv_text(annotated_csv)


def read_cell(sheet_url: str, sheet_id: str, cell: str) -> str:
    rows = read_range_matrix(sheet_url, sheet_id, f"{cell}:{cell}")
    if not rows or not rows[0]:
        return ""
    return (rows[0][0] or "").strip()


def write_matrix(sheet_url: str, sheet_id: str, start_cell: str, rows: List[List[Any]]) -> None:
    if not rows:
        return
    csv_text = _values_to_csv(rows)
    _run_lark_cli(
        [
            "sheets",
            "+csv-put",
            "--url",
            sheet_url,
            "--sheet-id",
            sheet_id,
            "--start-cell",
            start_cell,
            "--csv",
            "-",
        ],
        stdin_text=csv_text,
    )


def clear_data_range(sheet_url: str, sheet_id: str, data_range: str) -> None:
    _run_lark_cli(
        [
            "sheets",
            "+cells-clear",
            "--url",
            sheet_url,
            "--sheet-id",
            sheet_id,
            "--range",
            data_range,
            "--scope",
            "content",
            "--yes",
        ]
    )


def raw_readback(sheet_url: str, sheet_id: str, readback_range: str) -> Dict[str, Any]:
    payload = _run_lark_cli_json(
        [
            "sheets",
            "+csv-get",
            "--url",
            sheet_url,
            "--sheet-id",
            sheet_id,
            "--range",
            readback_range,
            "--include-row-prefix=false",
        ]
    )
    return payload.get("data", {}) or {}


def validate_target_contract(target: Dict[str, Any]) -> None:
    if not isinstance(target, dict):
        raise SheetWriterError(f"target must be dict, got {type(target).__name__}")
    if not target.get("sheet_url"):
        raise SheetWriterError("target.sheet_url is required")
    if not isinstance(target.get("columns"), list) or not target.get("columns"):
        raise SheetWriterError("target.columns must be a non-empty list")


def validate_header_lock(sheet_url: str, sheet_id: str, columns: List[str]) -> List[str]:
    last_col = _col_letter(len(columns) - 1)
    header = read_range_matrix(sheet_url, sheet_id, f"A1:{last_col}1")
    if not header:
        raise SheetWriterError("Header row is empty")
    first_row = [cell.strip() for cell in header[0]]
    if len(first_row) != len(columns):
        raise SheetWriterError(
            f"Header column count mismatch: sheet has {len(first_row)} cells, expected {len(columns)}"
        )
    return first_row


def ensure_header_cells(sheet_url: str, sheet_id: str, expected: Dict[str, str]) -> Dict[str, Any]:
    written = []
    for cell, value in expected.items():
        current = read_cell(sheet_url, sheet_id, cell)
        if current == value:
            continue
        write_matrix(sheet_url, sheet_id, cell, [[value]])
        written.append({"cell": cell, "old": current, "new": value})
    return {"written": written, "ok": True}


def get_last_non_empty_row(
    sheet_url: str,
    sheet_id: str,
    start_col: str,
    end_col: str,
    max_rows: int = MAX_DEFAULT_ROWS,
) -> int:
    rows = read_range_matrix(sheet_url, sheet_id, f"{start_col}1:{end_col}{max_rows}")
    last = 0
    for idx, row in enumerate(rows, start=1):
        if any(str(cell).strip() for cell in row):
            last = idx
    return last


def group_consecutive_rows(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not records:
        return []
    ordered = sorted(records, key=lambda item: int(item["row_index"]))
    groups: List[Dict[str, Any]] = []
    current_group = {
        "start_row": int(ordered[0]["row_index"]),
        "end_row": int(ordered[0]["row_index"]),
        "rows": [ordered[0]["values"]],
    }
    for item in ordered[1:]:
        row_index = int(item["row_index"])
        if row_index == current_group["end_row"] + 1:
            current_group["end_row"] = row_index
            current_group["rows"].append(item["values"])
        else:
            groups.append(current_group)
            current_group = {
                "start_row": row_index,
                "end_row": row_index,
                "rows": [item["values"]],
            }
    groups.append(current_group)
    return groups


def write_updated_at(sheet_url: str, sheet_id: str, cell: str, updated_at: str) -> None:
    write_matrix(sheet_url, sheet_id, cell, [[updated_at]])


def wait_and_verify_cell(sheet_url: str, sheet_id: str, cell: str, expected: str, sleep_seconds: int = 2) -> str:
    time.sleep(sleep_seconds)
    actual = read_cell(sheet_url, sheet_id, cell)
    if actual != expected:
        raise SheetWriterError(
            f"Cell mismatch: cell={cell}, expected={expected!r}, actual={actual!r}"
        )
    return actual


def write_data_rows(sheet_url: str, sheet_id: str, start_cell: str, rows: List[List[Any]]) -> None:
    write_matrix(sheet_url, sheet_id, start_cell, rows)


def write_all(
    target: Dict[str, Any],
    data_rows: List[List[Any]],
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    validate_target_contract(target)
    required = ["sheet_id", "data_range", "readback_range", "updated_at_cell"]
    missing = [k for k in required if not target.get(k)]
    if missing:
        raise SheetWriterError(f"target missing required keys: {missing}")

    sheet_url = target["sheet_url"]
    sheet_id = target["sheet_id"]
    columns = target["columns"]
    data_range = target["data_range"]
    readback_range = target["readback_range"]
    updated_at_cell = target["updated_at_cell"]
    data_start_row = int(target.get("data_start_row", 2))

    header_read = validate_header_lock(sheet_url, sheet_id, columns)
    clear_data_range(sheet_url, sheet_id, data_range)
    start_cell = f"A{data_start_row}"
    write_data_rows(sheet_url, sheet_id, start_cell, data_rows)

    if not updated_at:
        updated_at = datetime.now().strftime("%Y-%m-%d")
    write_updated_at(sheet_url, sheet_id, updated_at_cell, updated_at)
    time.sleep(2)

    readback_data = raw_readback(sheet_url, sheet_id, readback_range)
    updated_at_readback = read_cell(sheet_url, sheet_id, updated_at_cell)
    if updated_at_readback != updated_at:
        raise SheetWriterError(
            f"Updated-at anchor mismatch: expected={updated_at!r}, readback={updated_at_readback!r}, cell={updated_at_cell}"
        )

    return {
        "rows_written": len(data_rows),
        "columns": columns,
        "header_read": header_read,
        "start_cell": start_cell,
        "data_range_cleared": data_range,
        "updated_at": updated_at,
        "updated_at_cell": updated_at_cell,
        "updated_at_readback": updated_at_readback,
        "readback": readback_data,
    }
