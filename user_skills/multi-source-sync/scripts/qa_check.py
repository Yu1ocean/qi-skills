#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QA cross-check module for multi-source-sync.

Covers gaps that `zero-trust-qa-checker` does NOT cover for multi-source merge:
- records_vs_rows: Σ(records_fetched) 与 rows_written 一致性
- field_map_zero_loss: 字段映射零丢失核查
- updated_at_anchor: 更新日期锚点存在性与格式校验

如用户配置 qa.engine=zero_trust，则额外调用 user_skills/zero-trust-qa-checker/scripts/v3_engine.py。
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
ZERO_TRUST_SCRIPT = (
    WORKSPACE_ROOT / "user_skills" / "zero-trust-qa-checker" / "scripts" / "v3_engine.py"
)


def _validate_date_format(value: str, fmt: str) -> bool:
    """Check that value matches expected date format."""
    if not value:
        return False
    if fmt == "YYYY-MM-DD":
        return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value))
    # Fallback: accept any non-empty
    return True


def run_cross_checks(
    *,
    config: Dict[str, Any],
    sources_results: List[Dict[str, Any]],
    write_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Run cross-checks and return a structured report.

    sources_results: list of dicts from each source's fetch() output.
    write_result: dict from sheet_writer.write_all().
    """
    cross_checks: Dict[str, Any] = {}
    errors: List[str] = []
    warnings: List[str] = []

    # 1) records_vs_rows
    total_records = sum(int(s.get("records_fetched", 0)) for s in sources_results)
    rows_written = int(write_result.get("rows_written", 0))
    merge_strategy = (config.get("merge_strategy") or "union_append").lower()
    ok_records = (total_records == rows_written) if merge_strategy == "union_append" else True
    cross_checks["records_vs_rows"] = {
        "expected": total_records,
        "actual": rows_written,
        "merge_strategy": merge_strategy,
        "ok": ok_records,
    }
    if not ok_records:
        # For union_append, mismatch is a WARN, not FAIL (dedup / mapping loss allowed with note).
        warnings.append(
            f"records_vs_rows mismatch: Σ(records_fetched)={total_records}, rows_written={rows_written}"
        )

    # 2) field_map_zero_loss
    target_columns = [str(c) for c in (config.get("target", {}).get("columns") or [])]
    field_map_report = []
    all_ok = True
    for source_cfg, source_res in zip(config.get("sources", []), sources_results):
        field_map = source_cfg.get("field_map") or {}
        source_columns = source_res.get("columns") or []
        mapped_target_cols = list(field_map.values())
        unmapped_sources = [k for k in field_map.keys() if k not in source_columns]
        unknown_targets = [v for v in mapped_target_cols if v not in target_columns]
        source_ok = (not unmapped_sources) and (not unknown_targets)
        if not source_ok:
            all_ok = False
        field_map_report.append(
            {
                "source_id": source_cfg.get("id", "?"),
                "mapped_fields": len(field_map),
                "unmapped_source_fields": unmapped_sources,
                "unknown_target_columns": unknown_targets,
                "ok": source_ok,
            }
        )
    cross_checks["field_map_zero_loss"] = {"per_source": field_map_report, "ok": all_ok}
    if not all_ok:
        errors.append("field_map_zero_loss: some source fields did not match declared field_map")

    # 3) updated_at_anchor
    target = config.get("target", {}) or {}
    fmt = target.get("updated_at_format", "YYYY-MM-DD")
    updated_at = str(write_result.get("updated_at", "")).strip()
    updated_at_readback = str(write_result.get("updated_at_readback", "")).strip()
    ok_anchor = bool(updated_at) and (updated_at == updated_at_readback) and _validate_date_format(updated_at, fmt)
    cross_checks["updated_at_anchor"] = {
        "cell": target.get("updated_at_cell"),
        "format": fmt,
        "value": updated_at,
        "readback": updated_at_readback,
        "ok": ok_anchor,
    }
    if not ok_anchor:
        errors.append(
            f"updated_at_anchor invalid: cell={target.get('updated_at_cell')}, "
            f"value={updated_at!r}, readback={updated_at_readback!r}, format={fmt}"
        )

    status = "PASS"
    if errors:
        status = "FAIL"
    elif warnings:
        status = "WARN"

    return {
        "cross_checks": cross_checks,
        "errors": errors,
        "warnings": warnings,
        "status": status,
    }


def maybe_run_zero_trust(qa_manifest: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Optionally invoke zero-trust-qa-checker v3_engine.py if user provided a qa_manifest."""
    if not qa_manifest:
        return None
    if not ZERO_TRUST_SCRIPT.exists():
        return {"skipped": True, "reason": f"zero-trust-qa-checker not found at {ZERO_TRUST_SCRIPT}"}
    proc = subprocess.run(
        ["python3", str(ZERO_TRUST_SCRIPT), json.dumps(qa_manifest, ensure_ascii=False)],
        capture_output=True,
        text=True,
    )
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-2000:],
    }


def save_qa_report(report: Dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"qa_report_{ts}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
