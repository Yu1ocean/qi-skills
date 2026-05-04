#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Tuple


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def diff_feishu_messages(prev: Dict[str, Any], latest_messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    # Return (new_messages, new_state_fragment).
    last_seen = prev.get("last_seen_message_id") or ""
    # Messages are expected sorted desc; we will reverse to asc for diff
    msgs = list(latest_messages)
    msgs.sort(key=lambda m: (m.get("create_time") or "", m.get("message_id") or ""))

    new_msgs: List[Dict[str, Any]] = []
    for m in msgs:
        mid = str(m.get("message_id") or "")
        if not mid:
            continue
        if last_seen and mid == last_seen:
            new_msgs = []
            continue
        new_msgs.append(m)

    # If last_seen exists and not found, we conservatively only take tail up to N
    # But since the fetch window is limited, this is acceptable.

    new_last_seen = last_seen
    if msgs:
        new_last_seen = str(msgs[-1].get("message_id") or new_last_seen)

    return new_msgs, {"last_seen_message_id": new_last_seen}


def digest_sheet_matrix(matrix: List[List[Any]]) -> str:
    # Normalize to JSON for stable digest
    payload = json.dumps(matrix, ensure_ascii=False, separators=(",", ":"), default=str)
    return _sha256_text(payload)


def diff_sheet(prev: Dict[str, Any], matrix: List[List[Any]]) -> Tuple[bool, Dict[str, Any]]:
    prev_digest = prev.get("digest")
    digest = digest_sheet_matrix(matrix)
    changed = (prev_digest != digest)
    return changed, {"digest": digest, "rows": len(matrix), "cols": (len(matrix[0]) if matrix else 0)}
