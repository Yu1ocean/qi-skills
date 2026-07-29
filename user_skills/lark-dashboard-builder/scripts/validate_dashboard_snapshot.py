#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description="Validate dashboard readback values")
    p.add_argument("--input", required=True, help="JSON file with rows of numeric values")
    p.add_argument("--funnel-entry", type=int, default=-1, help="0-based entry column index")
    p.add_argument("--funnel-branches", default="", help="Comma-separated 0-based branch column indexes")
    return p.parse_args()


def to_number(v):
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    text = str(v).replace(',', '').strip()
    return float(text)


def main():
    args = parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    rows = payload.get("rows", payload)
    if not isinstance(rows, list):
        raise SystemExit("input must be a list or an object with rows")

    numeric_rows = [[to_number(v) for v in row] for row in rows]
    non_zero = any(any(v != 0 for v in row) for row in numeric_rows)
    report = {
        "row_count": len(numeric_rows),
        "all_zero": not non_zero,
        "funnel_checks": [],
    }

    if args.funnel_entry >= 0 and args.funnel_branches:
        branches = [int(x) for x in args.funnel_branches.split(',') if x.strip()]
        for idx, row in enumerate(numeric_rows):
            entry = row[args.funnel_entry]
            branch_sum = sum(row[i] for i in branches)
            diff = round(abs(branch_sum - entry), 6)
            report["funnel_checks"].append({
                "row_index": idx,
                "entry": entry,
                "branch_sum": branch_sum,
                "diff": diff,
                "passed": diff <= 1,
            })

    report["passed"] = (not report["all_zero"]) and all(x["passed"] for x in report["funnel_checks"])
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
