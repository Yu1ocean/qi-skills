#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily sync for US AM招商统计.

Workflow:
1. Sync Bitable detail records into VM2reD (明细), including Chinese industry names and 更新日期.
2. Update 2unp6l (US行业统计) formulas once. If B2 already contains SUMIF, formula rewrite is skipped.

Run with AIME lark-cli credentials injected, e.g. bash include_secrets=true:
  python3 scripts/daily_sync.py
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from sync_bitable_to_sheet import (  # noqa: E402
    DETAIL_SHEET_ID,
    OUTPUT_COLUMNS,
    SHEET_TOKEN,
    _extract_json_object,
    _run_lark_cli,
    read_detail_rows_from_sheet,
    sync_bitable_to_sheet,
    today_iso,
)

SUMMARY_SHEET_ID = "2unp6l"
DETAIL_SHEET_NAME = "明细"
SUMMARY_SHEET_NAME = "US行业统计"
# 唯一允许写入的汇总单元格公式：取明细表最新 sync_date（文本日期，禁用 MAX）
N2_UPDATE_DATE_FORMULA = "=INDEX('明细'!J:J,COUNTA('明细'!J:J))"


def assert_n2_formula_safe(formula: str) -> str:
    """副作用前硬熔断：N2 公式禁止使用 MAX( 或引用 sheet_id VM2reD!。"""
    upper = formula.upper()
    if "MAX(" in upper:
        raise RuntimeError(f"N2 formula guard failed: MAX( is forbidden (text date column): {formula!r}")
    if "VM2reD!" in formula or "VM2RED!" in upper:
        raise RuntimeError(f"N2 formula guard failed: must reference sheet_name '明细', not sheet_id: {formula!r}")
    if "INDEX(" not in upper or "COUNTA(" not in upper:
        raise RuntimeError(f"N2 formula guard failed: expected INDEX+COUNTA anchor formula: {formula!r}")
    return formula
SUMMARY_READ_RANGE = "A1:K16"
# 汇总表结构（v1.9）：第 2~8 行 = 7 大行业，第 9 行 = 育商兜底分组，第 10 行 = 总计，参数区第 12~16 行（入驻率 B16）
SUMMARY_GROUP_ROWS = (2, 9)
SUMMARY_TOTAL_ROW = 10
GROUP_COUNT = 8
INDUSTRY_ORDER_RANGE = "A2:A9"
FORMULA_CHECK_RANGE = "B2"


def _run_json(args: List[str], *, stdin_text: str | None = None) -> Dict[str, Any]:
    return _extract_json_object(_run_lark_cli([*args, "--format", "json"], stdin_text=stdin_text))


def _read_summary_snapshot() -> Dict[str, Any]:
    return _run_json(
        [
            "sheets",
            "+csv-get",
            "--spreadsheet-token",
            SHEET_TOKEN,
            "--sheet-id",
            SUMMARY_SHEET_ID,
            "--range",
            SUMMARY_READ_RANGE,
            "--include-row-prefix=false",
        ]
    )


def _read_b2_formula() -> str:
    payload = _run_json(
        [
            "sheets",
            "+cells-get",
            "--spreadsheet-token",
            SHEET_TOKEN,
            "--sheet-id",
            SUMMARY_SHEET_ID,
            "--range",
            FORMULA_CHECK_RANGE,
            "--include",
            "value,formula",
        ]
    )
    try:
        cell = payload["data"]["ranges"][0]["cells"][0][0]
    except (KeyError, IndexError, TypeError):
        return ""
    return str(cell.get("formula") or "")


def _build_formula_cells() -> List[List[Dict[str, str]]]:
    metric_columns = {
        "B": "C",
        "C": "D",
        "D": "E",
        "E": "F",
        "F": "G",
    }
    cells: List[List[Dict[str, str]]] = []
    for row in range(SUMMARY_GROUP_ROWS[0], SUMMARY_TOTAL_ROW + 1):
        row_cells: List[Dict[str, str]] = []
        for summary_col, detail_col in metric_columns.items():
            if row == SUMMARY_TOTAL_ROW:
                row_cells.append(
                    {"formula": f"=SUM({summary_col}{SUMMARY_GROUP_ROWS[0]}:{summary_col}{SUMMARY_GROUP_ROWS[1]})"}
                )
            else:
                row_cells.append(
                    {
                        "formula": (
                            f"=SUMIFS('明细'!{detail_col}:{detail_col},"
                            f"'明细'!$A:$A,$A{row},'明细'!$J:$J,$N$2)"
                        )
                    }
                )
        cells.append(row_cells)
    return cells


