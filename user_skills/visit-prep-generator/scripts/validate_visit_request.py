#!/usr/bin/env python3
"""Runtime gates for visit-prep-generator before data fetch and document creation."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

def validate_visit_request(payload: dict[str, Any]) -> None:
    seller_name = str(payload.get("seller_name", "")).strip()
    seller_id = str(payload.get("seller_id", "")).strip()
    if not seller_name and not seller_id:
        raise ValueError("seller_name 或 seller_id 至少提供一个")

    period = payload.get("period_months", 6)
    if not isinstance(period, int) or period <= 0 or period > 24:
        raise ValueError("period_months 必须是 1-24 的整数")

    doc_date = str(payload.get("doc_date", "")).strip()
    if doc_date and len(doc_date) != 10:
        raise ValueError("doc_date 必须使用 YYYY-MM-DD 格式")


def validate_join_key(records: list[dict[str, Any]], source_name: str) -> None:
    if not isinstance(records, list):
        raise ValueError(f"{source_name} records 必须是列表")
    for idx, row in enumerate(records):
        if not isinstance(row, dict) or not str(row.get("global_seller_id", "")).strip():
            raise ValueError(f"{source_name} 第 {idx + 1} 行缺少 global_seller_id")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate visit-prep-generator request or records")
    parser.add_argument("--payload-json", required=True, help="JSON payload to validate")
    parser.add_argument("--mode", choices=["request", "records"], default="request")
    parser.add_argument("--source-name", default="aeolus")
    args = parser.parse_args()

    payload = json.loads(args.payload_json)
    if args.mode == "request":
        validate_visit_request(payload)
    else:
        validate_join_key(payload, args.source_name)
    print("VALID")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        raise
