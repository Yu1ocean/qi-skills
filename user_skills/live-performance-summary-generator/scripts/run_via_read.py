#!/usr/bin/env python3
"""
本地兜底入口：当原 spreadsheet 因权限墙无法 +export 时，使用 +read 拉取 raw 数据，
构造本地 xlsx，再复用 generate_summary_sheet 主流程。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from openpyxl import Workbook

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import generate_summary_sheet as gs
from lark_sheets_cli import LarkSheetsCLI


def fetch_raw_via_read(cli: LarkSheetsCLI, spreadsheet_token: str, raw_sheet_id: str, max_row: int = 1000, max_col_letter: str = "AJ") -> list[list]:
    rng = f"{raw_sheet_id}!A1:{max_col_letter}{max_row}"
    payload = cli.read_range(spreadsheet_token, rng)
    return payload


def build_local_xlsx(values: list[list], raw_sheet_title: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = raw_sheet_title
    for row in values:
        ws.append(row)
    wb.save(target_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("spreadsheet")
    parser.add_argument("--raw-sheet-title", required=True)
    parser.add_argument("--summary-sheet-title", default=gs.DEFAULT_SUMMARY_SHEET_TITLE)
    parser.add_argument("--export-dir", default=str(Path.cwd() / "tmp_live_performance_exports"))
    parser.add_argument("--output-json", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        gs.validate_sheet_title(args.raw_sheet_title, "raw_sheet_title")
        gs.validate_sheet_title(args.summary_sheet_title, "summary_sheet_title")
        gs.validate_thresholds()

        gs.ensure_bytedcli_auth()
        cli = LarkSheetsCLI()
        spreadsheet_token = cli.resolve_spreadsheet_token(args.spreadsheet)

        raw_sheet = cli.get_sheet(spreadsheet_token, args.raw_sheet_title)
        if raw_sheet is None:
            raise gs.SummaryGenerationError(f"找不到 raw sheet：{args.raw_sheet_title}")

        # 用 +read 取代 +export
        values = fetch_raw_via_read(cli, spreadsheet_token, raw_sheet.sheet_id)

        export_dir = Path(args.export_dir).resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        local_xlsx = export_dir / f"{gs.DEFAULT_EXPORT_PREFIX}-{spreadsheet_token}.xlsx"
        build_local_xlsx(values, args.raw_sheet_title, local_xlsx)

        # monkey patch export_workbook 以返回本地 xlsx
        gs.export_workbook = lambda cli, spreadsheet_token, output_dir: local_xlsx

        # 调用主流程
        result = gs.generate_summary_sheet(
            spreadsheet=args.spreadsheet,
            raw_sheet_title=args.raw_sheet_title,
            summary_sheet_title=args.summary_sheet_title,
            export_dir=export_dir,
        )
    except Exception as exc:  # pylint: disable=broad-except
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    payload = {"ok": True, "result": result.to_dict()}
    if args.output_json:
        Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
