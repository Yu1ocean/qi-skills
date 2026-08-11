#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Main entry for multi-source-sync.

Pipeline:
1. Load config (JSON).
2. validate_sync_contract() — L3 physical assertion.
3. Fetch each source via sources/aeolus_source.py / sources/bitable_source.py.
4. Normalize + row-append into target.columns order.
5. sheet_writer.write_all() — header lock + data range clear + csv-put + updated_at anchor + RAW readback.
6. qa_check.run_cross_checks() — records_vs_rows / field_map_zero_loss / updated_at_anchor.
7. Optional: qa_check.maybe_run_zero_trust() if config.qa.engine=zero_trust.
8. Save output/qa_report_YYYYMMDD_HHMMSS.json.
9. Exit 0 on SUCCESS/WARN, exit 2 on FAIL.

Usage:
    python3 scripts/sync_main.py --config resources/example_weekly_friday.json
    python3 scripts/sync_main.py --config <path> --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from sources import aeolus_source, bitable_source  # noqa: E402
import sheet_writer  # noqa: E402
import qa_check  # noqa: E402


class SyncContractError(RuntimeError):
    """Raised when the sync config violates the physical contract."""


VALID_SOURCE_TYPES = {"aeolus", "bitable"}


def validate_sync_contract(config: Dict[str, Any]) -> None:
    """L3 physical assertion before any side effect."""
    if not isinstance(config, dict):
        raise SyncContractError(f"config must be dict, got {type(config).__name__}")
    sources = config.get("sources")
    if not isinstance(sources, list) or not sources:
        raise SyncContractError("config.sources must be a non-empty list")
    target = config.get("target")
    if not isinstance(target, dict):
        raise SyncContractError("config.target must be a dict")
    # Validate each source
    for i, src in enumerate(sources):
        if not isinstance(src, dict):
            raise SyncContractError(f"config.sources[{i}] must be a dict")
        stype = src.get("type")
        if stype not in VALID_SOURCE_TYPES:
            raise SyncContractError(
                f"config.sources[{i}].type={stype!r} not in {VALID_SOURCE_TYPES}"
            )
        field_map = src.get("field_map")
        if not isinstance(field_map, dict) or not field_map:
            raise SyncContractError(
                f"config.sources[{i}].field_map must be a non-empty dict; "
                f"got {type(field_map).__name__}"
            )
        value_map = src.get("value_map")
        if value_map is not None:
            if not isinstance(value_map, dict):
                raise SyncContractError(
                    f"config.sources[{i}].value_map must be a dict when provided; "
                    f"got {type(value_map).__name__}"
                )
            for col_name, mapping in value_map.items():
                if not isinstance(mapping, dict):
                    raise SyncContractError(
                        f"config.sources[{i}].value_map[{col_name!r}] must be a dict; "
                        f"got {type(mapping).__name__}"
                    )
    # sheet_writer will do its own contract check on target


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise SyncContractError(f"Config file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SyncContractError(f"Invalid JSON in {path}: {exc}")


def fetch_source(source_config: Dict[str, Any]) -> Dict[str, Any]:
    stype = source_config.get("type")
    if stype == "aeolus":
        return aeolus_source.fetch(source_config)
    if stype == "bitable":
        return bitable_source.fetch(source_config)
    raise SyncContractError(f"Unsupported source type: {stype}")


def normalize_rows(
    *, source_result: Dict[str, Any], field_map: Dict[str, str], target_columns: List[str]
) -> List[List[Any]]:
    """Map source rows onto target column order via field_map.

    field_map: {"上游字段名": "目标列名"}
    """
    source_columns: List[str] = source_result.get("columns") or []
    src_col_to_idx: Dict[str, int] = {name: i for i, name in enumerate(source_columns)}

    # Build target-col → source-col-index resolver
    target_to_src_idx: Dict[str, int] = {}
    for src_name, tgt_name in field_map.items():
        if src_name in src_col_to_idx:
            target_to_src_idx[tgt_name] = src_col_to_idx[src_name]

    normalized: List[List[Any]] = []
    for raw_row in source_result.get("rows") or []:
        new_row: List[Any] = []
        is_dict_row = isinstance(raw_row, dict)
        for tgt_col in target_columns:
            idx = target_to_src_idx.get(tgt_col)
            if idx is None:
                new_row.append("")
            elif is_dict_row:
                src_name = source_columns[idx]
                new_row.append(raw_row.get(src_name, ""))
            elif idx < len(raw_row):
                new_row.append(raw_row[idx])
            else:
                new_row.append("")
        normalized.append(new_row)
    return normalized


def apply_value_map(
    *,
    normalized_rows: List[List[Any]],
    field_map: Dict[str, str],
    target_columns: List[str],
    value_map: Dict[str, Dict[str, Any]] | None,
) -> Tuple[List[List[Any]], Dict[str, int]]:
    """Apply optional source-level value mapping after normalization.

    Resolution order for each value_map key:
    1. exact target column name
    2. source column name resolved through field_map
    """
    if not value_map:
        return normalized_rows, {}

    target_index = {name: idx for idx, name in enumerate(target_columns)}
    stats: Dict[str, int] = {}

    for value_map_key, mapping in value_map.items():
        target_name = value_map_key if value_map_key in target_index else field_map.get(value_map_key)
        if target_name not in target_index:
            raise SyncContractError(
                f"value_map key {value_map_key!r} could not be resolved to a target column"
            )
        idx = target_index[target_name]
        hit_count = 0
        for row in normalized_rows:
            if idx >= len(row):
                continue
            current_value = row[idx]
            mapped_value = mapping.get(str(current_value))
            if mapped_value is None:
                continue
            row[idx] = mapped_value
            hit_count += 1
        stats[value_map_key] = hit_count
    return normalized_rows, stats


def deduplicate_rows(
    *,
    rows: List[List[Any]],
    dedup_config: Dict[str, Any] | None,
    target_columns: List[str],
) -> Tuple[List[List[Any]], Dict[str, int]]:
    """Remove Sum rows and duplicates based on key column."""
    if not dedup_config:
        return rows, {"original": len(rows), "dropped_sum": 0, "duplicates": 0, "final": len(rows)}

    original_count = len(rows)
    dropped_sum = 0
    
    # 1. Drop Sum/Empty rows
    final_rows = []
    if dedup_config.get("drop_sum_rows"):
        try:
            shop_id_idx = target_columns.index("shop_id")
            for row in rows:
                val = str(row[shop_id_idx]).strip().lower()
                if val in {"", "sum", "总计", "null"}:
                    dropped_sum += 1
                    continue
                final_rows.append(row)
        except ValueError:
            final_rows = rows
    else:
        final_rows = rows

    # 2. Deduplicate
    dedup_key = dedup_config.get("key")
    if dedup_key and dedup_key in target_columns:
        idx = target_columns.index(dedup_key)
        seen = set()
        unique_rows = []
        for row in final_rows:
            key_val = str(row[idx])
            if key_val not in seen:
                unique_rows.append(row)
                seen.add(key_val)
        duplicates = len(final_rows) - len(unique_rows)
        final_rows = unique_rows
    else:
        duplicates = 0

    stats = {
        "original": original_count,
        "dropped_sum": dropped_sum,
        "duplicates": duplicates,
        "final": len(final_rows),
    }
    return final_rows, stats


def apply_field_format(
    *,
    rows: List[List[Any]],
    field_formats: Dict[str, str] | None,
    target_columns: List[str],
) -> Tuple[List[List[Any]], Dict[str, Dict[str, int]]]:
    """Clean numeric values: int_round / percent_no_decimal."""
    if not field_formats:
        return rows, {}

    target_index = {name: idx for idx, name in enumerate(target_columns)}
    stats: Dict[str, Dict[str, int]] = {}

    for col_name, fmt in field_formats.items():
        if col_name not in target_index:
            continue
        
        idx = target_index[col_name]
        col_stats = {"hit": 0, "null": 0}
        
        for row in rows:
            if idx >= len(row):
                continue
            
            val = row[idx]
            if val is None or val == "" or str(val).strip().lower() == "null":
                col_stats["null"] += 1
                row[idx] = ""
                continue
            
            try:
                num_val = float(val)
                if fmt == "int_round":
                    row[idx] = int(round(num_val))
                elif fmt == "percent_no_decimal":
                    if num_val <= 1:
                        row[idx] = f"{int(round(num_val * 100))}%"
                    else:
                        row[idx] = f"{int(round(num_val))}%"
                col_stats["hit"] += 1
            except (ValueError, TypeError):
                # Keep as is if not a number
                pass
        
        stats[col_name] = col_stats

    return rows, stats


def merge_rows(all_normalized: List[List[List[Any]]], strategy: str) -> List[List[Any]]:
    """Union-append merge (default). Extend here if new strategies added."""
    if strategy == "union_append" or not strategy:
        merged: List[List[Any]] = []
        for chunk in all_normalized:
            merged.extend(chunk)
        return merged
    raise SyncContractError(f"Unsupported merge_strategy: {strategy}")


def build_dry_run_plan(config: Dict[str, Any]) -> Dict[str, Any]:
    plan = {
        "mode": "dry_run",
        "sources": [
            {
                "id": s.get("id", f"source_{i}"),
                "type": s.get("type"),
                "url_or_base": s.get("url") or s.get("base_url") or s.get("base_token"),
                "field_map_size": len(s.get("field_map") or {}),
                "download_full": bool(s.get("download_full", False)),
            }
            for i, s in enumerate(config.get("sources", []))
        ],
        "target": {
            "sheet_url": config.get("target", {}).get("sheet_url"),
            "sheet_id": config.get("target", {}).get("sheet_id"),
            "columns_count": len(config.get("target", {}).get("columns") or []),
            "data_range": config.get("target", {}).get("data_range"),
            "updated_at_cell": config.get("target", {}).get("updated_at_cell"),
        },
        "merge_strategy": config.get("merge_strategy", "union_append"),
        "qa_engine": config.get("qa", {}).get("engine", "builtin"),
    }
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-source-sync entry.")
    parser.add_argument("--config", required=True, help="Path to JSON config file.")
    parser.add_argument("--dry-run", action="store_true", help="Only parse config and print plan.")
    parser.add_argument("--output-dir", default=str(SKILL_DIR / "output"), help="QA report output dir.")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        # Try relative to CWD first, then relative to skill dir
        if not config_path.exists():
            alt = SKILL_DIR / args.config
            if alt.exists():
                config_path = alt

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = (SKILL_DIR / args.output_dir).resolve() if not (Path.cwd() / args.output_dir).exists() else (Path.cwd() / args.output_dir).resolve()

    result: Dict[str, Any] = {
        "run_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "config_path": str(config_path.resolve()),
        "status": "FAIL",
        "errors": [],
    }

    try:
        config = load_config(config_path)
        validate_sync_contract(config)
    except Exception as exc:
        result["errors"].append(f"contract/load error: {exc}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    if args.dry_run:
        result["status"] = "DRY_RUN"
        result["plan"] = build_dry_run_plan(config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    target_columns: List[str] = [str(c) for c in config["target"]["columns"]]
    sources_results: List[Dict[str, Any]] = []
    value_map_applied: List[Dict[str, Any]] = []
    dedup_applied: List[Dict[str, Any]] = []
    all_normalized: List[List[List[Any]]] = []

    try:
        # Fetch each source
        for src_cfg in config["sources"]:
            fetched = fetch_source(src_cfg)
            sources_results.append(fetched)
            normalized = normalize_rows(
                source_result=fetched,
                field_map=src_cfg.get("field_map", {}),
                target_columns=target_columns,
            )
            # 1. Deduplicate
            normalized, dedup_stats = deduplicate_rows(
                rows=normalized,
                dedup_config=src_cfg.get("dedup"),
                target_columns=target_columns,
            )
            print(f"[sync] source {src_cfg.get('id')} dedup: {dedup_stats}")
            dedup_applied.append({"source_id": src_cfg.get("id", "?"), **dedup_stats})

            # 2. Value Map
            normalized, value_map_stats = apply_value_map(
                normalized_rows=normalized,
                field_map=src_cfg.get("field_map", {}),
                target_columns=target_columns,
                value_map=src_cfg.get("value_map"),
            )
            value_map_applied.append(
                {
                    "source_id": src_cfg.get("id", "?"),
                    "per_column": value_map_stats,
                }
            )
            all_normalized.append(normalized)

        merged = merge_rows(all_normalized, config.get("merge_strategy", "union_append"))

        # 3. Field Format
        merged, field_format_stats = apply_field_format(
            rows=merged,
            field_formats=config.get("field_format"),
            target_columns=target_columns,
        )
        print(f"[sync] global field_format applied to {len(field_format_stats)} columns")

        # Write to sheet
        write_result = sheet_writer.write_all(config["target"], merged)

        # Cross-checks
        cross_report = qa_check.run_cross_checks(
            config=config,
            sources_results=sources_results,
            write_result=write_result,
            expected_rows_after_transform=len(merged),
        )

        # Optional zero-trust
        zero_trust_report = None
        qa_engine = (config.get("qa", {}) or {}).get("engine", "builtin")
        if qa_engine == "zero_trust":
            zt_manifest = (config.get("qa", {}) or {}).get("manifest")
            zero_trust_report = qa_check.maybe_run_zero_trust(zt_manifest)

        # Assemble report
        report = {
            "run_id": result["run_id"],
            "config_path": result["config_path"],
            "status": cross_report["status"],
            "sources": [
                {
                    "id": src_cfg.get("id", f"source_{i}"),
                    "type": src_cfg.get("type"),
                    "records_fetched": fetched.get("records_fetched", 0),
                    "meta": fetched.get("source_meta", {}),
                }
                for i, (src_cfg, fetched) in enumerate(zip(config["sources"], sources_results))
            ],
            "target": {
                "sheet_url": config["target"].get("sheet_url"),
                "sheet_id": config["target"].get("sheet_id"),
                "rows_written": write_result.get("rows_written", 0),
                "updated_at": write_result.get("updated_at"),
                "updated_at_cell": write_result.get("updated_at_cell"),
                "data_range_cleared": write_result.get("data_range_cleared"),
            },
            "dedup_applied": dedup_applied,
            "value_map_applied": value_map_applied,
            "field_format_applied": field_format_stats,
            "cross_checks": cross_report["cross_checks"],
            "warnings": cross_report.get("warnings", []),
            "errors": cross_report.get("errors", []),
            "raw_readback": write_result.get("readback"),
            "zero_trust_qa": zero_trust_report,
        }

        # Save
        report_path = qa_check.save_qa_report(report, output_dir)
        report["qa_report_path"] = str(report_path)

        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] in {"PASS", "WARN"} else 2

    except Exception as exc:
        traceback.print_exc()
        result["errors"].append(f"runtime error: {exc}")
        result["sources_results_partial"] = [
            {"records_fetched": s.get("records_fetched", 0), "meta": s.get("source_meta", {})}
            for s in sources_results
        ]
        # best-effort partial QA save
        try:
            path = qa_check.save_qa_report(result, output_dir)
            result["qa_report_path"] = str(path)
        except Exception:
            pass
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
