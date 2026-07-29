#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from task_flow_engine.chat_registry_sync import (
    DEFAULT_CHAT_REGISTRY_SPREADSHEET_URL,
    resolve_output_path,
    sync_chat_registry_from_feishu,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="从飞书 Chat Registry 主表拉取群配置，并覆盖工作区根目录 CHAT_REGISTRY.json"
    )
    parser.add_argument(
        "--spreadsheet",
        default=DEFAULT_CHAT_REGISTRY_SPREADSHEET_URL,
        help="Chat Registry 飞书电子表格 URL 或 token。默认使用主表 URL。",
    )
    parser.add_argument(
        "--sheet-title",
        default=None,
        help="工作表名称；不传时若表内只有一个工作表则自动选择。",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出 JSON 路径；默认覆盖工作区根目录 CHAT_REGISTRY.json。相对路径按 task-flow-engine 根目录解析。",
    )
    parser.add_argument(
        "--skip-auth",
        action="store_true",
        help="跳过 bytedcli-auth（仅用于外层已完成鉴权的场景）。",
    )
    args = parser.parse_args()

    result = sync_chat_registry_from_feishu(
        spreadsheet=args.spreadsheet,
        sheet_title=args.sheet_title,
        output_path=resolve_output_path(args.output),
        skip_auth=args.skip_auth,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
