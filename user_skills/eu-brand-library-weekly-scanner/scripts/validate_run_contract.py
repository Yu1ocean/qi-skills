#!/usr/bin/env python3
"""Validate pre-run contract for eu-brand-library-weekly-scanner.

This script intentionally performs only deterministic local assertions. It is a
runtime gate before side-effecting scan/write tasks and helps the calling agent
fail fast when critical URLs or parameters are wrong.
"""
from __future__ import annotations

import argparse
import re
from urllib.parse import urlparse

TARGET_TOKEN = "S91BsutWshyGK9tcAapmoeYkyQb"
CATEGORY_TOKEN = "shtcnYzaobnxlPVGox8hmSZ8b8d"
MP_RE = re.compile(r"^https://mp\.weixin\.qq\.com/s/[A-Za-z0-9_-]+")


def assert_lark_sheet(url: str, expected_token: str, label: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"{label} must use https: {url}")
    if not parsed.netloc.endswith("larkoffice.com"):
        raise ValueError(f"{label} must be a Lark/Feishu URL: {url}")
    if f"/sheets/{expected_token}" not in parsed.path:
        raise ValueError(f"{label} token mismatch, expected {expected_token}: {url}")


def assert_mp_article(url: str) -> None:
    if not MP_RE.match(url):
        raise ValueError(f"seed-url must be a real mp.weixin.qq.com article URL: {url}")


def validate_run_contract(target_sheet_url: str, category_sheet_url: str, seed_url: str, limit: int) -> None:
    assert_lark_sheet(target_sheet_url, TARGET_TOKEN, "target-sheet-url")
    assert_lark_sheet(category_sheet_url, CATEGORY_TOKEN, "category-sheet-url")
    assert_mp_article(seed_url)
    if limit < 0:
        raise ValueError("limit must be >= 0")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-sheet-url", required=True)
    parser.add_argument("--category-sheet-url", required=True)
    parser.add_argument("--seed-url", required=True)
    parser.add_argument("--limit", type=int, default=0, help="0 means this-week default; otherwise latest N articles")
    args = parser.parse_args()

    validate_run_contract(args.target_sheet_url, args.category_sheet_url, args.seed_url, args.limit)
    print("✅ contract_validated: target sheet, category sheet, seed article and limit are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
