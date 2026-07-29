#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灵感台账同步护栏脚本

目标：确保 info-miner 产生的灵感卡片记录被准确、闭环地存入指定台账。
Bitable ID: PRbvbUyLqaeITqsXNMRcRCM5nhh
Table ID: tblHHVXl9ObjSyRw
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path

# ---------- Defaults ----------
DEFAULT_APP_TOKEN = "PRbvbUyLqaeITqsXNMRcRCM5nhh"
DEFAULT_TABLE_ID = "tblHHVXl9ObjSyRw"

class InspirationArchiveError(RuntimeError):
    """灵感归档异常。"""

def archive_inspiration(
    subject: str,
    story_content: str,
    fact_content: str,
    image_url: str,
    screenshot_path: str,
    deployed_url: str
):
    """调用 cyber-inspiration-generator 的同步脚本执行写入。"""
    workspace_root = Path("/workspace") # Assuming standard workspace root
    # Try to find the actual workspace root if IRIS_WORKSPACE_PATH is set
    env_root = os.environ.get("IRIS_WORKSPACE_PATH")
    if env_root:
        workspace_root = Path(env_root)
    
    sync_script = workspace_root / "user_skills/cyber-inspiration-generator/scripts/update_bitable.py"
    
    if not sync_script.exists():
        # Try relative path from this script
        sync_script = Path(__file__).resolve().parents[3] / "user_skills/cyber-inspiration-generator/scripts/update_bitable.py"

    if not sync_script.exists():
        raise InspirationArchiveError(f"未找到灵感同步脚本：{sync_script}")

    cmd = [
        "python3", str(sync_script),
        subject,
        story_content,
        fact_content,
        image_url,
        screenshot_path,
        deployed_url
    ]
    
    print(f"Executing: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise InspirationArchiveError(
            f"灵感同步失败 (exit {result.returncode})\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
    
    print("✅ 灵感台账同步成功")
    print(result.stdout)

def main():
    parser = argparse.ArgumentParser(description="灵感台账同步工具")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--story", required=True)
    parser.add_argument("--fact", required=True)
    parser.add_argument("--image-url", required=True)
    parser.add_argument("--screenshot", required=True)
    parser.add_argument("--deployed-url", required=True)
    
    args = parser.parse_args()
    
    try:
        archive_inspiration(
            args.subject,
            args.story,
            args.fact,
            args.image_url,
            args.screenshot,
            args.deployed_url
        )
    except InspirationArchiveError as e:
        print(f"FAILED: {e}")
        sys.exit(2)
    except Exception as e:
        print(f"UNEXPECTED ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
