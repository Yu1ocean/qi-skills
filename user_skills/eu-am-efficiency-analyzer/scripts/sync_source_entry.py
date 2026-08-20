#!/usr/bin/env python3
"""EU AM 数据源同步入口（L3 断言层护栏）。

职责边界（刻意极窄）：
1. 断言唯一真相源 ``projects/eu-am-efficiency/source_sync.py`` 存在；
   缺失即 ``raise FileNotFoundError``，禁止静默失败或降级。
2. 以子进程方式原样转发调用，透传全部 CLI 参数与退出码。

禁止在本文件复制 source_sync.py 的任何业务逻辑——重复真相源会导致
「技能目录里的副本」与「projects 下的实现」漂移，是本护栏要防的第一号事故。

用法：
    python3 scripts/sync_source_entry.py [source_sync.py 的原生参数...]

调用飞书链路时必须设置 include_secrets=true。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REL_SOURCE_SYNC = Path("projects") / "eu-am-efficiency" / "source_sync.py"


def locate_workspace_root(start: Path | None = None) -> Path:
    """向上回溯定位 workspace 根目录（含 user_skills/ 的那一层）。"""
    env_root = os.environ.get("AIME_WORKSPACE_ROOT")
    if env_root:
        return Path(env_root).resolve()

    cur = (start or Path(__file__).resolve()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "user_skills").is_dir():
            return candidate
    # 兜底：user_skills/<skill>/scripts/ -> 上三级
    return Path(__file__).resolve().parents[3]


def resolve_source_sync(workspace_root: Path) -> Path:
    """L3 断言：真相源脚本必须存在，否则立刻熔断。"""
    target = (workspace_root / REL_SOURCE_SYNC).resolve()
    if not target.is_file():
        raise FileNotFoundError(
            "ETL 真相源缺失，拒绝继续（禁止在技能目录内复制副本兜底）："
            f"{target}\n"
            f"workspace_root={workspace_root}\n"
            "请确认 projects/eu-am-efficiency/source_sync.py 已就位，"
            "或通过环境变量 AIME_WORKSPACE_ROOT 指定正确的工作区根目录。"
        )
    return target


def main(argv: list[str]) -> int:
    workspace_root = locate_workspace_root()
    source_sync = resolve_source_sync(workspace_root)

    cmd = [sys.executable, str(source_sync), *argv]
    print(f"[sync_source_entry] forwarding -> {' '.join(cmd)}", flush=True)
    completed = subprocess.run(cmd, cwd=str(source_sync.parent))
    if completed.returncode != 0:
        print(
            f"[sync_source_entry] FAILED: source_sync.py exited with {completed.returncode}",
            file=sys.stderr,
            flush=True,
        )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
