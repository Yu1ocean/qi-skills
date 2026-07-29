#!/usr/bin/env python3
"""Compatibility wrapper for legacy permission-fix entrypoint.

DEPRECATED in v7.3:
- No longer calls Drive Permission API with `AIME_USER_CLOUD_JWT`.
- Now delegates to `ensure_doc_in_personal.py`, which uses Lark MCP
  `move_lark_doc -> target_type=personal` to repair ownership/access.

Kept only to avoid breaking existing callers that still invoke the old filename.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_EMAIL = "yuqinan@bytedance.com"
DEFAULT_PERM = "full_access"
SUPPORTED_SEGMENTS = ("/docx/", "/docs/", "/doc/", "/sheets/", "/base/", "/wiki/", "/file/")


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


def validate_legacy_email(email: str) -> str:
    value = (email or "").strip().lower()
    if value != DEFAULT_EMAIL:
        raise ValueError(
            "grant_doc_permissions.py is deprecated. It can only keep backward compatibility for the default user "
            f"{DEFAULT_EMAIL!r}; got {email!r}. Use personal-space creation or a direct MCP move flow instead."
        )
    return value


def validate_legacy_perm(perm: str) -> str:
    value = (perm or "").strip().lower()
    if value != DEFAULT_PERM:
        raise ValueError(
            "grant_doc_permissions.py is deprecated and no longer supports arbitrary permission roles. "
            f"Expected {DEFAULT_PERM!r}, got {perm!r}."
        )
    return value


def run_personal_wrapper(document_url: str) -> str:
    helper = Path(__file__).resolve().with_name("ensure_doc_in_personal.py")
    if not helper.exists():
        raise FileNotFoundError(f"ensure_doc_in_personal.py not found: {helper}")

    result = subprocess.run(
        ["python3", str(helper), document_url],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "ensure_doc_in_personal wrapper failed\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="[DEPRECATED] Compatibility wrapper that now moves the document to personal space via MCP."
    )
    parser.add_argument("document_url", help="Doc URL, e.g. https://bytedance.larkoffice.com/docx/<token>")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help=f"Legacy compatibility only. Default: {DEFAULT_EMAIL}")
    parser.add_argument(
        "--perm",
        default=DEFAULT_PERM,
        choices=["view", "edit", "full_access"],
        help="Legacy compatibility only. Default: full_access",
    )
    args = parser.parse_args()

    try:
        document_url = validate_document_url(args.document_url)
        validate_legacy_email(args.email)
        validate_legacy_perm(args.perm)
        print(
            "[DEPRECATED] grant_doc_permissions.py no longer calls Drive Permission API. "
            "Delegating to move_lark_doc -> personal via ensure_doc_in_personal.py...",
            file=sys.stderr,
        )
        output = run_personal_wrapper(document_url)
        if output:
            print(output)
        print("Success: legacy permission repair request was converted into personal-space migration.")
        return 0
    except Exception as exc:  # noqa: PERF203
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
