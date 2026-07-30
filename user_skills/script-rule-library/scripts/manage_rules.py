#!/usr/bin/env python3
"""Local helpers for script-rule-library.

This script intentionally handles only local JSON/CSV aggregation and query shaping.
Feishu Bitable writes must be performed through the platform MCP / feishu-doc-writing-guide
workflow after schema readback.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

DEFAULT_NULL = "NULL"
REQUIRED_INPUT_FIELDS = ["batch_id", "record_id", "methodology_signals"]

SYNONYM_RULES = {
    "result-first-hook": ["结果先行", "结果前置", "效果画面前置", "先给效果", "结果画面先行"],
    "problem-solution-structure": ["问题-原因-解法", "问题原因解法", "痛点到解法", "教程纠偏"],
    "avoidance-list": ["避坑清单", "错误示范", "不要这样做", "避雷"],
    "contrast-demo": ["强对比", "前后对比", "对比演示", "before after"],
    "identity-hook": ["身份锁定", "特定人群", "如果你是", "适合"],
}


def load_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in ["records", "rows", "items", "data"]:
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]
        if isinstance(data, list):
            return data
        raise ValueError("JSON input must be an object or list")
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
            return list(csv.DictReader(file_obj))
    raise ValueError("Only .json and .csv inputs are supported")


def split_signals(value: Any) -> List[str]:
    if value in (None, "", DEFAULT_NULL):
        return []
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[;,，；|/\n]+", str(value))
    return [str(item).strip() for item in raw_items if str(item).strip()]


def normalize_signal(signal: str) -> str:
    lowered = signal.lower().strip()
    for normalized_key, synonyms in SYNONYM_RULES.items():
        if any(synonym.lower() in lowered for synonym in synonyms):
            return normalized_key
    slug = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", lowered).strip("-")
    return slug or "unknown-signal"


def validate_hot_script_row(row: Dict[str, Any]) -> None:
    missing = [key for key in REQUIRED_INPUT_FIELDS if not row.get(key)]
    if missing:
        raise ValueError(f"hot-script row missing required fields: {missing}")


def aggregate(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    buckets: Dict[str, Dict[str, Any]] = {}
    dlq: List[Dict[str, Any]] = []
    for row in records:
        try:
            validate_hot_script_row(row)
        except ValueError as exc:
            dlq.append({"reason": str(exc), "row": row})
            continue

        seen_keys = set()
        for signal in split_signals(row.get("methodology_signals")):
            normalized_key = normalize_signal(signal)
            bucket_key = "|".join(
                [
                    normalized_key,
                    str(row.get("category") or DEFAULT_NULL),
                    str(row.get("scenario") or DEFAULT_NULL),
                    str(row.get("platform") or DEFAULT_NULL),
                ]
            )
            if bucket_key in seen_keys:
                continue
            seen_keys.add(bucket_key)

            if bucket_key not in buckets:
                buckets[bucket_key] = {
                    "normalized_rule_key": normalized_key,
                    "rule_name": signal,
                    "rule_type": infer_rule_type(normalized_key),
                    "platform": row.get("platform") or DEFAULT_NULL,
                    "market": row.get("market") or DEFAULT_NULL,
                    "category": row.get("category") or DEFAULT_NULL,
                    "scenario": row.get("scenario") or DEFAULT_NULL,
                    "frequency": 0,
                    "source_batch_ids": [],
                    "source_record_ids": [],
                    "raw_signals": [],
                    "last_observed_at": row.get("observed_at") or DEFAULT_NULL,
                }
            bucket = buckets[bucket_key]
            bucket["frequency"] += 1
            append_unique(bucket["source_batch_ids"], row.get("batch_id"))
            append_unique(bucket["source_record_ids"], row.get("record_id"))
            append_unique(bucket["raw_signals"], signal)
            observed_at = str(row.get("observed_at") or DEFAULT_NULL)
            if observed_at != DEFAULT_NULL:
                bucket["last_observed_at"] = max(str(bucket.get("last_observed_at") or ""), observed_at)

    return {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rules": sorted(buckets.values(), key=lambda item: (-int(item["frequency"]), item["normalized_rule_key"])),
        "dlq": dlq,
    }


def append_unique(target: List[Any], value: Any) -> None:
    if value in (None, ""):
        return
    if value not in target:
        target.append(value)


def infer_rule_type(normalized_key: str) -> str:
    if "hook" in normalized_key or "result-first" in normalized_key or "identity" in normalized_key:
        return "hook"
    if "structure" in normalized_key or "solution" in normalized_key:
        return "structure"
    if "contrast" in normalized_key:
        return "proof"
    if "avoid" in normalized_key:
        return "risk"
    return "structure"


def query_rules(payload: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    rules = payload.get("rules", [])
    filtered = []
    for rule in rules:
        if args.platform and str(rule.get("platform")) not in {args.platform, DEFAULT_NULL}:
            continue
        if args.market and str(rule.get("market")) not in {args.market, DEFAULT_NULL}:
            continue
        if args.category and str(rule.get("category")) not in {args.category, DEFAULT_NULL}:
            continue
        if args.scenario and str(rule.get("scenario")) not in {args.scenario, DEFAULT_NULL}:
            continue
        filtered.append(to_video_script_rule(rule))
    return {
        "query_context": {
            "platform": args.platform or DEFAULT_NULL,
            "market": args.market or DEFAULT_NULL,
            "category": args.category or DEFAULT_NULL,
            "scenario": args.scenario or DEFAULT_NULL,
            "objective": args.objective or DEFAULT_NULL,
        },
        "rules": filtered[: args.limit],
        "null_fields": [],
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def to_video_script_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    normalized_key = rule.get("normalized_rule_key", "unknown")
    return {
        "rule_id": rule.get("rule_id") or f"LOCAL-{normalized_key}",
        "rule_name": rule.get("rule_name") or normalized_key,
        "rule_type": rule.get("rule_type") or "structure",
        "frequency": int(rule.get("frequency") or 0),
        "usage_guidance": build_usage_guidance(normalized_key, rule.get("rule_name") or normalized_key),
        "evidence_notes": f"来源批次: {', '.join(map(str, rule.get('source_batch_ids', []))) or DEFAULT_NULL}; 来源记录: {len(rule.get('source_record_ids', []))} 条",
        "risk_notes": "请结合具体品类、素材强度与目标动作校准；频次高不等于任何场景都适用。",
        "source_batch_id": (rule.get("source_batch_ids") or [DEFAULT_NULL])[-1],
    }


def build_usage_guidance(normalized_key: str, fallback: str) -> str:
    guidance = {
        "result-first-hook": "开场先展示最终效果或结果画面，再解释过程与条件。",
        "problem-solution-structure": "先明确用户痛点，再给原因解释和可执行解法。",
        "avoidance-list": "用避坑清单降低理解成本，每条只讲一个明确错误。",
        "contrast-demo": "用前后对比或变量对比证明变化，避免只口头承诺。",
        "identity-hook": "前三秒锁定具体人群，让目标用户确认这条内容和自己有关。",
    }
    return guidance.get(normalized_key, f"围绕「{fallback}」设计脚本结构，并保留证据或案例支撑。")


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="script-rule-library local helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    aggregate_parser = subparsers.add_parser("aggregate")
    aggregate_parser.add_argument("--input-path", required=True)
    aggregate_parser.add_argument("--output-path", required=True)

    query_parser = subparsers.add_parser("query")
    query_parser.add_argument("--rules-path", required=True)
    query_parser.add_argument("--output-path", required=True)
    query_parser.add_argument("--platform")
    query_parser.add_argument("--market")
    query_parser.add_argument("--category")
    query_parser.add_argument("--scenario")
    query_parser.add_argument("--objective")
    query_parser.add_argument("--limit", type=int, default=20)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "aggregate":
        payload = aggregate(load_records(Path(args.input_path)))
        write_json(Path(args.output_path), payload)
        print(json.dumps({"ok": True, "rules": len(payload["rules"]), "dlq": len(payload["dlq"]), "output_path": args.output_path}, ensure_ascii=False))
        return 0
    if args.command == "query":
        payload = json.loads(Path(args.rules_path).read_text(encoding="utf-8"))
        result = query_rules(payload, args)
        write_json(Path(args.output_path), result)
        print(json.dumps({"ok": True, "rules": len(result["rules"]), "output_path": args.output_path}, ensure_ascii=False))
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
