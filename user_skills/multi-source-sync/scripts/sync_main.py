#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Main entry for multi-source-sync.

v2.0 adds dual-sheet architecture:
- Sheet1 master: patch/update existing rows + append new rows + never delete rows
- Sheet2 snapshot: full overwrite of current A:K dataset
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from sources import aeolus_source, bitable_source  # noqa: E402
import qa_check  # noqa: E402
import sheet_writer  # noqa: E402


class SyncContractError(RuntimeError):
    """Raised when the sync config violates the physical contract."""


VALID_SOURCE_TYPES = {"aeolus", "bitable"}
MASTER_EXTRA_HEADERS = {"L1": "is_new", "M1": "入库时间"}
SNAPSHOT_MAX_ROWS = 10000


def validate_sync_contract(config: Dict[str, Any]) -> None:
    if not isinstance(config, dict):
        raise SyncContractError(f"config must be dict, got {type(config).__name__}")
    sources = config.get("sources")
    if not isinstance(sources, list) or not sources:
        raise SyncContractError("config.sources must be a non-empty list")
    target = config.get("target")
    if not isinstance(target, dict):
        raise SyncContractError("config.target must be a dict")
    for i, src in enumerate(sources):
        if not isinstance(src, dict):
            raise SyncContractError(f"config.sources[{i}] must be a dict")
        stype = src.get("type")
        if stype not in VALID_SOURCE_TYPES:
            raise SyncContractError(f"config.sources[{i}].type={stype!r} not in {VALID_SOURCE_TYPES}")
        field_map = src.get("field_map")
        if not isinstance(field_map, dict) or not field_map:
            raise SyncContractError(
                f"config.sources[{i}].field_map must be a non-empty dict; got {type(field_map).__name__}"
            )
        value_map = src.get("value_map")
        if value_map is not None and not isinstance(value_map, dict):
            raise SyncContractError(f"config.sources[{i}].value_map must be a dict when provided")

    required_target_keys = ["sheet_url", "sheet1_id", "sheet2_id", "columns", "mode"]
    missing = [k for k in required_target_keys if not target.get(k)]
    if missing:
        raise SyncContractError(f"config.target missing required keys: {missing}")
    if target.get("mode") != "diff_patch_v2":
        raise SyncContractError("config.target.mode must be 'diff_patch_v2'")
    if not isinstance(target.get("columns"), list) or len(target["columns"]) != 11:
        raise SyncContractError("config.target.columns must be a list of 11 columns (A:K)")


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise SyncContractError(f"Config file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SyncContractError(f"Invalid JSON in {path}: {exc}")


def fetch_source(source_config: Dict[str, Any]) -> Dict[str, Any]:
    stype = source_config.get("type")
    if stype == "aeolus":
        return aeolus_source.fetch(source_config)
    if stype == "bitable":
        return bitable_source.fetch(source_config)
    raise SyncContractError(f"Unsupported source type: {stype}")


def normalize_rows(*, source_result: Dict[str, Any], field_map: Dict[str, str], target_columns: List[str]) -> List[List[Any]]:
    source_columns: List[str] = source_result.get("columns") or []
    src_col_to_idx: Dict[str, int] = {name: i for i, name in enumerate(source_columns)}
    target_to_src_idx: Dict[str, int] = {}
    for src_name, tgt_name in field_map.items():
        if src_name in src_col_to_idx:
            target_to_src_idx[tgt_name] = src_col_to_idx[src_name]

    normalized: List[List[Any]] = []
    for raw_row in source_result.get("rows") or []:
        row_out: List[Any] = []
        is_dict_row = isinstance(raw_row, dict)
        for tgt_col in target_columns:
            idx = target_to_src_idx.get(tgt_col)
            if idx is None:
                row_out.append("")
            elif is_dict_row:
                row_out.append(raw_row.get(source_columns[idx], ""))
            elif idx < len(raw_row):
                row_out.append(raw_row[idx])
            else:
                row_out.append("")
        normalized.append(row_out)
    return normalized


def apply_value_map(*, normalized_rows: List[List[Any]], field_map: Dict[str, str], target_columns: List[str], value_map: Dict[str, Dict[str, Any]] | None) -> Tuple[List[List[Any]], Dict[str, int]]:
    if not value_map:
        return normalized_rows, {}
    target_index = {name: idx for idx, name in enumerate(target_columns)}
    stats: Dict[str, int] = {}
    for value_map_key, mapping in value_map.items():
        target_name = value_map_key if value_map_key in target_index else field_map.get(value_map_key)
        if target_name not in target_index:
            raise SyncContractError(f"value_map key {value_map_key!r} could not be resolved to a target column")
        idx = target_index[target_name]
        hit_count = 0
        for row in normalized_rows:
            mapped_value = mapping.get(str(row[idx]))
            if mapped_value is None:
                continue
            row[idx] = mapped_value
            hit_count += 1
        stats[value_map_key] = hit_count
    return normalized_rows, stats


def deduplicate_rows(*, rows: List[List[Any]], dedup_config: Dict[str, Any] | None, target_columns: List[str]) -> Tuple[List[List[Any]], Dict[str, int]]:
    if not dedup_config:
        return rows, {"original": len(rows), "dropped_sum": 0, "duplicates": 0, "final": len(rows)}

    original_count = len(rows)
    final_rows: List[List[Any]] = []
    dropped_sum = 0
    if dedup_config.get("drop_sum_rows"):
        shop_id_idx = target_columns.index("shop_id")
        for row in rows:
            val = str(row[shop_id_idx]).strip().lower()
            if val in {"", "sum", "总计", "null"}:
                dropped_sum += 1
                continue
            final_rows.append(row)
    else:
        final_rows = list(rows)

    dedup_key = dedup_config.get("key")
    duplicates = 0
    if dedup_key and dedup_key in target_columns:
        idx = target_columns.index(dedup_key)
        seen = set()
        unique_rows = []
        for row in final_rows:
            key_val = str(row[idx]).strip()
            if key_val in seen:
                duplicates += 1
                continue
            seen.add(key_val)
            unique_rows.append(row)
        final_rows = unique_rows

    return final_rows, {
        "original": original_count,
        "dropped_sum": dropped_sum,
        "duplicates": duplicates,
        "final": len(final_rows),
    }


def apply_field_format(*, rows: List[List[Any]], field_formats: Dict[str, str] | None, target_columns: List[str]) -> Tuple[List[List[Any]], Dict[str, Dict[str, int]]]:
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
            val = row[idx]
            if val is None or val == "" or str(val).strip().lower() == "null":
                row[idx] = ""
                col_stats["null"] += 1
                continue
            try:
                num_val = float(val)
                if fmt == "int_round":
                    row[idx] = int(round(num_val))
                elif fmt == "percent_no_decimal":
                    row[idx] = f"{int(round(num_val * 100 if num_val <= 1 else num_val))}%"
                col_stats["hit"] += 1
            except (TypeError, ValueError):
                pass
        stats[col_name] = col_stats
    return rows, stats


def merge_rows(all_normalized: List[List[List[Any]]], strategy: str) -> List[List[Any]]:
    if strategy in {"union_append", ""}:
        merged: List[List[Any]] = []
        for chunk in all_normalized:
            merged.extend(chunk)
        return merged
    raise SyncContractError(f"Unsupported merge_strategy: {strategy}")


def row_to_dict(row: List[Any], columns: List[str]) -> Dict[str, Any]:
    return {col: (row[i] if i < len(row) else "") for i, col in enumerate(columns)}


def normalize_current_rows(rows: List[List[Any]], columns: List[str], today: str) -> List[Dict[str, Any]]:
    normalized = []
    seen = set()
    for row in rows:
        item = row_to_dict(row, columns)
        shop_id = str(item.get("shop_id", "")).strip()
        if not shop_id or shop_id in seen:
            continue
        seen.add(shop_id)
        item["shop_id"] = shop_id
        item["shop_status"] = str(item.get("shop_status", "")).strip()
        item["更新时间"] = today
        normalized.append(item)
    return normalized


def read_sheet_snapshot(sheet_url: str, sheet_id: str, columns: List[str]) -> Dict[str, Dict[str, Any]]:
    rows = sheet_writer.read_range_matrix(sheet_url, sheet_id, f"A2:K{SNAPSHOT_MAX_ROWS}")
    snapshot: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not row:
            continue
        shop_id = str(row[0] if len(row) > 0 else "").strip()
        if not shop_id:
            continue
        row_padded = list(row) + [""] * (len(columns) - len(row))
        snapshot[shop_id] = {columns[i]: row_padded[i] for i in range(len(columns))}
    return snapshot


def read_sheet1_master(sheet_url: str, sheet_id: str) -> Dict[str, Dict[str, Any]]:
    rows = sheet_writer.read_range_matrix(sheet_url, sheet_id, f"A2:M{SNAPSHOT_MAX_ROWS}")
    master: Dict[str, Dict[str, Any]] = {}
    for idx, row in enumerate(rows, start=2):
        if not row:
            continue
        shop_id = str(row[0] if len(row) > 0 else "").strip()
        if not shop_id:
            continue
        master[shop_id] = {
            "row_index": idx,
            "entry_date_M": str(row[12] if len(row) > 12 else "").strip(),
            "shop_status": str(row[9] if len(row) > 9 else "").strip(),
        }
    return master


def compute_diff(current_rows: List[Dict[str, Any]], prev_snapshot: Dict[str, Dict[str, Any]], master: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    current_map = {str(row["shop_id"]): row for row in current_rows}
    current_ids = set(current_map.keys())
    prev_ids = set(prev_snapshot.keys())
    master_ids = set(master.keys())

    new_ids = sorted(current_ids - master_ids)
    existing_ids = sorted(current_ids & master_ids)
    removed_ids = sorted(master_ids - current_ids)

    status_changes = []
    for shop_id in sorted(current_ids & prev_ids):
        prev_status = str(prev_snapshot.get(shop_id, {}).get("shop_status", "")).strip()
        curr_status = str(current_map.get(shop_id, {}).get("shop_status", "")).strip()
        if prev_status and curr_status and prev_status != curr_status:
            status_changes.append({"shop_id": shop_id, "from": prev_status, "to": curr_status})

    return {
        "current_map": current_map,
        "new_shops": [current_map[sid] for sid in new_ids],
        "existing_shops": [current_map[sid] for sid in existing_ids],
        "removed_shops": [{"shop_id": sid, **master[sid]} for sid in removed_ids],
        "status_changes": status_changes,
        "summary": {
            "current": len(current_ids),
            "prev_snapshot": len(prev_ids),
            "master": len(master_ids),
            "existing": len(existing_ids),
            "new": len(new_ids),
            "removed": len(removed_ids),
            "status_changes": len(status_changes),
            "non_active": sum(1 for row in current_rows if str(row.get("shop_status", "")).strip().lower() != "active"),
        },
    }


def ensure_sheet_headers(target: Dict[str, Any]) -> Dict[str, Any]:
    sheet_url = target["sheet_url"]
    headers_ak = {f"{sheet_writer._col_letter(i)}1": col for i, col in enumerate(target["columns"])}
    master_header_result = sheet_writer.ensure_header_cells(
        sheet_url,
        target["sheet1_id"],
        {**headers_ak, **MASTER_EXTRA_HEADERS},
    )
    snapshot_header_result = sheet_writer.ensure_header_cells(
        sheet_url,
        target["sheet2_id"],
        headers_ak,
    )
    return {"sheet1": master_header_result, "sheet2": snapshot_header_result}


def build_master_row(row: Dict[str, Any], today: str, entry_date: str, is_new: int) -> List[Any]:
    return [
        row.get("shop_id", ""),
        row.get("shop_name", ""),
        row.get("US行业", ""),
        row.get("US AM", ""),
        row.get("US Live AM", ""),
        row.get("直播日均GMV", ""),
        row.get("竞拍日均GMV", ""),
        row.get("竞拍渗透", ""),
        row.get("竞拍日均UV", ""),
        row.get("shop_status", ""),
        today,
        is_new,
        entry_date,
    ]


def write_sheet1_patch(
    *,
    target: Dict[str, Any],
    diff: Dict[str, Any],
    master: Dict[str, Dict[str, Any]],
    today: str,
) -> Dict[str, Any]:
    sheet_url = target["sheet_url"]
    sheet_id = target["sheet1_id"]

    existing_records = []
    existing_m_fill = []
    for row in diff["existing_shops"]:
        shop_id = row["shop_id"]
        master_row = master[shop_id]
        row_index = int(master_row["row_index"])
        existing_records.append(
            {
                "row_index": row_index,
                "values": [
                    row.get("shop_name", ""),
                    row.get("US行业", ""),
                    row.get("US AM", ""),
                    row.get("US Live AM", ""),
                    row.get("直播日均GMV", ""),
                    row.get("竞拍日均GMV", ""),
                    row.get("竞拍渗透", ""),
                    row.get("竞拍日均UV", ""),
                    row.get("shop_status", ""),
                    today,
                    0,
                ],
            }
        )
        if not str(master_row.get("entry_date_M", "")).strip():
            existing_m_fill.append({"row_index": row_index, "values": [today]})

    removed_records = []
    for removed in diff["removed_shops"]:
        removed_records.append({"row_index": int(removed["row_index"]), "values": ["removed", 0]})

    last_row = sheet_writer.get_last_non_empty_row(sheet_url, sheet_id, "A", "M")
    append_start_row = max(last_row + 1, 2)
    new_rows = [build_master_row(row, today, today, 1) for row in diff["new_shops"]]

    for group in sheet_writer.group_consecutive_rows(existing_records):
        sheet_writer.write_matrix(sheet_url, sheet_id, f"B{group['start_row']}", group["rows"])
    for group in sheet_writer.group_consecutive_rows(existing_m_fill):
        sheet_writer.write_matrix(sheet_url, sheet_id, f"M{group['start_row']}", group["rows"])
    for group in sheet_writer.group_consecutive_rows(removed_records):
        sheet_writer.write_matrix(sheet_url, sheet_id, f"J{group['start_row']}", group["rows"])
    if new_rows:
        sheet_writer.write_matrix(sheet_url, sheet_id, f"A{append_start_row}", new_rows)

    sheet_writer.write_updated_at(sheet_url, sheet_id, "K2", today)

    return {
        "existing_patched": len(existing_records),
        "existing_entry_date_filled": len(existing_m_fill),
        "removed_patched": len(removed_records),
        "new_appended": len(new_rows),
        "append_start_row": append_start_row,
        "updated_at": today,
        "updated_at_cell": "K2",
    }


def write_sheet2_full_overwrite(*, target: Dict[str, Any], current_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    sheet_url = target["sheet_url"]
    sheet_id = target["sheet2_id"]
    columns = target["columns"]
    data_range = target.get("sheet2_data_range", f"A2:K{SNAPSHOT_MAX_ROWS}")
    readback_range = target.get("sheet2_readback_range", "A1:K3")
    rows = [[row.get(col, "") for col in columns] for row in current_rows]
    sheet_writer.clear_data_range(sheet_url, sheet_id, data_range)
    if rows:
        sheet_writer.write_matrix(sheet_url, sheet_id, "A2", rows)
    return {
        "rows_written": len(rows),
        "data_range_cleared": data_range,
        "readback": sheet_writer.raw_readback(sheet_url, sheet_id, readback_range),
    }


def write_qa_diff(qa_dict: Dict[str, Any], diff: Dict[str, Any]) -> Dict[str, Any]:
    qa_dict["diff_summary"] = {
        **diff["summary"],
        "status_changes_preview": diff["status_changes"][:20],
        "removed_preview": [item["shop_id"] for item in diff["removed_shops"][:20]],
        "new_preview": [item["shop_id"] for item in diff["new_shops"][:20]],
    }
    return qa_dict


def build_dry_run_plan(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
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
            "sheet1_id": config.get("target", {}).get("sheet1_id"),
            "sheet2_id": config.get("target", {}).get("sheet2_id"),
            "columns_count": len(config.get("target", {}).get("columns") or []),
            "mode": config.get("target", {}).get("mode"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-source-sync entry.")
    parser.add_argument("--config", required=True, help="Path to JSON config file.")
    parser.add_argument("--dry-run", action="store_true", help="Only parse config and print plan.")
    parser.add_argument("--output-dir", default=str(SKILL_DIR / "output"), help="QA report output dir.")
    parser.add_argument("--today", default="", help="Optional YYYY-MM-DD override for idempotent runs.")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute() and not config_path.exists():
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

    today = (args.today or datetime.now().strftime("%Y-%m-%d")).strip()
    target_columns: List[str] = [str(c) for c in config["target"]["columns"]]
    source_target_columns = [col for col in target_columns if col != "更新时间"]

    sources_results: List[Dict[str, Any]] = []
    value_map_applied: List[Dict[str, Any]] = []
    dedup_applied: List[Dict[str, Any]] = []
    all_normalized: List[List[List[Any]]] = []

    try:
        headers_result = ensure_sheet_headers(config["target"])

        for src_cfg in config["sources"]:
            fetched = fetch_source(src_cfg)
            sources_results.append(fetched)
            normalized = normalize_rows(
                source_result=fetched,
                field_map=src_cfg.get("field_map", {}),
                target_columns=source_target_columns,
            )
            normalized, dedup_stats = deduplicate_rows(
                rows=normalized,
                dedup_config=src_cfg.get("dedup"),
                target_columns=source_target_columns,
            )
            dedup_applied.append({"source_id": src_cfg.get("id", "?"), **dedup_stats})
            normalized, value_map_stats = apply_value_map(
                normalized_rows=normalized,
                field_map=src_cfg.get("field_map", {}),
                target_columns=source_target_columns,
                value_map=src_cfg.get("value_map"),
            )
            value_map_applied.append({"source_id": src_cfg.get("id", "?"), "per_column": value_map_stats})
            all_normalized.append(normalized)

        merged = merge_rows(all_normalized, config.get("merge_strategy", "union_append"))
        merged, field_format_stats = apply_field_format(
            rows=merged,
            field_formats=config.get("field_format"),
            target_columns=source_target_columns,
        )

        current_rows = normalize_current_rows(merged, source_target_columns, today)
        prev_snapshot = read_sheet_snapshot(config["target"]["sheet_url"], config["target"]["sheet2_id"], target_columns)
        master = read_sheet1_master(config["target"]["sheet_url"], config["target"]["sheet1_id"])
        diff = compute_diff(current_rows, prev_snapshot, master)

        sheet1_result = write_sheet1_patch(target=config["target"], diff=diff, master=master, today=today)
        sheet2_result = write_sheet2_full_overwrite(target=config["target"], current_rows=current_rows)

        sheet_writer.wait_and_verify_cell(config["target"]["sheet_url"], config["target"]["sheet1_id"], "K2", today)
        time_readback = sheet_writer.read_range_matrix(
            config["target"]["sheet_url"],
            config["target"]["sheet1_id"],
            f"A1:M{max(len(master) + len(diff['new_shops']) + 5, 20)}",
        )
        sheet1_data_rows = 0
        for row in time_readback[1:]:
            if len(row) > 0 and str(row[0]).strip():
                sheet1_data_rows += 1

        write_result = {
            "rows_written": len(current_rows),
            "updated_at": today,
            "updated_at_cell": "K2",
            "updated_at_readback": sheet_writer.read_cell(config["target"]["sheet_url"], config["target"]["sheet1_id"], "K2"),
            "readback": {
                "sheet1_top": sheet_writer.raw_readback(config["target"]["sheet_url"], config["target"]["sheet1_id"], "A1:M3"),
                "sheet2_top": sheet2_result.get("readback"),
            },
            "sheet1_rows_after": sheet1_data_rows,
        }

        cross_report = qa_check.run_cross_checks(
            config=config,
            sources_results=sources_results,
            write_result=write_result,
            expected_rows_after_transform=len(current_rows),
        )

        report = {
            "run_id": result["run_id"],
            "config_path": result["config_path"],
            "status": cross_report["status"],
            "today": today,
            "headers_ensured": headers_result,
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
                "sheet1_id": config["target"].get("sheet1_id"),
                "sheet2_id": config["target"].get("sheet2_id"),
                "sheet1": sheet1_result,
                "sheet2": {"rows_written": sheet2_result.get("rows_written", 0), "data_range_cleared": sheet2_result.get("data_range_cleared")},
                "sheet1_rows_after": sheet1_data_rows,
            },
            "dedup_applied": dedup_applied,
            "value_map_applied": value_map_applied,
            "field_format_applied": field_format_stats,
            "cross_checks": cross_report["cross_checks"],
            "warnings": cross_report.get("warnings", []),
            "errors": cross_report.get("errors", []),
            "raw_readback": write_result.get("readback"),
        }
        report = write_qa_diff(report, diff)
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
        try:
            path = qa_check.save_qa_report(result, output_dir)
            result["qa_report_path"] = str(path)
        except Exception:
            pass
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
