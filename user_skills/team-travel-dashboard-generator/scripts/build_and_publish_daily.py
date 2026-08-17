#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import math
import urllib.error
import urllib.request
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True)


def read_generated_at(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"[DATA_VERSION_ASSERT_FAILED] dashboard json not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"[DATA_VERSION_ASSERT_FAILED] invalid dashboard json: {path} ({exc})") from exc
    generated_at = payload.get("generated_at")
    if not generated_at:
        raise SystemExit(f"[DATA_VERSION_ASSERT_FAILED] missing generated_at in: {path}")
    return str(generated_at)


def fetch_remote_generated_at(url: str) -> str:
    try:
        request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=20) as resp:  # noqa: S310 - fixed internal url
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise SystemExit(f"[DATA_VERSION_ASSERT_FAILED] cannot fetch remote dashboard json: {url} ({exc})") from exc
    generated_at = payload.get("generated_at")
    if not generated_at:
        raise SystemExit(f"[DATA_VERSION_ASSERT_FAILED] missing generated_at in remote json: {url}")
    return str(generated_at)


def assert_generated_at_consistency(skill_root: Path, local_json: str, published_json: str, verify_url: str) -> dict:
    """发布后强制断言：线上 generated_at == 本地 generated_at，不一致立即熔断。"""
    local_path = (skill_root / local_json).resolve()
    published_path = (skill_root / published_json).resolve()

    local_generated_at = read_generated_at(local_path)
    published_generated_at = read_generated_at(published_path)

    if published_generated_at != local_generated_at:
        raise SystemExit(
            "[DATA_VERSION_MISMATCH] published generated_at != local generated_at: "
            f"local={local_generated_at} published={published_generated_at} "
            f"(local_json={local_path}, published_json={published_path})"
        )

    result = {
        "local_generated_at": local_generated_at,
        "published_generated_at": published_generated_at,
        "local_json": str(local_path),
        "published_json": str(published_path),
        "remote_generated_at": "",
        "remote_url": "",
    }

    if verify_url:
        remote_generated_at = fetch_remote_generated_at(verify_url)
        if remote_generated_at != local_generated_at:
            raise SystemExit(
                "[DATA_VERSION_MISMATCH] online generated_at != local generated_at: "
                f"local={local_generated_at} online={remote_generated_at} (url={verify_url})"
            )
        result["remote_generated_at"] = remote_generated_at
        result["remote_url"] = verify_url

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build latest travel dashboard prod artifact and publish it to the live daily entry")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--mode", default="auto")
    parser.add_argument(
        "--verify-url",
        default="",
        help="可选：线上大屏数据文件 URL（如 https://<host>/travel_dashboard.prod.json），传入即做远端 generated_at 断言",
    )
    args = parser.parse_args()

    skill_root = Path(__file__).resolve().parents[1]
    months = max(1, math.ceil(max(args.days, 1) / 30))

    run([
        "python3", "scripts/build_travel_dashboard.py", "build",
        "--months", str(months),
        "--mode", args.mode,
        "--output-json", "output/travel_dashboard.prod.json",
        "--output-html", "output/travel_dashboard.prod.html",
        "--geo-cache", "output/geo_cache.json",
        "--city-alias-cache", "output/city_alias_cache.json",
        "--footprint-library", "output/travel_footprint_library.json",
    ], skill_root)

    run([
        "python3", "scripts/sync_travel_log_sheet.py",
        "--input-json", "output/travel_dashboard.prod.json",
        "--apply",
    ], skill_root)

    run([
        "python3", "scripts/publish_dashboard_prod.py",
        "--source-html", "output/travel_dashboard.prod.html",
        "--target-html", "../../published/travel-dashboard-live/index.html",
        "--source-json", "output/travel_dashboard.prod.json",
        "--target-json", "../../published/travel-dashboard-live/travel_dashboard.prod.json",
    ], skill_root)

    verification = assert_generated_at_consistency(
        skill_root,
        local_json="output/travel_dashboard.prod.json",
        published_json="../../published/travel-dashboard-live/travel_dashboard.prod.json",
        verify_url=args.verify_url,
    )

    print(json.dumps({"ok": True, "data_version_check": verification}, ensure_ascii=False, indent=2))
    print("已生成 published/travel-dashboard-live/index.html + travel_dashboard.prod.json；数据版本断言通过。如需线上部署，请在上层流程使用 deploy skill 处理。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
