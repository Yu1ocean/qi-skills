#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import math
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build latest travel dashboard prod artifact and publish it to the live daily entry")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--mode", default="auto")
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
    ], skill_root)

    print("已生成 published/travel-dashboard-live/index.html；如需线上部署，请在上层流程使用 deploy skill 处理。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
