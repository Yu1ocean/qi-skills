#!/usr/bin/env python3
"""Browser Tab GC log guard for info-miner.

目标：把 Browser Tab GC 的结构化日志写入固化成低自由度脚本，避免成功/失败文案与时间格式漂移。
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

LOG_PATH = Path("/workspace/.ephemeral_pool/browser_gc.log")
TIME_FORMAT = "%Y-%m-%d %H:%M"


class BrowserGCError(RuntimeError):
    """Raised when the Browser GC log cannot be written safely."""


def _timestamp() -> str:
    return dt.datetime.now().strftime(TIME_FORMAT)


def build_success_line(task_id: str, tabs: int, task_name: str) -> str:
    if not task_id.strip():
        raise BrowserGCError("task_id 不能为空")
    if tabs < 0:
        raise BrowserGCError("tabs 不能为负数")
    if not task_name.strip():
        raise BrowserGCError("task_name 不能为空")
    return f"[{_timestamp()}] [{task_id}] [Browser GC] closed {tabs} tabs | task: {task_name}"


def build_failure_line(task_id: str, reason: str) -> str:
    if not task_id.strip():
        raise BrowserGCError("task_id 不能为空")
    if not reason.strip():
        raise BrowserGCError("reason 不能为空")
    return f"[{_timestamp()}] [{task_id}] [Browser GC] FAILED: {reason}"


def append_line(line: str, log_path: Path = LOG_PATH) -> Path:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return log_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Append Browser Tab GC logs for info-miner.")
    parser.add_argument("--selftest", action="store_true", help="运行自检")
    subparsers = parser.add_subparsers(dest="command")

    success = subparsers.add_parser("success", help="记录成功关闭标签页的 GC 日志")
    success.add_argument("--task-id", required=True)
    success.add_argument("--tabs", required=True, type=int)
    success.add_argument("--task-name", required=True)

    failure = subparsers.add_parser("failure", help="记录 GC 失败日志")
    failure.add_argument("--task-id", required=True)
    failure.add_argument("--reason", required=True)

    args = parser.parse_args()
    if not args.selftest and not args.command:
        parser.error("必须提供 success / failure 子命令，或使用 --selftest")
    return args


def run_selftest() -> int:
    success_line = build_success_line("task_demo", 2, "demo task")
    failure_line = build_failure_line("task_demo", "demo failure")
    assert "closed 2 tabs" in success_line
    assert "FAILED: demo failure" in failure_line
    print("[browser_tab_gc] selftest passed")
    return 0


def main() -> int:
    args = parse_args()
    if args.selftest:
        return run_selftest()
    if args.command == "success":
        line = build_success_line(args.task_id, args.tabs, args.task_name)
    elif args.command == "failure":
        line = build_failure_line(args.task_id, args.reason)
    else:
        raise BrowserGCError(f"未知命令: {args.command}")
    path = append_line(line)
    print(line)
    print(f"[browser_tab_gc] appended -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
