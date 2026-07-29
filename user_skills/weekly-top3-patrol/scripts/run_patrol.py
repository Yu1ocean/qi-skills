#!/usr/bin/env python3
"""
兼容入口（已废弃）。

真实入口已统一为 patrol.py。
本文件仅保留为薄包装器，避免历史命令立即炸掉；执行时会把参数原样转发。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
REAL_ENTRY = HERE / "patrol.py"


def main() -> int:
    forwarded = [sys.executable, str(REAL_ENTRY), *sys.argv[1:]]
    print(
        "[DEPRECATED] run_patrol.py 已废弃，真实入口统一为 scripts/patrol.py；本次已自动转发。",
        file=sys.stderr,
    )
    proc = subprocess.run(forwarded, check=False)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
