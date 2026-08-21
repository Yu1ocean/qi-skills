#!/usr/bin/env python3
"""EU AM 分层读写架构（3 底表 + 3 阅读视图）构建入口（L3 断言层护栏）。

职责边界（刻意极窄，与 ``sync_source_entry.py`` 完全同构）：
1. 断言唯一真相源 ``projects/eu-am-efficiency/build_layered_sheets.py`` 存在；
   缺失即 ``raise FileNotFoundError``，禁止静默失败或降级。
2. 以子进程方式原样转发调用，透传全部 CLI 参数与退出码。

禁止在本文件复制 build_layered_sheets.py 的任何业务逻辑（列映射、筛选口径、
INDEX+MATCH 公式生成、PROTECTED 白名单、+formula-verify 分段复扫等）——
重复真相源会导致「技能目录里的副本」与「projects 下的实现」漂移，
是本护栏要防的第一号事故。

用法（原生参数直接透传）：
    python3 scripts/layered_sync_entry.py --dry-run
    python3 scripts/layered_sync_entry.py --layer base
    python3 scripts/layered_sync_entry.py --layer view
    python3 scripts/layered_sync_entry.py --cache /path/to/records.ndjson

调用飞书链路时必须设置 include_secrets=true。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REL_BUILD_LAYERED = Path("projects") / "eu-am-efficiency" / "build_layered_sheets.py"


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


def resolve_build_layered(workspace_root: Path) -> Path:
    """L3 断言：真相源脚本必须存在，否则立刻熔断。"""
    target = (workspace_root / REL_BUILD_LAYERED).resolve()
    if not target.is_file():
        raise FileNotFoundError(
            "分层架构真相源缺失，拒绝继续（禁止在技能目录内复制副本兜底）："
            f"{target}\n"
            f"workspace_root={workspace_root}\n"
            "请确认 projects/eu-am-efficiency/build_layered_sheets.py 已就位，"
            "或通过环境变量 AIME_WORKSPACE_ROOT 指定正确的工作区根目录。"
        )
    return target


def main(argv: list[str]) -> int:
    workspace_root = locate_workspace_root()
    build_layered = resolve_build_layered(workspace_root)

    cmd = [sys.executable, str(build_layered), *argv]
    print(f"[layered_sync_entry] forwarding -> {' '.join(cmd)}", flush=True)
    completed = subprocess.run(cmd, cwd=str(build_layered.parent))
    if completed.returncode != 0:
        print(
            f"[layered_sync_entry] FAILED: build_layered_sheets.py exited with "
            f"{completed.returncode}",
            file=sys.stderr,
            flush=True,
        )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
