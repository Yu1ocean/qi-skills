#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from scripts.state_store import assert_in_workspace_root


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_dlq(dlq_path: Path, record: Dict[str, Any]) -> None:
    assert_in_workspace_root(dlq_path)
    record = dict(record)
    record.setdefault("ts", _now_iso())
    line = json.dumps(record, ensure_ascii=False)
    dlq_path.parent.mkdir(parents=True, exist_ok=True)
    with dlq_path.open("a", encoding="utf-8") as f:
        f.write(line + "\\n")
