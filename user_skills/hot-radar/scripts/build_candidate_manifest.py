#!/usr/bin/env python3
import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

DEFAULT_NULL = "NULL"
DEFAULT_TOP_N = 50
VALID_PLATFORMS = {"TikTok Shop", "抖音跨境", "TikTok", "Douyin"}
METRIC_FIELDS = ["view_count", "like_count", "comment_count", "share_count", "gmv"]
TEXT_FIELDS = ["account_name", "video_title", "publish_time", "source_note"]

TAG_RULES = [
    (re.compile(r"(try\s*on|ootd|上身|穿搭|种草)", re.I), "种草"),
    (re.compile(r"(review|测评|对比|评测)", re.I), "测评"),
    (re.compile(r"(story|剧情|反转|冲突)", re.I), "剧情"),
    (re.compile(r"(直播切片|直播间|live\s*clip|直播)", re.I), "直播切片"),
    (re.compile(r"(口播|讲解|解说|talking\s*head)", re.I), "口播"),
    (re.compile(r"(混剪|montage|合集)", re.I), "混剪"),
]


def validate_query(platform: str, market: str, category: str, top_n: int) -> None:
    if not platform or not market or not category:
        raise ValueError("platform / market / category 不完整，禁止继续")
    if top_n <= 0:
        raise ValueError("top_n 必须大于 0")


def validate_candidate_row(row: Dict[str, Any]) -> None:
    url = str(row.get("video_url", "")).strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("候选缺少合法 video_url")


def validate_null_contract(row: Dict[str, Any]) -> None:
    forbidden = {"", None, "N/A", "unknown"}
    for key in METRIC_FIELDS:
        if row.get(key) in forbidden:
            raise ValueError(f"字段 {key} 必须使用 NULL，而不是空值")


def load_records(input_path: Path) -> List[Dict[str, Any]]:
    suffix = input_path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
            return payload["candidates"]
        if isinstance(payload, list):
            return payload
        raise ValueError("JSON 输入必须是列表，或包含 candidates 列表")
    if suffix == ".csv":
        with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    raise ValueError(f"暂不支持的输入格式: {input_path.suffix}")


def normalize_platform(platform: str) -> str:
    aliases = {
        "tts": "TikTok Shop",
        "tiktok shop": "TikTok Shop",
        "tiktok": "TikTok",
        "douyin": "Douyin",
        "抖音": "抖音跨境",
        "抖音跨境": "抖音跨境",
    }
    key = (platform or "").strip().lower()
    value = aliases.get(key, platform)
    if value not in VALID_PLATFORMS:
        return platform
    return value


def normalize_metric(value: Any) -> Any:
    if value in (None, "", "N/A", "unknown"):
        return DEFAULT_NULL
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(",", "")
    if not text:
        return DEFAULT_NULL
    if text.upper() == DEFAULT_NULL:
        return DEFAULT_NULL
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return DEFAULT_NULL


def normalize_text(value: Any) -> str:
    text = str(value).strip() if value is not None else ""
    return text if text else DEFAULT_NULL


def infer_tags(record: Dict[str, Any]) -> List[str]:
    text = " ".join(
        str(record.get(key, "")) for key in ["video_title", "title", "description", "source_note"]
    )
    tags: List[str] = []
    for pattern, tag in TAG_RULES:
        if pattern.search(text):
            tags.append(tag)
    existing = record.get("video_type_tags")
    if isinstance(existing, list):
        tags.extend(str(item).strip() for item in existing if str(item).strip())
    elif isinstance(existing, str) and existing.strip():
        tags.extend(part.strip() for part in re.split(r"[,|/；;]", existing) if part.strip())
    deduped: List[str] = []
    for tag in tags:
        if tag and tag not in deduped:
            deduped.append(tag)
    return deduped or ["其他"]


def normalize_live_clip(record: Dict[str, Any], tags: List[str]) -> str:
    raw = str(record.get("is_live_clip", "")).strip().lower()
    if raw in {"true", "1", "yes", "y", "是"}:
        return "true"
    if raw in {"false", "0", "no", "n", "否"}:
        return "false"
    return "true" if "直播切片" in tags else "false"


def build_record(record: Dict[str, Any], platform: str, market: str, category: str) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {
        "video_url": str(record.get("video_url") or record.get("url") or "").strip(),
        "platform": normalize_platform(record.get("platform") or platform),
        "market": normalize_text(record.get("market") or market),
        "category": normalize_text(record.get("category") or category),
        "account_name": normalize_text(record.get("account_name") or record.get("author") or record.get("account")),
        "video_title": normalize_text(record.get("video_title") or record.get("title")),
        "publish_time": normalize_text(record.get("publish_time") or record.get("published_at")),
        "source_type": normalize_text(record.get("source_type") or "manual_watchlist"),
        "source_note": normalize_text(record.get("source_note") or record.get("note")),
    }
    for field in METRIC_FIELDS:
        normalized[field] = normalize_metric(record.get(field))
    tags = infer_tags(record)
    normalized["video_type_tags"] = tags
    normalized["is_live_clip"] = normalize_live_clip(record, tags)
    validate_candidate_row(normalized)
    validate_null_contract(normalized)
    return normalized


def dedupe(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = {}
    for record in records:
        url = record["video_url"]
        if url not in seen:
            seen[url] = record
            continue
        current_note = seen[url].get("source_note", DEFAULT_NULL)
        next_note = record.get("source_note", DEFAULT_NULL)
        if current_note == DEFAULT_NULL and next_note != DEFAULT_NULL:
            seen[url]["source_note"] = next_note
    return list(seen.values())


def write_dlq(path: Path, invalid_rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in invalid_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize hot video candidates into standard manifest")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--dlq-path", default="output/hot_radar_candidates.dlq.jsonl")
    parser.add_argument("--platform", required=True)
    parser.add_argument("--market", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--time-window", required=True)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    args = parser.parse_args()

    validate_query(args.platform, args.market, args.category, args.top_n)
    input_path = Path(args.input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")

    raw_records = load_records(input_path)
    normalized_records: List[Dict[str, Any]] = []
    invalid_rows: List[Dict[str, Any]] = []

    for idx, row in enumerate(raw_records, start=1):
        try:
            normalized_records.append(build_record(row, args.platform, args.market, args.category))
        except Exception as exc:  # noqa: PERF203
            invalid_rows.append({"row_number": idx, "reason": str(exc), "payload": row})

    deduped = dedupe(normalized_records)[: args.top_n]
    output = {
        "query": {
            "platform": normalize_platform(args.platform),
            "market": args.market,
            "category": args.category,
            "time_window": args.time_window,
            "top_n": args.top_n,
        },
        "summary": {
            "input_count": len(raw_records),
            "valid_count": len(normalized_records),
            "deduped_count": len(deduped),
            "dlq_count": len(invalid_rows),
        },
        "candidates": deduped,
        "dlq_path": str(Path(args.dlq_path).resolve()),
    }

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    write_dlq(Path(args.dlq_path), invalid_rows)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
