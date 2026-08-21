#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run prism_flush_llmproxy and save full stdout JSON to a target file.

Why: bash tool output is truncated; we need full JSON persisted to disk.
"""

import argparse
import os
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="Output json file path")
    args = ap.parse_args()

    out_path = args.out
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    cmd = [sys.executable, "tools/prism_flush_llmproxy.py", "--type", "all", "-o", "json"]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # Persist full stdout regardless of size.
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(p.stdout)

    # Keep a small, human-readable summary on stderr/stdout for logs.
    if p.returncode != 0:
        sys.stderr.write(p.stderr)
        raise SystemExit(p.returncode)

    # Print a tiny summary (safe for tool output limits)
    print(f"saved_to={out_path}")
    print(f"stderr_tail={p.stderr.strip()[-500:]}")


if __name__ == "__main__":
    main()
