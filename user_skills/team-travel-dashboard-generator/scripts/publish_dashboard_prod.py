#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish prod dashboard HTML to the live daily entry")
    parser.add_argument("--source-html", default="output/travel_dashboard.prod.html")
    parser.add_argument("--target-html", default="../../published/travel-dashboard-live/index.html")
    args = parser.parse_args()

    skill_root = Path(__file__).resolve().parents[1]
    source = (skill_root / args.source_html).resolve()
    target = (skill_root / args.target_html).resolve()

    if not source.exists():
        raise SystemExit(json.dumps({"ok": False, "error": f"source html not found: {source}"}, ensure_ascii=False))

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)

    echarts_source = skill_root / "assets" / "echarts.min.js"
    echarts_target = target.parent / "echarts.min.js"
    if echarts_source.exists():
        shutil.copyfile(echarts_source, echarts_target)

    print(json.dumps({
        "ok": True,
        "source_html": str(source),
        "target_html": str(target),
        "echarts_js": str(echarts_target) if echarts_source.exists() else "",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
