#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

VALID_MODES = {"probe", "video", "audio"}
DEFAULT_OUTPUT_ROOT = Path("downloads/media_fetcher")


def validate_mode(mode: str) -> None:
    if mode not in VALID_MODES:
        raise ValueError("mode 非法")


def validate_input_rows(rows: List[Dict[str, Any]]) -> None:
    if not isinstance(rows, list) or not rows:
        raise ValueError("输入必须是非空列表")
    for row in rows:
        url = str(row.get("url") or row.get("video_url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("存在非法 url")


def validate_success_item(item: Dict[str, Any], mode: str) -> None:
    if item.get("probe", {}).get("returncode") != 0:
        raise ValueError("probe 未成功，禁止标记为成功项")
    if mode != "probe" and not item.get("fetch", {}).get("primary_asset_path"):
        raise ValueError("缺少主产物路径，禁止宣称下载成功")


def load_input(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
        rows = []
        for candidate in payload["candidates"]:
            rows.append(
                {
                    "url": candidate.get("video_url"),
                    "tags": {
                        "platform": candidate.get("platform"),
                        "market": candidate.get("market"),
                        "category": candidate.get("category"),
                        "account_name": candidate.get("account_name"),
                        "video_type_tags": candidate.get("video_type_tags"),
                    },
                    "source": candidate,
                }
            )
        return rows
    if isinstance(payload, list):
        return payload
    raise ValueError("输入 JSON 必须是列表，或包含 candidates 列表")


def safe_slug(text: str, fallback: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in text.strip())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return (cleaned[:80] or fallback).lower()


def run_fetch(fetch_script: Path, url: str, mode: str, output_dir: Path) -> Dict[str, Any]:
    if not fetch_script.exists():
        raise FileNotFoundError(f"yt-dlp fetch script not found: {fetch_script}")
    cmd = [
        "python3",
        str(fetch_script),
        "--mode",
        mode,
        "--url",
        url,
        "--output-dir",
        str(output_dir),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    stdout = proc.stdout.strip()
    if not stdout:
        return {
            "mode": mode,
            "url": url,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {
            "mode": mode,
            "url": url,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "parse_error": "stdout is not valid json",
        }


def build_item(index: int, row: Dict[str, Any], mode: str, output_root: Path, fetch_script: Path) -> Dict[str, Any]:
    url = str(row.get("url") or row.get("video_url")).strip()
    tags = row.get("tags") or {}
    slug = safe_slug(url.split("/")[-1], f"item-{index:03d}")
    item_dir = output_root / f"{index:03d}-{slug}"
    item_dir.mkdir(parents=True, exist_ok=True)

    probe_result = run_fetch(fetch_script, url, "probe", item_dir)
    item = {
        "index": index,
        "url": url,
        "tags": tags,
        "probe": probe_result,
    }

    if probe_result.get("returncode") != 0:
        item["status"] = "failed"
        item["failure_stage"] = "probe"
        item["stderr_summary"] = (probe_result.get("stderr") or "").strip()[:300]
        return item

    if mode == "probe":
        item["status"] = "success"
        validate_success_item(item, mode)
        return item

    fetch_result = run_fetch(fetch_script, url, mode, item_dir)
    item["fetch"] = fetch_result
    if fetch_result.get("returncode") != 0:
        item["status"] = "failed"
        item["failure_stage"] = mode
        item["stderr_summary"] = (fetch_result.get("stderr") or "").strip()[:300]
        return item

    item["status"] = "success"
    validate_success_item(item, mode)
    return item


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_dlq(path: Path, items: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch orchestrator for yt-dlp media fetching")
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--mode", default="video")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--fetch-script", required=True)
    parser.add_argument("--result-json", required=True)
    parser.add_argument("--dlq-jsonl", required=True)
    args = parser.parse_args()

    validate_mode(args.mode)
    input_path = Path(args.input_json)
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")
    fetch_script = Path(args.fetch_script)
    if not fetch_script.exists():
        raise FileNotFoundError(f"底层 fetch script 不存在: {fetch_script}")

    rows = load_input(input_path)
    validate_input_rows(rows)

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    items: List[Dict[str, Any]] = []
    failed_items: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        item = build_item(idx, row, args.mode, output_root, fetch_script)
        items.append(item)
        if item.get("status") != "success":
            failed_items.append(item)

    result = {
        "batch_id": f"MFETCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "mode": args.mode,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "input_json": str(input_path.resolve()),
        "output_root": str(output_root.resolve()),
        "summary": {
            "input_count": len(rows),
            "success_count": len(items) - len(failed_items),
            "failed_count": len(failed_items),
        },
        "items": items,
        "dlq_path": str(Path(args.dlq_jsonl).resolve()),
    }

    write_json(Path(args.result_json), result)
    write_dlq(Path(args.dlq_jsonl), failed_items)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
