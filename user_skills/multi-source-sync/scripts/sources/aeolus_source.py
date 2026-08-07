#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aeolus (风神) data source adapter for multi-source-sync.

底层调用 inner_skills/aeolus-platform-analysis 的 url_query.py / download_dashboard_data.py。
Region 从 URL 自动推断（CN/SG/VA/MYBD）。
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
AEOLUS_SKILL_DIR = WORKSPACE_ROOT / "inner_skills" / "aeolus-platform-analysis"


class AeolusSourceError(RuntimeError):
    """Raised when Aeolus data fetch fails or contract violated."""


def _infer_region_and_base_url(url: str, region_hint: Optional[str] = None) -> Tuple[str, str]:
    """Infer region + base URL from URL domain.

    Supported:
    - data.bytedance.net              → CN
    - aeolus-sg.bytedance.net         → SG
    - aeolus-va.bytedance.net         → VA
    - aeolus-va.tiktok-row.net       → VA
    - aeolus-mybd.bytedance.net       → MYBD
    """
    if region_hint:
        region = region_hint.upper().strip()
    else:
        host = urlparse(url).netloc.lower()
        if "aeolus-sg" in host:
            region = "SG"
        elif "aeolus-va" in host or "-va" in host or "virginia" in host or "tiktok-row.net" in host:
            region = "VA"
        elif "aeolus-mybd" in host or "-mybd" in host:
            region = "MYBD"
        else:
            region = "CN"

    region_to_base = {
        "CN": "https://data.bytedance.net",
        "SG": "https://aeolus-sg.bytedance.net",
        "VA": "https://aeolus-va.tiktok-row.net",
        "MYBD": "https://aeolus-mybd.sinf.net",
    }
    if region not in region_to_base:
        raise AeolusSourceError(f"Unsupported aeolus region: {region}")

    return region, region_to_base[region]


