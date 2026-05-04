#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


class StateError(RuntimeError):
    pass


def _workspace_root() -> Path:
    # Prefer platform-provided absolute path
    env = os.environ.get("IRIS_WORKSPACE_PATH")
    if env:
        return Path(env).resolve()
    # Fallback: assume current working directory is workspace
    return Path.cwd().resolve()


def assert_in_workspace_root(path: Path) -> None:
    root = _workspace_root()
    try:
        path.resolve().relative_to(root)
    except Exception:
        raise StateError(f"禁止写入工作区之外的路径：{path}（workspace={root}）")


def load_state(path: Path) -> Dict[str, Any]:
    assert_in_workspace_root(path)
    if not path.exists():
        return {"version": 1, "targets": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise StateError(f"快照文件解析失败：{path} ({e})")


def save_state(path: Path, state: Dict[str, Any]) -> None:
    assert_in_workspace_root(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
