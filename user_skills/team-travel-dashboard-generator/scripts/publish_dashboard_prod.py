#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def load_generated_at(path: Path) -> str:
    """Read `generated_at` from a dashboard data json; raise on structural drift."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - surface any parse failure as a hard error
        raise SystemExit(json.dumps(
            {"ok": False, "error": f"invalid dashboard json: {path} ({exc})"},
            ensure_ascii=False,
        )) from exc

    generated_at = payload.get("generated_at")
    if not generated_at:
        raise SystemExit(json.dumps(
            {"ok": False, "error": f"missing generated_at in dashboard json: {path}"},
            ensure_ascii=False,
        ))
    return str(generated_at)


def assert_json_synced(source_json: Path, target_json: Path) -> str:
    """L3 runtime gate: read-after-write probe on the published data file."""
    source_generated_at = load_generated_at(source_json)
    target_generated_at = load_generated_at(target_json)
    if source_generated_at != target_generated_at:
        raise SystemExit(json.dumps({
            "ok": False,
            "error": "[DATA_VERSION_MISMATCH] published json generated_at != local json generated_at",
            "local_generated_at": source_generated_at,
            "published_generated_at": target_generated_at,
            "source_json": str(source_json),
            "target_json": str(target_json),
        }, ensure_ascii=False))
    return source_generated_at


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish prod dashboard HTML + data json to the live daily entry")
    parser.add_argument("--source-html", default="output/travel_dashboard.prod.html")
    parser.add_argument("--target-html", default="../../published/travel-dashboard-live/index.html")
    parser.add_argument("--source-json", default="output/travel_dashboard.prod.json")
    parser.add_argument(
        "--target-json",
        default="../../published/travel-dashboard-live/travel_dashboard.prod.json",
    )
    args = parser.parse_args()

    skill_root = Path(__file__).resolve().parents[1]
    source = (skill_root / args.source_html).resolve()
    target = (skill_root / args.target_html).resolve()
    source_json = (skill_root / args.source_json).resolve()
    target_json = (skill_root / args.target_json).resolve()

    if not source.exists():
        raise SystemExit(json.dumps({"ok": False, "error": f"source html not found: {source}"}, ensure_ascii=False))
    if not source_json.exists():
        raise SystemExit(json.dumps({"ok": False, "error": f"source json not found: {source_json}"}, ensure_ascii=False))

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)

    # 数据文件必须与 index.html 同批同步，禁止只推 HTML 造成“新壳旧数据”。
    target_json.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_json, target_json)
    generated_at = assert_json_synced(source_json, target_json)

    echarts_source = skill_root / "assets" / "echarts.min.js"
    echarts_target = target.parent / "echarts.min.js"
    if echarts_source.exists():
        shutil.copyfile(echarts_source, echarts_target)

    print(json.dumps({
        "ok": True,
        "source_html": str(source),
        "target_html": str(target),
        "source_json": str(source_json),
        "target_json": str(target_json),
        "generated_at": generated_at,
        "echarts_js": str(echarts_target) if echarts_source.exists() else "",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