def _run_aeolus_script(script_name: str, args: List[str]) -> Tuple[str, str, int]:
    """Run an aeolus platform script and capture stdout/stderr/exit_code."""
    script_path = AEOLUS_SKILL_DIR / "scripts" / script_name
    if not script_path.exists():
        raise AeolusSourceError(f"Aeolus script not found: {script_path}")
    cmd = ["python3", str(script_path), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.stdout, proc.stderr, proc.returncode


def _parse_url_query_output(stdout: str) -> Dict[str, Any]:
    """Parse url_query.py JSON output (may include rawFile pointer if truncated)."""
    text = stdout.strip()
    start = text.find("{")
    if start < 0:
        raise AeolusSourceError(f"url_query.py produced no JSON output: {stdout[:500]}")
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        # Try to find a complete JSON object from the end
        end = text.rfind("}")
        if end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError as exc:
                raise AeolusSourceError(f"Unable to parse url_query.py JSON: {exc}\nstdout={stdout[:1000]}")
        raise AeolusSourceError(f"Unable to parse url_query.py JSON. stdout={stdout[:1000]}")


def _read_csv_rows(csv_path: Path) -> Tuple[List[str], List[List[str]]]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def fetch(source_config: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch data from an Aeolus source configuration.

    Args:
        source_config: dict with keys:
            - url: aeolus URL (required)
            - region: optional (auto-inferred from URL)
            - download_full: bool, default False → 走 download_dashboard_data.py
            - filters: list of "字段=值" strings, optional
            - report_id: optional (dashboard mode)
            - id: optional readable identifier

    Returns:
        dict:
          - columns: List[str]
          - rows: List[List[Any]]        (2D data rows)
          - records_fetched: int
          - source_meta: dict            (region, url, mode)
    """
    if source_config.get("type") != "aeolus":
        raise AeolusSourceError(f"Not an aeolus source: type={source_config.get('type')}")

    url = source_config.get("url", "").strip()
    if not url:
        raise AeolusSourceError("aeolus source missing 'url'")

    region, base_url = _infer_region_and_base_url(url, source_config.get("region"))
    filters = source_config.get("filters") or []
    download_full = bool(source_config.get("download_full", False))
    report_id = source_config.get("report_id")

    if download_full:
        return _fetch_via_download(
            url=url,
            base_url=base_url,
            region=region,
            filters=filters,
            report_id=report_id,
            source_id=source_config.get("id", "aeolus"),
        )
    return _fetch_via_url_query(
        url=url,
        base_url=base_url,
        region=region,
        filters=filters,
        report_id=report_id,
        source_id=source_config.get("id", "aeolus"),
    )


def _fetch_via_url_query(
    url: str, base_url: str, region: str, filters: List[str], report_id: Optional[str], source_id: str
) -> Dict[str, Any]:
    args = ["--url", url, "--base-url", base_url]
    if report_id:
        args += ["--report-id", str(report_id)]
    for f in filters:
        args += ["--filters", f]

    stdout, stderr, exit_code = _run_aeolus_script("url_query.py", args)
    # Even on exit_code=1 (data_truncated), stdout is still valid JSON with rawFile pointer
    if not stdout.strip():
        raise AeolusSourceError(
            f"url_query.py returned no stdout. exit={exit_code}, stderr={stderr[:500]}"
        )
    payload = _parse_url_query_output(stdout)

    columns = payload.get("columns") or []
    rows = payload.get("rows") or []
    data_truncated = payload.get("data_truncated", False)
    raw_file = payload.get("rawFile")

    # If truncated, read from rawFile for full data
    if data_truncated and raw_file and Path(raw_file).exists():
        try:
            with Path(raw_file).open("r", encoding="utf-8") as f:
                raw_payload = json.load(f)
            columns = raw_payload.get("columns") or columns
            rows = raw_payload.get("rows") or rows
        except (json.JSONDecodeError, OSError) as exc:
            raise AeolusSourceError(
                f"Failed to read rawFile for full data: {exc}. Consider setting download_full=true."
            )

    if not columns:
        raise AeolusSourceError(
            f"aeolus url_query returned no columns. exit={exit_code}, payload keys={list(payload.keys())}"
        )

    return {
        "columns": [str(c) for c in columns],
        "rows": rows,
        "records_fetched": len(rows),
        "source_meta": {
            "id": source_id,
            "region": region,
            "url": url,
            "mode": "url_query",
            "data_truncated": data_truncated,
        },
    }


def _fetch_via_download(
    url: str, base_url: str, region: str, filters: List[str], report_id: Optional[str], source_id: str
) -> Dict[str, Any]:
    args = ["--url", url, "--base-url", base_url]
    if report_id:
        args += ["--chart-id", str(report_id)]
    for f in filters:
        args += ["--filters", f]

    stdout, stderr, exit_code = _run_aeolus_script("download_dashboard_data.py", args)
    if exit_code != 0:
        raise AeolusSourceError(
            f"download_dashboard_data.py failed. exit={exit_code}\nstdout={stdout[:800]}\nstderr={stderr[:800]}"
        )
    # download_dashboard_data.py outputs JSON with a `file` path pointing to CSV
    text = stdout.strip()
    start = text.find("{")
    if start < 0:
        raise AeolusSourceError(f"download_dashboard_data.py produced no JSON: {stdout[:500]}")
    try:
        payload = json.loads(text[start:])
    except json.JSONDecodeError:
        end = text.rfind("}")
        payload = json.loads(text[start:end + 1])

    csv_file = payload.get("file") or payload.get("csvFile") or payload.get("filePath")
    if not csv_file or not Path(csv_file).exists():
        raise AeolusSourceError(
            f"download_dashboard_data.py did not produce a CSV file. payload={payload}"
        )
    columns, rows = _read_csv_rows(Path(csv_file))
    if not columns:
        raise AeolusSourceError(f"Downloaded CSV has no header: {csv_file}")

    return {
        "columns": columns,
        "rows": rows,
        "records_fetched": len(rows),
        "source_meta": {
            "id": source_id,
            "region": region,
            "url": url,
            "mode": "download_full",
            "csv_file": csv_file,
        },
    }
