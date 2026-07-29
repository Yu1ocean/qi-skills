#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

ILLEGAL_FILE_NAMES = {"send_l1_reply.py"}
ILLEGAL_SUBSTRINGS = [
    "lark_im_send_message",
    '"reply_to"',
    "'reply_to'",
]
DEFAULT_EXCLUDES = {".pytest_cache", ".tmp", "notification_logs", "__pycache__", "tests"}
SELF_FILE_NAMES = {"cross_skill_taskflow_guard_audit.py", "taskflow_route_bypass_audit.py"}
DEFAULT_TARGETS = [
    "user_skills/task-flow-engine",
    "user_skills/heartbeat-inspector",
    "user_skills/smart-scheduler",
    "projects/路由决策进化机制/forge_payloads",
    "user_skills/centralized-transmitter",
]
ALLOWLIST_EXACT: Dict[str, Tuple[str, ...]] = {
    "user_skills/centralized-transmitter/scripts/centralized_transmitter.py": ("lark_im_send_message",),
}


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if any(part in DEFAULT_EXCLUDES for part in path.parts):
            continue
        if path.name in SELF_FILE_NAMES:
            continue
        yield path


def is_allowed(relative_path: str, needle: str) -> bool:
    return needle in ALLOWLIST_EXACT.get(relative_path, ())


def audit_roots(roots: Sequence[Path], *, base_dir: Path) -> Dict[str, object]:
    violations: List[Dict[str, object]] = []
    scanned_files = 0
    scanned_roots: List[str] = []

    for root in roots:
        root = root.resolve()
        scanned_roots.append(str(root))
        if not root.exists():
            violations.append(
                {
                    "type": "missing_root",
                    "file": str(root),
                    "detail": "待审计目录不存在",
                }
            )
            continue

        for path in iter_python_files(root):
            scanned_files += 1
            relative_path = path.relative_to(base_dir).as_posix()
            if path.name in ILLEGAL_FILE_NAMES:
                violations.append(
                    {
                        "type": "illegal_file_name",
                        "file": relative_path,
                        "detail": f"禁止保留历史旁路脚本：{path.name}",
                    }
                )

            try:
                content = path.read_text(encoding="utf-8")
            except OSError as exc:
                violations.append(
                    {
                        "type": "read_error",
                        "file": relative_path,
                        "detail": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue

            for needle in ILLEGAL_SUBSTRINGS:
                if needle not in content:
                    continue
                if is_allowed(relative_path, needle):
                    continue
                violations.append(
                    {
                        "type": "illegal_pattern",
                        "file": relative_path,
                        "detail": f"发现非法旁路发送特征：{needle}",
                    }
                )

    return {
        "ok": len(violations) == 0,
        "workspace_root": str(base_dir),
        "scanned_root_count": len(scanned_roots),
        "scanned_file_count": scanned_files,
        "scanned_roots": scanned_roots,
        "violation_count": len(violations),
        "violations": violations,
    }


def parse_targets(raw_targets: Sequence[str]) -> List[Path]:
    base = workspace_root()
    return [(base / item).resolve() for item in raw_targets]


def main() -> int:
    parser = argparse.ArgumentParser(description="TaskFlow 跨技能/跨目录旁路巡检器")
    parser.add_argument(
        "--targets",
        nargs="*",
        default=DEFAULT_TARGETS,
        help="待审计目录列表，默认覆盖 task-flow-engine / heartbeat-inspector / smart-scheduler / forge_payloads / centralized-transmitter",
    )
    args = parser.parse_args()

    base = workspace_root()
    result = audit_roots(parse_targets(args.targets), base_dir=base)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