def _write_summary_formulas() -> Dict[str, Any]:
    cells = _build_formula_cells()
    return _run_json(
        [
            "sheets",
            "+cells-set",
            "--spreadsheet-token",
            SHEET_TOKEN,
            "--sheet-id",
            SUMMARY_SHEET_ID,
            "--range",
            f"B{SUMMARY_GROUP_ROWS[0]}:F{SUMMARY_TOTAL_ROW}",
            "--cells",
            "-",
        ],
        stdin_text=json.dumps(cells, ensure_ascii=False),
    )


def _write_summary_update_date_formula() -> Dict[str, Any]:
    """Only allow writing the update-date formula to N2.

    Per contract, the summary sheet (2unp6l) is user-maintained except N2.
    """
    return _run_json(
        [
            "sheets",
            "+cells-set",
            "--spreadsheet-token",
            SHEET_TOKEN,
            "--sheet-id",
            SUMMARY_SHEET_ID,
            "--range",
            "N2",
            "--cells",
            "-",
        ],
        stdin_text=json.dumps(
            [[{"formula": assert_n2_formula_safe(N2_UPDATE_DATE_FORMULA)}]], ensure_ascii=False
        ),
    )


def _verify_formulas() -> Dict[str, Any]:
    return _run_json(
        [
            "sheets",
            "+formula-verify",
            "--spreadsheet-token",
            SHEET_TOKEN,
            "--sheet-id",
            SUMMARY_SHEET_ID,
            "--range",
            f"B{SUMMARY_GROUP_ROWS[0]}:I{SUMMARY_TOTAL_ROW}",
        ]
    )


def step1_sync_detail() -> Dict[str, Any]:
    """同步明细：分页拉取 Bitable，全量覆盖写入 VM2reD，并 RAW 回捞 A1:J3。"""
    return sync_bitable_to_sheet()


def _read_n2_formula() -> str:
    payload = _run_json(
        [
            "sheets",
            "+cells-get",
            "--spreadsheet-token",
            SHEET_TOKEN,
            "--sheet-id",
            SUMMARY_SHEET_ID,
            "--range",
            "N2",
            "--include",
            "value,formula",
        ]
    )
    try:
        cell = payload["data"]["ranges"][0]["cells"][0][0]
    except (KeyError, IndexError, TypeError):
        return ""
    return str(cell.get("formula") or "")


def step2_update_formulas() -> Dict[str, Any]:
    """只写入 2unp6l!N2 更新日期公式，不允许覆盖其他任何区域。"""
    before = _read_summary_snapshot()
    write_result = _write_summary_update_date_formula()
    time.sleep(2)

    n2_formula = _read_n2_formula()
    upper_n2 = n2_formula.upper()
    if "INDEX(" not in upper_n2 or "COUNTA(" not in upper_n2 or "MAX(" in upper_n2 or "VM2RED!" in upper_n2:
        raise RuntimeError(f"N2 formula verification failed: {n2_formula!r}")

    after = _read_summary_snapshot()

    return {
        "write_result": write_result,
        "n2_formula": n2_formula,
        "raw_before_A1_K16": before,
        "raw_after_A1_K16": after,
    }


def _read_industry_order_from_summary() -> List[str]:
    payload = _run_json(
        [
            "sheets",
            "+csv-get",
            "--spreadsheet-token",
            SHEET_TOKEN,
            "--sheet-id",
            SUMMARY_SHEET_ID,
            "--range",
            INDUSTRY_ORDER_RANGE,
            "--include-row-prefix=false",
        ]
    )
    csv_text = payload.get("data", {}).get("annotated_csv", "")
    lines = [line.strip() for line in csv_text.splitlines() if line.strip()]
    industries = [line for line in lines if line]
    if len(industries) != GROUP_COUNT:
        raise RuntimeError(
            f"Expected {GROUP_COUNT} groups (7 大行业 + 育商) in 2unp6l!{INDUSTRY_ORDER_RANGE}, "
            f"got {len(industries)}: {industries}"
        )
    return industries


def _col_index_to_a1(col_index_1_based: int) -> str:
    """Convert 1-based column index to Excel-style letters (A, B, ..., Z, AA, ...)."""
    if col_index_1_based <= 0:
        raise ValueError(f"Invalid column index: {col_index_1_based}")
    letters: List[str] = []
    n = col_index_1_based
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


