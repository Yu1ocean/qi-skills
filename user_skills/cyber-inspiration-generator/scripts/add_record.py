"""Compatibility wrapper for creating one Lark Base/Bitable record via lark-cli.

This replaces the removed legacy `scripts.add_record` dependency with the
current MCP/lark-cli shortcut path. It intentionally accepts the old shape:
`{"fields": {...}}`, and returns the lark-cli JSON response.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, List


def add_record(app_token: str, table_id: str, record_json: str) -> Dict[str, Any]:
    payload = json.loads(record_json)
    fields_map = payload.get("fields", payload)
    if not isinstance(fields_map, dict):
        raise ValueError("record_json must be a JSON object or contain a fields object")

    fields: List[str] = list(fields_map.keys())
    row: List[Any] = [fields_map[name] for name in fields]
    body = {"fields": fields, "rows": [row]}

    cmd = [
        "lark-cli",
        "base",
        "+record-batch-create",
        "--base-token",
        app_token,
        "--table-id",
        table_id,
        "--json",
        json.dumps(body, ensure_ascii=False),
        "--format",
        "json",
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"lark-cli exited {proc.returncode}")
    stdout = proc.stdout.strip()
    json_start = stdout.find("{")
    if json_start < 0:
        raise RuntimeError(f"lark-cli returned non-json stdout: {stdout}")
    return json.loads(stdout[json_start:])
