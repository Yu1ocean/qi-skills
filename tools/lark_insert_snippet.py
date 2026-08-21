#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Insert a local markdown snippet into an existing Lark doc via MCP update tool.

This avoids manual JSON escaping in bash.

Usage:
  python3 tools/lark_insert_snippet.py '{
    "document_url": "https://bytedance.larkoffice.com/docx/xxx",
    "block_number": "BLOCK_1",
    "block_id": "doxcn...",
    "snippet_path": "output/weibo/feishu_assets/update_snippet.lark.md"
  }'

Note:
- This script expects bytedcli-auth already done (JWT present) when needed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("ERR: expects 1 JSON arg", file=sys.stderr)
        return 2

    cfg = json.loads(sys.argv[1])
    document_url = cfg["document_url"]
    block_number = cfg["block_number"]
    block_id = cfg["block_id"]
    snippet_path = Path(cfg["snippet_path"]).resolve()

    content = snippet_path.read_text(encoding="utf-8")

    payload = {
        "document_url": document_url,
        "markdown_file_path": str(snippet_path),
        "modifications": [
            {
                "block_number": block_number,
                "block_id": block_id,
                "modification_type": "insert",
                "content": content,
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