def _find_or_append_aux_date_column(sync_date: str) -> str | None:
    """Return start cell (e.g. O1) for today's aux column; None if already exists."""
    payload = _run_json(
        [
            "sheets",
            "+csv-get",
            "--spreadsheet-token",
            SHEET_TOKEN,
            "--sheet-id",
            DETAIL_SHEET_ID,
            "--range",
            "O1:ZZ10",
            "--include-row-prefix=false",
        ]
    )
    csv_text = payload.get("data", {}).get("annotated_csv", "")
    reader = csv.reader(csv_text.splitlines())
    rows = list(reader)
    if not rows:
        rows = [[]]
    header = [cell.strip() for cell in rows[0]]

    for idx, cell in enumerate(header):
        if cell == sync_date:
            return None

    last_used = -1
    for idx, cell in enumerate(header):
        if cell.strip():
            last_used = idx

    target_offset = last_used + 1
    start_col_1_based = 15  # O
    target_col_1_based = start_col_1_based + target_offset
    return f"{_col_index_to_a1(target_col_1_based)}1"


def _compute_today_onboard_by_industry(detail_rows: List[Dict[str, Any]], industries: List[str], sync_date: str) -> List[int]:
    metric_col = "新增入驻数"
    if metric_col not in OUTPUT_COLUMNS:
        raise RuntimeError(f"Unexpected OUTPUT_COLUMNS contract, missing {metric_col}")

    totals = {industry: 0.0 for industry in industries}
    for row in detail_rows:
        if str(row.get("更新日期", "")).strip() != sync_date:
            continue
        industry = str(row.get("US行业", "")).strip()
        if industry not in totals:
            continue
        raw = str(row.get(metric_col, "") or "").strip().replace(",", "")
        try:
            value = float(raw) if raw else 0.0
        except ValueError:
            value = 0.0
        totals[industry] += value

    return [int(totals[industry]) for industry in industries]


def step3_write_detail_aux_area() -> Dict[str, Any]:
    """在 VM2reD 的 O 列起写入横向辅助区（幂等追加一列）。"""
    sync_date = today_iso()
    industries = _read_industry_order_from_summary()

    start_cell = _find_or_append_aux_date_column(sync_date)
    if start_cell is None:
        return {"skipped_existing_sync_date": True, "sync_date": sync_date}

    detail_rows = read_detail_rows_from_sheet(SHEET_TOKEN, DETAIL_SHEET_ID)
    counts = _compute_today_onboard_by_industry(detail_rows, industries, sync_date)
    total = sum(counts)

    csv_lines = [sync_date, *[str(v) for v in counts], str(total)]
    csv_text = "\n".join(csv_lines) + "\n"

    write_result = _run_json(
        [
            "sheets",
            "+csv-put",
            "--spreadsheet-token",
            SHEET_TOKEN,
            "--sheet-id",
            DETAIL_SHEET_ID,
            "--start-cell",
            start_cell,
            "--csv",
            "-",
        ],
        stdin_text=csv_text,
    )
    time.sleep(2)

    col_letters = "".join([ch for ch in start_cell if ch.isalpha()])
    readback_range = f"{col_letters}1:{col_letters}{GROUP_COUNT + 2}"
    readback = _run_json(
        [
            "sheets",
            "+csv-get",
            "--spreadsheet-token",
            SHEET_TOKEN,
            "--sheet-id",
            DETAIL_SHEET_ID,
            "--range",
            readback_range,
            "--include-row-prefix=false",
        ]
    )

    return {
        "skipped_existing_sync_date": False,
        "sync_date": sync_date,
        "start_cell": start_cell,
        "readback_range": readback_range,
        "industries": industries,
        "counts": counts,
        "total": total,
        "write_result": write_result,
        "raw_readback": readback,
    }


def main() -> None:
    detail_result = step1_sync_detail()
    summary_result = step2_update_formulas()
    aux_result = step3_write_detail_aux_area()
    print(
        json.dumps(
            {
                "detail": detail_result,
                "summary": summary_result,
                "detail_aux": aux_result,
                "links": {
                    "detail_sheet": f"https://bytedance.larkoffice.com/sheets/{SHEET_TOKEN}?sheet={DETAIL_SHEET_ID}",
                    "summary_sheet": f"https://bytedance.larkoffice.com/sheets/{SHEET_TOKEN}?sheet={SUMMARY_SHEET_ID}",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
