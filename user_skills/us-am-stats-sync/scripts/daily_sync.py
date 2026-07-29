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
    SHEET_TOKEN,
    _extract_json_object,
    _run_lark_cli,
    raw_readback,
    sync_bitable_to_sheet,
    today_m_d,
)

SUMMARY_SHEET_ID = "2unp6l"
SUMMARY_READ_RANGE = "A1:K14"
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
    for row in range(2, 10):
        row_cells: List[Dict[str, str]] = []
        for summary_col, detail_col in metric_columns.items():
            if row == 9:
                row_cells.append({"formula": f"=SUM({summary_col}2:{summary_col}8)"})
            else:
                row_cells.append({"formula": f"=SUMIF(明细!A:A,A{row},明细!{detail_col}:{detail_col})"})
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
            "B2:F9",
            "--cells",
            "-",
        ],
        stdin_text=json.dumps(cells, ensure_ascii=False),
    )


def _write_summary_update_date() -> Dict[str, Any]:
    # Use +csv-put instead of +cells-set here. The summary sheet has hidden G:H columns,
    # and +cells-set may offset the physical write target around K; +csv-put writes K1:K2 exactly.
    # Pre-set K2 as text so 7/29 stays M/D instead of being formatted as 29-Jul.
    _run_json(
        [
            "sheets",
            "+cells-set-style",
            "--spreadsheet-token",
            SHEET_TOKEN,
            "--sheet-id",
            SUMMARY_SHEET_ID,
            "--range",
            "K2",
            "--number-format",
            "@",
        ]
    )
    csv_text = f"更新日期\n{today_m_d()}\n"
    return _run_json(
        [
            "sheets",
            "+csv-put",
            "--spreadsheet-token",
            SHEET_TOKEN,
            "--sheet-id",
            SUMMARY_SHEET_ID,
            "--start-cell",
            "K1",
            "--csv",
            "-",
        ],
        stdin_text=csv_text,
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
            "B2:I9",
        ]
    )


def step1_sync_detail() -> Dict[str, Any]:
    """同步明细：分页拉取 Bitable，全量覆盖写入 VM2reD，并 RAW 回捞 A1:J3。"""
    return sync_bitable_to_sheet()


def step2_update_formulas() -> Dict[str, Any]:
    """一次性写公式：若 B2 已包含 SUMIF，则跳过 B2:F9，仅刷新 K1:K2 更新日期。"""
    before = _read_summary_snapshot()
    b2_before = _read_b2_formula()
    formulas_skipped = "SUMIF" in b2_before.upper()

    formula_write_result: Dict[str, Any] | None = None
    if not formulas_skipped:
        formula_write_result = _write_summary_formulas()

    date_write_result = _write_summary_update_date()
    time.sleep(2)

    b2_after = _read_b2_formula()
    verify = _verify_formulas()
    after = _read_summary_snapshot()

    if "SUMIF" not in b2_after.upper():
        raise RuntimeError(f"B2 formula verification failed: {b2_after!r}")
    verify_status = verify.get("data", {}).get("status")
    if verify_status != "success":
        raise RuntimeError(f"Formula verify did not pass: {json.dumps(verify, ensure_ascii=False)}")

    return {
        "formulas_skipped": formulas_skipped,
        "b2_formula_before": b2_before,
        "b2_formula_after": b2_after,
        "formula_write_result": formula_write_result,
        "date_write_result": date_write_result,
        "formula_verify": verify,
        "raw_before_A1_K14": before,
        "raw_after_A1_K14": after,
    }


def main() -> None:
    detail_result = step1_sync_detail()
    summary_result = step2_update_formulas()
    print(
        json.dumps(
            {
                "detail": detail_result,
                "summary": summary_result,
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
