#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily sync for US AM招商统计.

Workflow:
1. Sync Bitable detail records into VM2reD (明细), including Chinese industry names and 更新日期.
2. Update 2unp6l (US行业统计) N2 update-date formula only. Every other summary region is user-maintained.
3. Append today's column to the detail aux area (O.. onward).
4. Read-only guard: verify the trend matrix data source (明细!K helper column + 趋势区日期锚点) is still alive.

Write boundary (v2.0):
- 明细(VM2reD): only A:J and O.. onward. K:N is PROTECTED (K = 日期(标准化)).
- US行业统计(2unp6l): only N2. A17:B17 / A18:H28 / A30:E40 / K:L are PROTECTED trend-matrix regions.

Run with AIME lark-cli credentials injected, e.g. bash include_secrets=true:
  python3 scripts/daily_sync.py
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from sync_bitable_to_sheet import (  # noqa: E402
    DETAIL_SHEET_ID,
    OUTPUT_COLUMNS,
    PROTECTED_RANGES,
    SHEET_TOKEN,
    SUMMARY_ALLOWED_WRITE_CELLS,
    _extract_json_object,
    _run_lark_cli,
    assert_detail_write_range,
    assert_summary_write_range,
    read_detail_rows_from_sheet,
    sync_bitable_to_sheet,
    today_iso,
)

SUMMARY_SHEET_ID = "2unp6l"
DETAIL_SHEET_NAME = "明细"
SUMMARY_SHEET_NAME = "US行业统计"
# 唯一允许写入的汇总单元格公式：取明细表最新 sync_date（文本日期，禁用 MAX）
N2_UPDATE_DATE_FORMULA = "=INDEX('明细'!J:J,COUNTA('明细'!J:J))"

# ---------------------------------------------------------------------------
# v2.0 趋势数据区契约（Trend Matrix Contract）——全部由用户手工维护，脚本只读校验
# ---------------------------------------------------------------------------
# 明细 K 列：日期(标准化) 辅助列，把文本日期（8/14 与 2026-08-15 混排）统一成日期序列号
DETAIL_DATE_NORM_COLUMN = "K"
DETAIL_DATE_NORM_HEADER = "日期(标准化)"
DETAIL_DATE_NORM_PROBE_RANGE = "K1:K2"
# 趋势区唯一日期基准锚点
TREND_ANCHOR_CELL = "B17"
TREND_ANCHOR_FORMULA = "=IF(ISNUMBER($N$2),$N$2,DATEVALUE($N$2))"
# 7 日趋势区（A18:H28）：B19 = $B$17-6 ... H19 = $B$17
TREND_DAILY_RANGE = "A18:H28"
TREND_DAILY_FIRST_DATE_CELL = "B19"
TREND_DAILY_FIRST_DATE_FORMULA = "=$B$17-6"
# 4 周趋势区（A30:E40）：B31..E31 = 各周周一
TREND_WEEKLY_RANGE = "A30:E40"
TREND_WEEKLY_FIRST_DATE_CELL = "B31"


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
    """Deprecated since v1.7 / hard-blocked since v2.0.

    The summary data rows (B2:F10), the parameter block and the whole trend matrix
    (A17:B17 / A18:H28 / A30:E40 / K:L) are user-maintained. Only N2 is writable.
    """
    target_range = f"B{SUMMARY_GROUP_ROWS[0]}:F{SUMMARY_TOTAL_ROW}"
    assert_summary_write_range(target_range, op="_write_summary_formulas")
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
            target_range,
            "--cells",
            "-",
        ],
        stdin_text=json.dumps(cells, ensure_ascii=False),
    )


