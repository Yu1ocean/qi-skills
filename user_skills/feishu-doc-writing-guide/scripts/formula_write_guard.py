#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""formula_write_guard.py — 飞书表格公式写入前置断言（L3 运行时熔断）

对应 SKILL.md v7.4 陷阱3/4/5：
  - 陷阱3：公式中引用的必须是 sheet_name，不能是 sheet_id
  - 陷阱4：公式必须走 formula 字段写入，禁止 value / csv-put（伪公式文本）
  - 陷阱5：文本型日期列禁止 MAX/MIN，应改用 INDEX(列, COUNTA(列))

用法:
  python3 scripts/formula_write_guard.py \
    --formula "=INDEX('明细'!J:J,COUNTA('明细'!J:J))" \
    --sheet-names '明细,US行业统计' \
    [--sheet-ids 'VM2reD,7Kd0aQ'] \
    [--field formula] [--text-date-columns "明细!J"]

失败时 raise/exit 1，禁止调用方兜底继续写入。
"""
from __future__ import annotations

import argparse
import re
import sys

SHEET_REF_RE = re.compile(r"'([^']+)'!")
SHEET_ID_LIKE_RE = re.compile(r"^[A-Za-z0-9]{6}$")
AGG_ON_COL_RE = re.compile(r"\b(MAX|MIN)\s*\(\s*'([^']+)'!\s*([A-Za-z]{1,3})", re.I)


class FormulaGuardError(RuntimeError):
    """公式写入护栏熔断异常。"""


def validate_write_field(field: str) -> None:
    """陷阱4：只允许 formula 字段写公式。"""
    if field.strip().lower() != "formula":
        raise FormulaGuardError(
            f"[TRAP4] 公式必须以 formula 字段写入，当前 field={field!r}。"
            " 禁止使用 value 或 +csv-put，否则会写成伪公式文本并级联 #VALUE!。"
        )


def validate_sheet_refs(formula: str, sheet_names: list[str], sheet_ids: list[str]) -> list[str]:
    """陷阱3：公式中的跨 Sheet 引用必须命中已知 sheet_name，且不得是 sheet_id。"""
    refs = SHEET_REF_RE.findall(formula)
    if not refs:
        return []
    known = {n.strip() for n in sheet_names if n.strip()}
    ids = {i.strip() for i in sheet_ids if i.strip()}
    for ref in refs:
        if ref in ids:
            raise FormulaGuardError(
                f"[TRAP3] 公式引用 '{ref}' 是 sheet_id，不是 sheet_name。"
                " 请先执行 `lark-cli sheets +workbook-info` 获取 sheet_name 后重写公式。"
            )
        if known and ref not in known:
            hint = "疑似 sheet_id" if SHEET_ID_LIKE_RE.match(ref) else "未在 workbook-info 中出现"
            raise FormulaGuardError(
                f"[TRAP3] 公式引用 '{ref}' 不在已知 sheet_name 列表 {sorted(known)} 中（{hint}）。"
                " 禁止凭猜测或 sheet_id 拼公式。"
            )
    return refs


def validate_text_date_aggregation(formula: str, text_date_columns: list[str]) -> None:
    """陷阱5：文本型日期列禁止 MAX/MIN。"""
    marked = {c.strip().upper() for c in text_date_columns if c.strip()}
    for _fn, sheet, col in AGG_ON_COL_RE.findall(formula):
        key = f"{sheet}!{col}".upper()
        if key in marked:
            raise FormulaGuardError(
                f"[TRAP5] '{sheet}'!{col} 为文本型日期列，MAX/MIN 会返回 0。"
                f" 请改用 =INDEX('{sheet}'!{col}:{col},COUNTA('{sheet}'!{col}:{col}))。"
            )


def assert_formula_write_safe(
    formula: str,
    sheet_names: list[str],
    sheet_ids: list[str] | None = None,
    field: str = "formula",
    text_date_columns: list[str] | None = None,
) -> dict:
    if not formula.startswith("="):
        raise FormulaGuardError(f"[GUARD] 公式必须以 '=' 开头，当前: {formula!r}")
    validate_write_field(field)
    refs = validate_sheet_refs(formula, sheet_names, sheet_ids or [])
    validate_text_date_aggregation(formula, text_date_columns or [])
    return {"status": "ok", "formula": formula, "cross_sheet_refs": refs, "field": field}


def _split(raw: str | None) -> list[str]:
    return [x for x in (raw or "").split(",") if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="飞书公式写入前置断言（陷阱3/4/5）")
    ap.add_argument("--formula", required=True)
    ap.add_argument("--sheet-names", default="", help="逗号分隔的合法 sheet_name（来自 +workbook-info）")
    ap.add_argument("--sheet-ids", default="", help="逗号分隔的 sheet_id 黑名单")
    ap.add_argument("--field", default="formula", help="写入字段，必须为 formula")
    ap.add_argument("--text-date-columns", default="", help="文本型日期列，如 '明细!J'")
    args = ap.parse_args()
    try:
        result = assert_formula_write_safe(
            args.formula,
            _split(args.sheet_names),
            _split(args.sheet_ids),
            args.field,
            _split(args.text_date_columns),
        )
    except FormulaGuardError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"PASSED: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
