#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bitable (飞书多维表格) data source adapter for multi-source-sync.

底层调用 lark-cli base +record-list（AIME 定制版），分页 100 条一批拉取全量。
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse


class BitableSourceError(RuntimeError):
    """Raised when Bitable data fetch fails or contract violated."""


PAGE_SIZE = 100


def _resolve_base_and_table(source_config: Dict[str, Any]) -> Tuple[str, str, Optional[str]]:
    """Resolve base_token / table_id / view_id from url or explicit fields."""
    base_token = str(source_config.get("base_token") or "").strip()
    table_id = str(source_config.get("table_id") or "").strip()
    view_id = source_config.get("view_id")

    base_url = source_config.get("base_url")
    if base_url:
        parsed = urlparse(base_url)
        path_parts = [p for p in parsed.path.split("/") if p]
        # /base/<base_token>
        if "base" in path_parts:
            idx = path_parts.index("base")
            if idx + 1 < len(path_parts):
                base_token = base_token or path_parts[idx + 1]
        # ?table=<table_id>&view=<view_id>
        qs = parse_qs(parsed.query or "")
        if not table_id and qs.get("table"):
            table_id = qs["table"][0]
        if view_id is None and qs.get("view"):
            view_id = qs["view"][0]

    if not base_token or not table_id:
        raise BitableSourceError(
            f"Bitable source needs base_token + table_id (from base_url or explicit fields). "
            f"resolved base_token={base_token!r}, table_id={table_id!r}"
        )
    return base_token, table_id, view_id


def _run_lark_cli(args: List[str]) -> Dict[str, Any]:
    cmd = ["lark-cli", *args, "--format", "json"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BitableSourceError(
            f"lark-cli command failed. exit={proc.returncode}\n"
            f"cmd: {' '.join(cmd)}\nstdout={proc.stdout[:800]}\nstderr={proc.stderr[:800]}"
        )
    text = proc.stdout.strip()
    start = text.find("{")
    if start < 0:
        raise BitableSourceError(f"lark-cli returned no JSON: {proc.stdout[:500]}")
    try:
        payload = json.loads(text[start:])
    except json.JSONDecodeError:
        end = text.rfind("}")
        payload = json.loads(text[start:end + 1])
    if not payload.get("ok", False):
        raise BitableSourceError(f"lark-cli envelope not ok: {json.dumps(payload, ensure_ascii=False)}")
    return payload


def fetch(source_config: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch all records from a Bitable source configuration.

    Args:
        source_config: dict with keys:
            - base_url OR (base_token + table_id) (required)
            - view_id: optional
            - filter: optional +record-list --filter DSL string
            - id: optional readable identifier

    Returns:
        dict:
          - columns: List[str]
          - rows: List[List[Any]]
          - records_fetched: int
          - source_meta: dict
    """
    if source_config.get("type") != "bitable":
        raise BitableSourceError(f"Not a bitable source: type={source_config.get('type')}")

    base_token, table_id, view_id = _resolve_base_and_table(source_config)
    filter_dsl = source_config.get("filter")
    source_id = source_config.get("id", "bitable")

    all_rows: List[List[Any]] = []
    fields: List[str] = []
    offset = 0

    while True:
        args = [
            "base",
            "+record-list",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--limit",
            str(PAGE_SIZE),
            "--offset",
            str(offset),
        ]
        if view_id:
            args += ["--view-id", str(view_id)]
        if filter_dsl:
            args += ["--filter", str(filter_dsl)]

        payload = _run_lark_cli(args)
        data = payload.get("data", {}) or {}
        page_fields = data.get("fields") or []
        page_rows = data.get("data") or []
        if not fields and page_fields:
            fields = [str(f) for f in page_fields]
        for raw_row in page_rows:
            row_values = []
            for idx in range(len(fields)):
                value = raw_row[idx] if idx < len(raw_row) else ""
                # Normalize list/dict to string for sheet-friendly output
                if isinstance(value, list):
                    value = "; ".join(str(v) for v in value if v is not None)
                elif isinstance(value, dict):
                    value = json.dumps(value, ensure_ascii=False, sort_keys=True)
                elif value is None:
                    value = ""
                row_values.append(value)
            all_rows.append(row_values)

        if not data.get("has_more", False):
            break
        offset += PAGE_SIZE

    if not fields:
        raise BitableSourceError(
            f"Bitable table returned no fields. base={base_token}, table={table_id}"
        )

    return {
        "columns": fields,
        "rows": all_rows,
        "records_fetched": len(all_rows),
        "source_meta": {
            "id": source_id,
            "base_token": base_token,
            "table_id": table_id,
            "view_id": view_id,
            "mode": "record_list",
        },
    }