def _write_summary_update_date_formula() -> Dict[str, Any]:
    """Only allow writing the update-date formula to N2.

    Per contract, the summary sheet (2unp6l) is user-maintained except N2.
    """
    target_cell = assert_summary_write_range("N2", op="_write_summary_update_date_formula")
    return _run_json(
        [
            "sheets",
            "+cells-set",
            "--spreadsheet-token",
            SHEET_TOKEN,
            "--sheet-id",
            SUMMARY_SHEET_ID,
            "--range",
            target_cell,
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

    # 硬熔断：辅助区必须落在 O 列及其右侧，绝不允许回落到受保护的 K:N
    assert_detail_write_range(start_cell, op="step3_write_detail_aux_area", width=1)

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


def _read_cell(sheet_id: str, cell_range: str) -> Dict[str, Any]:
    """Read a single cell with both value and formula (read-only probe)."""
    payload = _run_json(
        [
            "sheets",
            "+cells-get",
            "--spreadsheet-token",
            SHEET_TOKEN,
            "--sheet-id",
            sheet_id,
            "--range",
            cell_range,
            "--include",
            "value,formula",
        ]
    )
    try:
        return payload["data"]["ranges"][0]["cells"][0][0] or {}
    except (KeyError, IndexError, TypeError):
        return {}


def _as_date_serial(value: Any) -> float | None:
    """Interpret a cell value as a date serial number (or a parseable ISO date)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m/%d"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return float((parsed.date() - date(1899, 12, 30)).days)
    return None


def assert_detail_date_norm_column_alive() -> Dict[str, Any]:
    """Runtime gate: 明细!K 列（日期标准化辅助列）必须存活，否则趋势区整体断链。

    K 列是趋势区唯一的真日期来源（明细!J 是文本日期，8/14 与 2026-08-15 混排），
    K2 为空或不是日期序列号即判定为辅助列断链。
    """
    header_cell = _read_cell(DETAIL_SHEET_ID, f"{DETAIL_DATE_NORM_COLUMN}1")
    probe_cell = _read_cell(DETAIL_SHEET_ID, f"{DETAIL_DATE_NORM_COLUMN}2")
    serial = _as_date_serial(probe_cell.get("value"))
    if serial is None or serial <= 0:
        raise RuntimeError(
            f"[硬熔断] 明细!{DETAIL_DATE_NORM_COLUMN}2 日期标准化辅助列断链："
            f"值={probe_cell.get('value')!r} formula={probe_cell.get('formula')!r}；"
            f"应为 {DETAIL_DATE_NORM_HEADER} 日期序列号，公式 "
            '=IF($J2="","",IF(ISNUMBER($J2),$J2,IFERROR(DATEVALUE($J2),"")))'
        )
    return {
        "k1_header": header_cell.get("value"),
        "k2_value": probe_cell.get("value"),
        "k2_formula": probe_cell.get("formula"),
        "k2_date_serial": serial,
    }


def assert_trend_anchor_alive() -> Dict[str, Any]:
    """Runtime gate: 趋势区日期锚点 B17 存活，且 7 日区首日 B19 == B17-6，防止锚点漂移。"""
    anchor = _read_cell(SUMMARY_SHEET_ID, TREND_ANCHOR_CELL)
    first_day = _read_cell(SUMMARY_SHEET_ID, TREND_DAILY_FIRST_DATE_CELL)

    anchor_serial = _as_date_serial(anchor.get("value"))
    if anchor_serial is None or anchor_serial <= 0:
        raise RuntimeError(
            f"[硬熔断] {SUMMARY_SHEET_NAME}!{TREND_ANCHOR_CELL} 趋势区日期锚点失效："
            f"值={anchor.get('value')!r} formula={anchor.get('formula')!r}；"
            f"应为 {TREND_ANCHOR_FORMULA}"
        )

    formula = str(first_day.get("formula") or "")
    normalized = formula.replace(" ", "").upper()
    formula_ok = normalized == TREND_DAILY_FIRST_DATE_FORMULA.replace(" ", "").upper()

    first_serial = _as_date_serial(first_day.get("value"))
    value_ok = first_serial is not None and abs((anchor_serial - 6) - first_serial) < 1e-6

    if not (formula_ok or value_ok):
        raise RuntimeError(
            f"[硬熔断] 趋势区日期锚点漂移：{SUMMARY_SHEET_NAME}!{TREND_DAILY_FIRST_DATE_CELL} "
            f"应为 {TREND_DAILY_FIRST_DATE_FORMULA}（即 {TREND_ANCHOR_CELL}-6），"
            f"实际 formula={formula!r} value={first_day.get('value')!r}"
        )

    return {
        "b17_value": anchor.get("value"),
        "b17_formula": anchor.get("formula"),
        "b17_date_serial": anchor_serial,
        "b19_value": first_day.get("value"),
        "b19_formula": formula,
        "b19_formula_match": formula_ok,
        "b19_value_match": value_ok,
    }


def _verify_trend_formulas() -> Dict[str, Any]:
    """Zero-error convergence check across the whole trend matrix (read-only)."""
    results: Dict[str, Any] = {}
    for label, rng in (
        ("summary_core", f"B{SUMMARY_GROUP_ROWS[0]}:I{SUMMARY_TOTAL_ROW}"),
        ("trend_daily", TREND_DAILY_RANGE),
        ("trend_weekly", TREND_WEEKLY_RANGE),
    ):
        payload = _run_json(
            [
                "sheets",
                "+formula-verify",
                "--spreadsheet-token",
                SHEET_TOKEN,
                "--sheet-id",
                SUMMARY_SHEET_ID,
                "--range",
                rng,
            ]
        )
        data = payload.get("data", payload) or {}
        status = str(data.get("status") or payload.get("status") or "")
        total_errors = data.get("total_errors", payload.get("total_errors"))
        if status and status != "success":
            raise RuntimeError(f"[硬熔断] {label} ({rng}) formula-verify status={status!r}")
        if total_errors not in (None, 0, "0"):
            raise RuntimeError(f"[硬熔断] {label} ({rng}) formula-verify total_errors={total_errors!r}")
        results[label] = {"range": rng, "status": status, "total_errors": total_errors}
    return results


def step4_verify_trend_matrix() -> Dict[str, Any]:
    """只读验收趋势数据区：K 列辅助列存活 + B17/B19 锚点未漂移 + 公式零错误收敛。"""
    detail_probe = assert_detail_date_norm_column_alive()
    anchor_probe = assert_trend_anchor_alive()
    trend_readback = _run_json(
        [
            "sheets",
            "+csv-get",
            "--spreadsheet-token",
            SHEET_TOKEN,
            "--sheet-id",
            SUMMARY_SHEET_ID,
            "--range",
            TREND_DAILY_RANGE,
            "--include-row-prefix=false",
        ]
    )
    weekly_readback = _run_json(
        [
            "sheets",
            "+csv-get",
            "--spreadsheet-token",
            SHEET_TOKEN,
            "--sheet-id",
            SUMMARY_SHEET_ID,
            "--range",
            TREND_WEEKLY_RANGE,
            "--include-row-prefix=false",
        ]
    )
    return {
        "protected_ranges": PROTECTED_RANGES,
        "summary_allowed_write_cells": list(SUMMARY_ALLOWED_WRITE_CELLS),
        "detail_date_norm_column": detail_probe,
        "trend_anchor": anchor_probe,
        "formula_verify": _verify_trend_formulas(),
        "raw_trend_daily_A18_H28": trend_readback,
        "raw_trend_weekly_A30_E40": weekly_readback,
    }


def main() -> None:
    detail_result = step1_sync_detail()
    summary_result = step2_update_formulas()
    aux_result = step3_write_detail_aux_area()
    trend_result = step4_verify_trend_matrix()
    print(
        json.dumps(
            {
                "detail": detail_result,
                "summary": summary_result,
                "detail_aux": aux_result,
                "trend_matrix": trend_result,
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
