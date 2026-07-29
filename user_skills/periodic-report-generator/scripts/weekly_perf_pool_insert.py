#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Weekly performance material pool zero-trust append.

Purpose:
- Optional companion for weekly reports: when --write-perf-pool is requested,
  append weekly highlights into the fixed performance material pool sheet.
- Keep data shape compatible with performance-review-writer material recall.

Contract:
- Target sheet headers must be exactly: 日期, 事项类型, 内容摘要, 来源报告链接
- Item type must be one of: GMV, 实验, 决策
- Writes are delegated to feishu-doc-writing-guide/scripts/safe_insert_sheet_row.py
- Read-after-write uses lark-sheets CLI and locates rows by exact tuple match.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_SHEET_URL = "https://bytedance.larkoffice.com/sheets/ECQ0sDwmbhDex9tcUSjlkU7Bgdh"
DEFAULT_SHEET_NAME = "Perf_Material_Pool"
DEFAULT_SHEET_ID = "3Mn6co"
REQUIRED_HEADERS = ["日期", "事项类型", "内容摘要", "来源报告链接"]
ALLOWED_TYPES = {"GMV", "实验", "决策"}


def workspace_root() -> Path:
    p = Path(__file__).resolve()
    for parent in [p, *p.parents]:
        if (parent / "user_skills").exists() and (parent / "inner_skills").exists():
            return parent
    return Path.cwd().resolve()


def lark_sheets_cli() -> Path:
    return workspace_root() / "inner_skills" / "lark-sheets" / "bin" / "lark-sheets-cli"


def run_cli(args: list[str]) -> dict[str, Any]:
    cmd = [str(lark_sheets_cli())] + args
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"lark-sheets-cli failed: {' '.join(cmd)}\nSTDERR:\n{proc.stderr}\nSTDOUT:\n{proc.stdout}")
    try:
        return json.loads(proc.stdout)
    except Exception as exc:
        raise RuntimeError(f"lark-sheets-cli returned non-json stdout: {proc.stdout[:800]}") from exc


def safe_insert_script() -> Path:
    p = workspace_root() / "user_skills" / "feishu-doc-writing-guide" / "scripts" / "safe_insert_sheet_row.py"
    if not p.exists():
        raise FileNotFoundError(f"safe_insert_sheet_row.py not found: {p}")
    return p


def normalize_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        # lark-sheets may return rich URL objects for link cells.
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("link") or item.get("text") or ""))
            else:
                parts.append(str(item))
        return "".join(parts).strip()
    return str(value).strip()


def read_values(sheet_url: str, sheet_id: str, range_a1: str) -> list[list[Any]]:
    res = run_cli([
        "sheets", "+read",
        "--url", sheet_url,
        "--sheet-id", sheet_id,
        "--range", range_a1,
    ])
    if not res.get("ok"):
        raise RuntimeError(f"read failed: {json.dumps(res, ensure_ascii=False)}")
    return res.get("data", {}).get("valueRange", {}).get("values", []) or []


def assert_schema(sheet_url: str, sheet_id: str) -> None:
    rows = read_values(sheet_url, sheet_id, f"{sheet_id}!A1:D1")
    headers = [normalize_cell(x) for x in (rows[0] if rows else [])]
    if headers != REQUIRED_HEADERS:
        raise RuntimeError(f"Perf_Material_Pool schema mismatch. expected={REQUIRED_HEADERS}, actual={headers}")


def parse_items(items_json: str) -> list[dict[str, str]]:
    try:
        obj = json.loads(items_json)
    except json.JSONDecodeError as exc:
        raise ValueError("--items-json must be a JSON array") from exc
    if not isinstance(obj, list) or not obj:
        raise ValueError("--items-json must be a non-empty JSON array")
    items: list[dict[str, str]] = []
    for idx, item in enumerate(obj, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"item {idx} must be an object")
        item_type = str(item.get("type") or item.get("事项类型") or "").strip()
        summary = str(item.get("summary") or item.get("内容摘要") or "").strip()
        source = str(item.get("source_report_link") or item.get("来源报告链接") or "").strip()
        date_str = str(item.get("date") or item.get("日期") or "").strip()
        if item_type not in ALLOWED_TYPES:
            raise ValueError(f"item {idx} type must be one of {sorted(ALLOWED_TYPES)}, got {item_type!r}")
        if not summary:
            raise ValueError(f"item {idx} summary is required")
        if not source:
            raise ValueError(f"item {idx} source_report_link is required")
        items.append({"date": date_str, "type": item_type, "summary": summary, "source": source})
    return items


def build_rows(items: list[dict[str, str]], default_date: str, source_report_link: str | None) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in items:
        date_str = item["date"] or default_date
        source = item["source"] or source_report_link or ""
        rows.append([date_str, item["type"], item["summary"], source])
    return rows


def append_rows_via_wrapper(sheet_url: str, sheet_name: str, rows: list[list[str]]) -> None:
    cmd = [
        sys.executable,
        str(safe_insert_script()),
        sheet_url,
        sheet_name,
        "0",
        json.dumps(rows, ensure_ascii=False),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"safe_insert_sheet_row.py failed\nSTDERR:\n{proc.stderr}\nSTDOUT:\n{proc.stdout}")


def locate_rows(sheet_url: str, sheet_id: str, expected_rows: list[list[str]]) -> list[int]:
    values = read_values(sheet_url, sheet_id, f"{sheet_id}!A1:D5000")
    normalized = [[normalize_cell(x) for x in row[:4]] for row in values]
    located: list[int] = []
    search_start = 2
    for expected in expected_rows:
        hit = None
        for row_idx, row in enumerate(normalized[search_start - 1 :], start=search_start):
            padded = row + [""] * (4 - len(row))
            if padded[:4] == expected:
                hit = row_idx
        if hit is None:
            raise RuntimeError(f"RAW read-after-write missing row: {expected}")
        located.append(hit)
        search_start = hit + 1
    return located


def main() -> int:
    parser = argparse.ArgumentParser(description="Append weekly highlights into performance material pool")
    parser.add_argument("--write-perf-pool", action="store_true", help="Enable write. Without this flag, script only validates payload and schema.")
    parser.add_argument("--sheet-url", default=DEFAULT_SHEET_URL)
    parser.add_argument("--sheet-name", default=DEFAULT_SHEET_NAME)
    parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--source-report-link", default="", help="Fallback source report link for all items")
    parser.add_argument("--items-json", required=True, help="JSON array: [{type, summary, source_report_link?, date?}]")
    args = parser.parse_args()

    items = parse_items(args.items_json)
    rows = build_rows(items, args.date, args.source_report_link or None)
    if any(not cell for row in rows for cell in row):
        raise ValueError(f"all four columns must be non-empty: {rows}")

    assert_schema(args.sheet_url, args.sheet_id)
    print("[Schema] ok", json.dumps(REQUIRED_HEADERS, ensure_ascii=False))
    print("[Payload]", json.dumps(rows, ensure_ascii=False))

    if not args.write_perf_pool:
        print("[DryRun] --write-perf-pool not set; skip write.")
        return 0

    append_rows_via_wrapper(args.sheet_url, args.sheet_name, rows)
    time.sleep(2)
    located = locate_rows(args.sheet_url, args.sheet_id, rows)
    print("[ReadAfterWrite] located_rows:", json.dumps(located, ensure_ascii=False))
    print("[OK] Perf material pool write verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
