#!/usr/bin/env python3
import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description="Profile a bottom-sheet snapshot for dashboard scouting")
    p.add_argument("--input", required=True, help="CSV snapshot path exported from Lark sheet")
    p.add_argument("--header-row", type=int, default=1, help="1-based header row index")
    p.add_argument("--columns", default="", help="Comma-separated Excel column letters to inspect, e.g. B,Q,V")
    p.add_argument("--topn", type=int, default=50, help="Max distinct values to print per column")
    return p.parse_args()


def excel_col_to_index(col: str) -> int:
    col = col.strip().upper()
    if not col:
        raise ValueError("empty column")
    n = 0
    for ch in col:
        if not ('A' <= ch <= 'Z'):
            raise ValueError(f"invalid Excel column: {col}")
        n = n * 26 + (ord(ch) - ord('A') + 1)
    return n - 1


def normalize(v):
    if v is None:
        return ""
    return str(v).strip()


def main():
    args = parse_args()
    path = Path(args.input)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) < args.header_row:
        raise SystemExit("header row out of range")

    header = rows[args.header_row - 1]
    body = rows[args.header_row:]
    if not header:
        raise SystemExit("empty header")

    if args.columns:
        chosen = [c.strip().upper() for c in args.columns.split(",") if c.strip()]
    else:
        chosen = []
        for i, _ in enumerate(header):
            n = i + 1
            letters = ""
            while n:
                n, r = divmod(n - 1, 26)
                letters = chr(ord('A') + r) + letters
            chosen.append(letters)

    report = {
        "row_count": len(body),
        "header_row": args.header_row,
        "column_mapping": [],
        "profiles": [],
    }

    for col in chosen:
        idx = excel_col_to_index(col)
        if idx >= len(header):
            continue
        name = normalize(header[idx]) or f"{col}_UNNAMED"
        values = [normalize(r[idx]) if idx < len(r) else "" for r in body]
        non_empty = [v for v in values if v != ""]
        distinct = Counter(non_empty)
        non_empty_ratio = round((len(non_empty) / len(values)) if values else 0, 4)
        report["column_mapping"].append({"column": col, "header": name})
        report["profiles"].append({
            "column": col,
            "header": name,
            "total_rows": len(values),
            "non_empty_rows": len(non_empty),
            "non_empty_ratio": non_empty_ratio,
            "distinct_non_empty_count": len(distinct),
            "distinct_values": [
                {"value": value, "count": count}
                for value, count in distinct.most_common(args.topn)
            ],
            "p3_non_empty_trap": non_empty_ratio > 0.8,
        })

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
