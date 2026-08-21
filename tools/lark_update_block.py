#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Update (or delete) a single block in a Lark doc via MCP.

Usage:
  python3 tools/lark_update_block.py '{
    "document_url": "https://bytedance.larkoffice.com/docx/xxx",
    "block_number": "BLOCK_185",
    "block_id": "doxcn...",
    "content": "..."  # empty string means delete
  }'
"""

from __future__ import annotations

import json
import subprocess
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("ERR: expects 1 JSON arg", file=sys.stderr)
        return 2

    cfg = json.loads(sys.argv[1])
    payload = {
        "document_url": cfg["document_url"],
        "markdown_file_path": cfg.get("markdown_file_path", ""),
        "modifications": [
            {
                "block_number": cfg["block_number"],
                "block_id": cfg["block_id"],
                "modification_type": "update",
                "content": cfg.get("content", ""),
            }
        ],
    }

    proc = subprocess.run(
        [
            sys.executable,
            "inner_skills/lark/mcp_lark_update_lark_doc.py",
            json.dumps(payload, ensure_ascii=False),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )

    print(proc.stdout)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
