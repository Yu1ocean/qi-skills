#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

ILLEGAL_FILE_NAMES = {"send_l1_reply.py"}
ILLEGAL_SUBSTRINGS = [
    "lark_im_send_message",
    '"reply_to"',
    "'reply_to'",
]
DEFAULT_EXCLUDES = {".pytest_cache", ".tmp", "notification_logs", "__pycache__", "tests"}
SELF_FILE_NAME = "taskflow_route_bypass_audit.py"


def iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in DEFAULT_EXCLUDES for part in path.parts):
            continue
        if path.name == SELF_FILE_NAME:
            continue
        yield path


def audit_taskflow_route_bypass(root: Path) -> Dict[str, object]:
    violations: List[Dict[str, object]] = []
    for path in iter_python_files(root):
        rel_path = path.relative_to(root).as_posix()
        if path.name in ILLEGAL_FILE_NAMES:
            violations.append(
                {
                    "type": "illegal_file_name",
                    "file": rel_path,
                    "detail": f"禁止保留历史旁路脚本：{path.name}",
                }
            )
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            violations.append(
                {
                    "type": "read_error",
                    "file": rel_path,
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        for needle in ILLEGAL_SUBSTRINGS:
            if needle in content:
                violations.append(
                    {
                        "type": "illegal_pattern",
                        "file": rel_path,
                        "detail": f"发现非法旁路发送特征：{needle}",
                    }
                )
    return {
        "ok": len(violations) == 0,
        "root": str(root),
        "violation_count": len(violations),
        "violations": violations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="TaskFlow 路由旁路审计器")
    parser.add_argument("--root", default=None, help="待审计目录，默认审计 task-flow-engine 根目录")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    result = audit_taskflow_route_bypass(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
