#!/usr/bin/env python3
"""[DEPRECATED / BROKEN since v7.6] Move a Lark/Feishu document into personal space.

⚠️ 失效说明（v7.6）：本脚本依赖的 MCP 脚本
`inner_skills/lark/mcp_lark_move_lark_doc.py` **已从运行时下线**，任何调用都会
FileNotFoundError。脚本保留仅作历史存档，**禁止在任何链路中调用**。
云盘/文档资产赋权请改用 `grant_doc_permissions.py`
（`lark-cli drive +member-add` + `+member-list` RAW 回读断言）。

Ensure an existing Lark/Feishu document is moved into the current user's personal space.

This helper is the v7.3 replacement for legacy "grant permission after create" logic.
Instead of calling Drive Permission APIs with JWT, it delegates to the Lark MCP
`move_lark_doc` capability and uses `target_type=personal` as the only fallback path.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SUPPORTED_SEGMENTS = ("/docx/", "/docs/", "/doc/", "/sheets/", "/base/", "/wiki/", "/file/")
DEFAULT_TARGET_TYPE = "personal"


def validate_document_url(document_url: str) -> str:
    value = (document_url or "").strip()
    if not value:
        raise ValueError("document_url is required")
    if not value.startswith("http://") and not value.startswith("https://"):
        raise ValueError(f"document_url must be a full URL, got: {document_url!r}")
    if not any(segment in value for segment in SUPPORTED_SEGMENTS):
        raise ValueError(
            "Unsupported document_url. Expected one of /docx/, /docs/, /doc/, /sheets/, /base/, /wiki/, /file/."
        )
    return value


def validate_target_type(target_type: str) -> str:
    value = (target_type or "").strip().lower()
    if value != DEFAULT_TARGET_TYPE:
        raise ValueError(f"Only target_type={DEFAULT_TARGET_TYPE!r} is supported, got: {target_type!r}")
    return value


def get_workspace_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "inner_skills").exists():
            return parent
    raise RuntimeError("Unable to locate workspace root containing inner_skills/")


def run_move_to_personal(document_url: str, target_type: str = DEFAULT_TARGET_TYPE) -> str:
    workspace_root = get_workspace_root()
    move_script = workspace_root / "inner_skills" / "lark" / "mcp_lark_move_lark_doc.py"
    if not move_script.exists():
        raise FileNotFoundError(f"Lark MCP move script not found: {move_script}")

    payload = {
        "document_urls": [validate_document_url(document_url)],
        "target_type": validate_target_type(target_type),
    }

    result = subprocess.run(
        ["python3", str(move_script), json.dumps(payload, ensure_ascii=False)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "move_lark_doc failed\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Move a Lark/Feishu document into personal space via MCP.")
    parser.add_argument("document_url", help="完整飞书文档链接，例如 https://bytedance.larkoffice.com/docx/<token>")
    parser.add_argument(
        "--target-type",
        default=DEFAULT_TARGET_TYPE,
        help=f"Only {DEFAULT_TARGET_TYPE!r} is supported. Default: {DEFAULT_TARGET_TYPE}",
    )
    args = parser.parse_args()

    try:
        output = run_move_to_personal(args.document_url, args.target_type)
        if output:
            print(output)
        print("Success: document is ensured in personal space via Lark MCP move flow.")
        return 0
    except Exception as exc:  # noqa: PERF203
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
