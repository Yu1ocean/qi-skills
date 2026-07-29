#!/usr/bin/env python3
"""Runtime validation helper for performance-review-writer inputs.

This script is intentionally small and deterministic. It validates that a
performance writing payload has enough structure before any downstream document
or registry write operation consumes it.
"""

import json
import sys
from pathlib import Path

REQUIRED_STEPS = [
    "素材召回",
    "OKR 对齐",
    "影响力量化",
    "价值观映射",
    "向上汇报改写",
]


def validate_payload(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    steps = payload.get("completed_steps", [])
    missing = [step for step in REQUIRED_STEPS if step not in steps]
    if missing:
        raise ValueError(f"missing required workflow steps: {', '.join(missing)}")

    outputs = payload.get("key_outputs", [])
    if not isinstance(outputs, list) or len(outputs) == 0:
        raise ValueError("key_outputs must contain at least one performance output item")
    if len(outputs) > 5:
        raise ValueError("key_outputs must not exceed 5 items")

    for index, item in enumerate(outputs, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"key_outputs[{index}] must be an object")
        for field in ["title", "role", "impact", "evidence_status"]:
            if not item.get(field):
                raise ValueError(f"key_outputs[{index}] missing field: {field}")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_payload.py <payload.json>", file=sys.stderr)
        return 2

    payload_path = Path(sys.argv[1])
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    validate_payload(payload)
    print("OK: performance review payload passed validation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
