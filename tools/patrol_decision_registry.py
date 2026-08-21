#!/usr/bin/env python3
"""Decision Registry 定时巡检脚本。

流程：
1. 先 dry-run 对账，判断是否存在漂移
2. 若存在漂移，生成漂移报告
3. 尝试以本地为准自动修复飞书镜像
4. 若修复失败，输出 ⚠️ [DRIFT_DETECTED] 供上游巡检任务抓取
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sync_decision_registry import DEFAULT_REGISTRY_PATH, DEFAULT_WIKI_URL, sync_registry


def render_report(prefix: str, payload: dict) -> None:
    print(prefix)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="巡检并修复 Decision Registry 漂移")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY_PATH), help="本地 registry 文件路径")
    parser.add_argument("--sheet-url", default=DEFAULT_WIKI_URL, help="飞书 wiki/sheet 链接")
    parser.add_argument("--quiet", action="store_true", help="减少过程日志")
    args = parser.parse_args()

    registry = Path(args.registry)
    sheet_url = args.sheet_url
    verbose = not args.quiet

    try:
        dry_result = sync_registry(registry_path=registry, sheet_url=sheet_url, apply=False, verbose=verbose)
        render_report("[PATROL][DRY-RUN]", dry_result.to_dict())

        if not dry_result.has_drift:
            print("[PATROL] 未发现漂移，无需修复")
            return 0

        print("[PATROL] 发现漂移，开始自动修复（以本地为准）")
        repair_result = sync_registry(registry_path=registry, sheet_url=sheet_url, apply=True, verbose=verbose)
        render_report("[PATROL][REPAIRED]", repair_result.to_dict())
        print("[PATROL] 自动修复完成")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ [DRIFT_DETECTED] 自动修复失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
