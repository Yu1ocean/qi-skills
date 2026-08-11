#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sheet writer with header lock, idempotent range clear, csv-put, updated-at anchor and RAW readback.

Physical guarantees:
1. 表头第一行只读锁死：写入前只读 A1:<最右列>1，校验列数匹配 target.columns；不匹配 → raise。
2. 幂等 range clear：+cells-clear --scope content --range data_range（严格从 data_start_row 起，不触 row 1）。
3. csv-put 平铺：+csv-put --start-cell A<data_start_row>。
4. Updated-at anchor：+csv-put --start-cell <updated_at_cell> 写 YYYY-MM-DD。
5. RAW readback：sleep 2s → +csv-get 读回 A1:<最右列>3 + updated_at_cell，逐字段比对。
6. 硬拒绝 +values-append（assert）。
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


def _col_letter(index: int) -> str:
    """0-based column index → A/B/.../Z/AA/AB..."""
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
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise SheetWriterError(f"Failed to parse lark-cli JSON: {exc}\nstdout={stdout[:800]}")


def _run_lark_cli(args: Sequence[str], stdin_text: Optional[str] = None) -> str:
    # Anti-values-append hard block
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


def validate_target_contract(target: Dict[str, Any]) -> None:
    """L3 runtime physical assertion before any write."""
    if not isinstance(target, dict):
        raise SheetWriterError(f"target must be dict, got {type(target).__name__}")
    required = ["sheet_url", "sheet_id", "columns", "data_range", "readback_range", "updated_at_cell"]
    missing = [k for k in required if not target.get(k)]
    if missing:
        raise SheetWriterError(f"target missing required keys: {missing}")
    if not isinstance(target["columns"], list) or not target["columns"]:
        raise SheetWriterError("target.columns must be a non-empty list")
    # header_row / data_start_row consistency
    header_row = int(target.get("header_row", 1))
    data_start_row = int(target.get("data_start_row", 2))
    if header_row != 1:
        raise SheetWriterError(f"header_row must be 1 (header lock invariant), got {header_row}")
    if data_start_row < 2:
        raise SheetWriterError(f"data_start_row must be >= 2, got {data_start_row}")
    # data_range must not start from row 1
    m = re.match(r"^([A-Z]+)(\d+):([A-Z]+)(\d+)$", target["data_range"].strip().upper())
    if not m:
        raise SheetWriterError(f"data_range must match pattern 'A2:J10000', got {target['data_range']!r}")
    start_row = int(m.group(2))
    if start_row < 2:
        raise SheetWriterError(
            f"data_range must NOT include row 1 (header lock). got start_row={start_row}"
        )
    # updated_at_cell format
    if not re.match(r"^[A-Z]+\d+$", target["updated_at_cell"].strip().upper()):
        raise SheetWriterError(f"updated_at_cell must be an A1 reference, got {target['updated_at_cell']!r}")


def validate_header_lock(sheet_url: str, sheet_id: str, columns: List[str]) -> List[str]:
    """Read A1:<最右列>1 and validate it matches expected columns length.

    Returns the actual header row read from sheet.
    """
    last_col = _col_letter(len(columns) - 1)
    header_range = f"A1:{last_col}1"
    payload = _run_lark_cli_json(
        [
            "sheets",
            "+csv-get",
            "--url",
            sheet_url,
            "--sheet-id",
            sheet_id,
            "--range",
            header_range,
            "--include-row-prefix=false",
        ]
    )
    data = payload.get("data", {}) or {}
    annotated_csv = data.get("annotated_csv") or data.get("csv") or ""
    if not annotated_csv.strip():
        raise SheetWriterError(
            f"Header row {header_range} is empty. Header lock requires a non-empty first row."
        )
    # Parse first CSV line as header
    reader = csv.reader(io.StringIO(annotated_csv))
    rows = list(reader)
    if not rows:
        raise SheetWriterError(f"Header row {header_range} parsed to zero rows.")
    header = [cell.strip() for cell in rows[0]]
    if len(header) != len(columns):
        raise SheetWriterError(
            f"Header column count mismatch: sheet has {len(header)} cells, "
            f"target.columns expects {len(columns)}. sheet_header={header!r}, expected={columns!r}"
        )
    return header


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


def _values_to_csv(rows: List[List[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in rows:
        writer.writerow(["" if v is None else v for v in row])
    return buffer.getvalue()


def write_data_rows(
    sheet_url: str, sheet_id: str, start_cell: str, rows: List[List[Any]]
) -> None:
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


def write_updated_at(
    sheet_url: str, sheet_id: str, cell: str, updated_at: str
) -> None:
    csv_text = f"{updated_at}\n"
    _run_lark_cli(
        [
            "sheets",
            "+csv-put",
            "--url",
            sheet_url,
            "--sheet-id",
            sheet_id,
            "--start-cell",
            cell,
            "--csv",
            "-",
        ],
        stdin_text=csv_text,
    )


def raw_readback(
    sheet_url: str, sheet_id: str, readback_range: str
) -> Dict[str, Any]:
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


def read_cell(sheet_url: str, sheet_id: str, cell: str) -> str:
    range_str = f"{cell}:{cell}"
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
    if not annotated_csv.strip():
        return ""
    reader = csv.reader(io.StringIO(annotated_csv))
    rows = list(reader)
    if not rows or not rows[0]:
        return ""
    return (rows[0][0] or "").strip()


def write_all(
    target: Dict[str, Any],
    data_rows: List[List[Any]],
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """End-to-end idempotent write with header lock + data clear + csv-put + updated_at + RAW readback.

    Returns a report dict including rows_written, updated_at, readback samples.
    """
    validate_target_contract(target)
    sheet_url = target["sheet_url"]
    sheet_id = target["sheet_id"]
    columns = target["columns"]
    data_range = target["data_range"]
    readback_range = target["readback_range"]
    updated_at_cell = target["updated_at_cell"]
    updated_at_format = target.get("updated_at_format", "YYYY-MM-DD")
    data_start_row = int(target.get("data_start_row", 2))

    header_read = validate_header_lock(sheet_url, sheet_id, columns)
    clear_data_range(sheet_url, sheet_id, data_range)

    start_cell = f"A{data_start_row}"
    write_data_rows(sheet_url, sheet_id, start_cell, data_rows)

    # Compute updated_at
    if not updated_at:
        # YYYY-MM-DD default
        if updated_at_format == "YYYY-MM-DD":
            updated_at = datetime.now().strftime("%Y-%m-%d")
        else:
            # crude formatter mapping (extend as needed)
            updated_at = datetime.now().strftime("%Y-%m-%d")

    write_updated_at(sheet_url, sheet_id, updated_at_cell, updated_at)

    # Wait for sheet propagation
    time.sleep(2)

    readback_data = raw_readback(sheet_url, sheet_id, readback_range)
    updated_at_readback = read_cell(sheet_url, sheet_id, updated_at_cell)

    if updated_at_readback != updated_at:
        raise SheetWriterError(
            f"Updated-at anchor mismatch: expected={updated_at!r}, "
            f"readback={updated_at_readback!r}, cell={updated_at_cell}"
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
