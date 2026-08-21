#!/usr/bin/env python3
import argparse
import importlib.util
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

VALID_MODES = {"probe", "video", "audio"}
DEFAULT_OUTPUT_ROOT = Path("downloads/media_fetcher")

# --- TikTok 403 降级链路（v1.2）---------------------------------------------
# 背景：数据中心出口 IP 下 yt-dlp 的 TikTok webpage 路径在 challenge 阶段稳定 403，
# app API 路径缺 X-Argus 签名返回空 body。唯一实测可用的路径是官方 embed 端点
# https://www.tiktok.com/embed/v2/<id>（不校验 WAF challenge）。详见
# scripts/tiktok_embed_fallback.py 顶部注释与 SKILL.md。
DEFAULT_TIKTOK_FALLBACK = "embed_v2"
TIKTOK_HOST_MARKERS = ("tiktok.com",)
TIKTOK_FALLBACK_ROUTE = "tiktok_embed_fallback"
FALLBACK_SCRIPT_NAME = "tiktok_embed_fallback.py"
TIKTOK_FALLBACK_PACING_SECONDS = 2.0


def validate_mode(mode: str) -> None:
    if mode not in VALID_MODES:
        raise ValueError("mode 非法")


def is_tiktok_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(marker in lowered for marker in TIKTOK_HOST_MARKERS)


