#!/usr/bin/env python3
"""Batch fetch Aeolus seller data for visit-prep-generator.

This wrapper is intentionally the only supported Aeolus-fetch entrypoint for the
visit-prep-generator skill. It calls the built-in aeolus-platform-analysis skill's
url_query.py script directly, keeps per-query timeout bounded, and makes every
failure visible in the returned JSON instead of raising across the whole batch.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

EU_RID = "5466004"
US_RID = "5991071"
SID = "2770378"
APP_ID = "555771"
AEOLUS_HOST = "https://aeolus-va.tiktok-row.net"
EU_URL = (
    f"{AEOLUS_HOST}/pages/dataQuery?appId={APP_ID}&dashboardId=511872"
    f"&id=2476255319&isDefault=1&reportQuerySchemaKey=1108ed5b-0140-4a00-b379-435bddfb7cbf"
    f"&rid={EU_RID}&sid={SID}&waitForDataReady=0"
)
US_URL = f"{AEOLUS_HOST}/pages/dataQuery?appId={APP_ID}&rid={US_RID}&sid={SID}"
DEFAULT_TIMEOUT_SECONDS = 45
DEFAULT_MAX_WORKERS = 3


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _aeolus_script() -> Path:
    return _repo_root() / "inner_skills" / "aeolus-platform-analysis" / "scripts" / "url_query.py"


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    candidates = [
        payload.get("rows"),
        payload.get("data"),
        payload.get("sampleRows"),
    ]
    for value in candidates:
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    # Some aeolus wrappers return nested result blocks.
    for key in ("result", "payload"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            rows = _extract_rows(nested)
            if rows:
                return rows
    return []


def _query_source(seller_id: str, source: str, url: str, timeout_seconds: int) -> dict[str, Any]:
    script_path = _aeolus_script()
    result: dict[str, Any] = {
        "source": source,
        "rid": EU_RID if source == "eu_uk_jp" else US_RID,
        "sid": SID,
        "status": "pending",
        "rows": [],
        "row_count": 0,
        "error": "",
        "warning": "",
    }
    cmd = [
        sys.executable,
        str(script_path),
        "--url",
        url,
        "--filters",
        f"global_seller_id={seller_id}",
        "--top-n",
        "1000",
    ]
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(script_path.parent),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        result.update({"status": "timeout", "warning": "⚠️ 超时", "error": "⚠️ 超时"})
        return result
    except Exception as exc:  # noqa: BLE001 - all failures must be materialized.
        result.update({"status": "failed", "error": str(exc)})
        return result

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if not stdout:
        result.update({"status": "failed", "error": stderr or f"aeolus exited with {completed.returncode}"})
        return result
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        result.update({"status": "failed", "error": f"JSON parse failed: {exc}; stderr={stderr[:500]}"})
        return result

    rows = _extract_rows(payload)
    result.update(
        {
            "status": "ok" if completed.returncode in (0, 1) else "failed",
            "rows": rows,
            "row_count": len(rows),
            "raw_summary": {k: payload.get(k) for k in ("total", "totalRows", "data_truncated", "truncation_reason", "rawFile") if k in payload},
            "stderr": stderr[-1000:] if stderr else "",
        }
    )
    if completed.returncode not in (0, 1):
        result["error"] = stderr or f"aeolus exited with {completed.returncode}"
    if source == "us" and len(rows) == 0 and not result.get("error"):
        result["warning"] = "⚠️ 暂无 US 风神数据"
    return result


def _fetch_one(seller_id: str, timeout_seconds: int) -> dict[str, Any]:
    seller_result: dict[str, Any] = {
        "seller_id": seller_id,
        "status": "ok",
        "seller_name": "",
        "eu_uk_jp": {},
        "us": {},
        "error": "",
        "warnings": [],
    }
    try:
        eu_result = _query_source(seller_id, "eu_uk_jp", EU_URL, timeout_seconds)
        us_result = _query_source(seller_id, "us", US_URL, timeout_seconds)
        seller_result["eu_uk_jp"] = eu_result
        seller_result["us"] = us_result
        rows = eu_result.get("rows") or us_result.get("rows") or []
        if rows:
            first = rows[0]
            for key in ("seller_name", "shop_name", "global_seller_name", "merchant_name"):
                value = str(first.get(key, "")).strip()
                if value:
                    seller_result["seller_name"] = value
                    break
        warnings = [r.get("warning") for r in (eu_result, us_result) if r.get("warning")]
        seller_result["warnings"] = warnings
        errors = [r.get("error") for r in (eu_result, us_result) if r.get("error")]
        if errors:
            seller_result["status"] = "partial_failed"
            seller_result["error"] = " | ".join(errors)
        if eu_result.get("status") == "timeout" or us_result.get("status") == "timeout":
            seller_result["status"] = "timeout"
            if "⚠️ 超时" not in seller_result["warnings"]:
                seller_result["warnings"].append("⚠️ 超时")
    except Exception as exc:  # noqa: BLE001 - never break the batch.
        seller_result.update({"status": "failed", "error": str(exc)})
    return seller_result


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch EU/UK/JP and US Aeolus data for seller_id batch")
    parser.add_argument("--seller-ids", nargs="+", required=True, help="seller_id list")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument("--output", help="Optional output JSON path")
    args = parser.parse_args()

    max_workers = max(1, min(args.max_workers, DEFAULT_MAX_WORKERS))
    seller_ids = [str(x).strip() for x in args.seller_ids if str(x).strip()]
    output: dict[str, Any] = {
        "contract": {
            "timeout_seconds": args.timeout_seconds,
            "max_workers": max_workers,
            "sources": {
                "eu_uk_jp": {"rid": EU_RID, "sid": SID, "url": EU_URL},
                "us": {"rid": US_RID, "sid": SID, "url": US_URL},
            },
        },
        "results": [],
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_fetch_one, seller_id, args.timeout_seconds): seller_id for seller_id in seller_ids}
        for future in concurrent.futures.as_completed(future_map):
            try:
                output["results"].append(future.result())
            except Exception as exc:  # defensive; individual worker already catches.
                output["results"].append({"seller_id": future_map[future], "status": "failed", "error": str(exc)})
    output["results"].sort(key=lambda row: seller_ids.index(row.get("seller_id", "")) if row.get("seller_id", "") in seller_ids else 999999)
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