def load_tiktok_fallback():
    """按需加载同目录下的 embed 降级模块；缺失即抛错，禁止静默跳过降级。"""
    path = Path(__file__).resolve().parent / FALLBACK_SCRIPT_NAME
    if not path.exists():
        raise FileNotFoundError(f"TikTok 降级脚本缺失: {path}")
    spec = importlib.util.spec_from_file_location("tiktok_embed_fallback", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_tiktok_fallback(url: str, mode: str, output_dir: Path) -> Dict[str, Any]:
    """对 TikTok URL 执行 embed 降级；返回结构化结果（含失败原因分类）。"""
    module = load_tiktok_fallback()
    probe_only = mode == "probe"
    # 批内节流：embed 端点对密集连续请求会限流抖动，进入降级前先礼貌等待。
    time.sleep(TIKTOK_FALLBACK_PACING_SECONDS)
    try:
        result = module.fetch_one(url, str(output_dir), probe_only=probe_only)
    except Exception as exc:  # noqa: BLE001 - 降级失败必须留痕而非崩掉整批
        return {
            "route": TIKTOK_FALLBACK_ROUTE,
            "strategy": DEFAULT_TIKTOK_FALLBACK,
            "ok": False,
            "url": url,
            "stage": "fallback_invoke",
            "reason": f"{type(exc).__name__}: {exc}",
        }
    result["route"] = TIKTOK_FALLBACK_ROUTE
    result["strategy"] = DEFAULT_TIKTOK_FALLBACK
    return result


def validate_input_rows(rows: List[Dict[str, Any]]) -> None:
    if not isinstance(rows, list) or not rows:
        raise ValueError("输入必须是非空列表")
    for row in rows:
        url = str(row.get("url") or row.get("video_url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("存在非法 url")


def validate_success_item(item: Dict[str, Any], mode: str) -> None:
    """L3 断言：成功项必须 probe 成立 + 有主产物路径。

    v1.2：对 `fetch_route == "tiktok_embed_fallback"` 的条目放开「probe.returncode == 0」
    这条 yt-dlp 专属校验，改为等价校验「embed probe 成功」（fallback.probe_ok is True）。
    但「无主产物路径不许宣称成功」这条**不放松**。
    """
    route = item.get("fetch_route")
    if route == TIKTOK_FALLBACK_ROUTE:
        if not item.get("fallback", {}).get("probe_ok"):
            raise ValueError("embed fallback probe 未成功，禁止标记为成功项")
    elif item.get("probe", {}).get("returncode") != 0:
        raise ValueError("probe 未成功，禁止标记为成功项")

    if mode == "probe":
        return
    if not item.get("primary_asset_path") and not item.get("fetch", {}).get(
        "primary_asset_path"
    ):
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


def apply_tiktok_fallback(
    item: Dict[str, Any],
    url: str,
    mode: str,
    item_dir: Path,
    primary_stage: str,
    primary_reason: str,
) -> Dict[str, Any]:
    """TikTok 主链路（yt-dlp）失败后的 embed 降级路由。

    成功 → status=success + fetch_route=tiktok_embed_fallback + primary_asset_path/metadata；
    失败 → status=failed，并在 DLQ 记录 yt-dlp 与 embed 两条链路各自的失败原因。
    """
    fb = run_tiktok_fallback(url, mode, item_dir)
    probe_ok = fb.get("stage") in {"probe", "download"} and bool(fb.get("play_urls"))
    item["fetch_route"] = TIKTOK_FALLBACK_ROUTE
    item["fallback"] = {
        "route": TIKTOK_FALLBACK_ROUTE,
        "strategy": DEFAULT_TIKTOK_FALLBACK,
        "probe_ok": probe_ok,
        "ok": bool(fb.get("ok")),
        "stage": fb.get("stage"),
        "reason": fb.get("reason"),
        "embed_url": fb.get("embed_url"),
        "raw": fb,
    }
    item["primary_route_failure"] = {
        "route": "yt_dlp",
        "stage": primary_stage,
        "reason": primary_reason,
    }

    if fb.get("ok") and (mode == "probe" or fb.get("filepath")):
        item["metadata"] = {
            "video_id": fb.get("video_id"),
            "title": fb.get("title"),
            "author": fb.get("author"),
            "duration": fb.get("duration"),
            "width": fb.get("width"),
            "height": fb.get("height"),
            "create_time": fb.get("create_time"),
            "stats": fb.get("stats"),
            "cover": fb.get("cover"),
            "source": TIKTOK_FALLBACK_ROUTE,
        }
        if fb.get("filepath"):
            item["primary_asset_path"] = fb["filepath"]
            item["filesize"] = fb.get("filesize")
        item["status"] = "success"
        validate_success_item(item, mode)
        return item

    item["status"] = "failed"
    item["failure_stage"] = f"{primary_stage}+{TIKTOK_FALLBACK_ROUTE}"
    item["failure_reasons"] = {
        "yt_dlp": f"[{primary_stage}] {primary_reason}"[:300],
        TIKTOK_FALLBACK_ROUTE: f"[{fb.get('stage')}] {fb.get('reason')}"[:300],
    }
    item["stderr_summary"] = (
        f"yt_dlp[{primary_stage}]: {primary_reason} | "
        f"embed[{fb.get('stage')}]: {fb.get('reason')}"
    )[:600]
    return item


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
        "fetch_route": "yt_dlp",
        "probe": probe_result,
    }

    if probe_result.get("returncode") != 0:
        reason = (probe_result.get("stderr") or probe_result.get("stdout") or "").strip()[:300]
        if is_tiktok_url(url):
            return apply_tiktok_fallback(item, url, mode, item_dir, "probe", reason)
        item["status"] = "failed"
        item["failure_stage"] = "probe"
        item["stderr_summary"] = reason
        return item

    if mode == "probe":
        item["status"] = "success"
        validate_success_item(item, mode)
        return item

    fetch_result = run_fetch(fetch_script, url, mode, item_dir)
    item["fetch"] = fetch_result
    if fetch_result.get("returncode") != 0 or not fetch_result.get("primary_asset_path"):
        reason = (
            (fetch_result.get("stderr") or "").strip()
            or "primary_asset_path missing"
        )[:300]
        if is_tiktok_url(url):
            return apply_tiktok_fallback(item, url, mode, item_dir, mode, reason)
        item["status"] = "failed"
        item["failure_stage"] = mode
        item["stderr_summary"] = reason
        return item

    item["primary_asset_path"] = fetch_result.get("primary_asset_path")
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
