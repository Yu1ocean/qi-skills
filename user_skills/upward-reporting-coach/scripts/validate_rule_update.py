#!/usr/bin/env python3
"""Runtime guard for upward-reporting-coach rule updates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ALLOWED_SCENARIOS = {"scene1", "scene2", "scene3"}
ALLOWED_RULE_STATUS = {"active", "proposed", "deprecated"}
ALLOWED_DIFF_TYPES = {"新增", "强化", "冲突"}


class RuleUpdateError(RuntimeError):
    pass


def validate_payload(payload: dict) -> None:
    scenario = str(payload.get("scenario", "")).strip()
    if scenario not in ALLOWED_SCENARIOS:
        raise RuleUpdateError(f"invalid scenario: {scenario}")

    updates = payload.get("rule_updates")
    if not isinstance(updates, list):
        raise RuleUpdateError("rule_updates must be a list")

    for idx, item in enumerate(updates, start=1):
        if not isinstance(item, dict):
            raise RuleUpdateError(f"rule_updates[{idx}] must be an object")

        diff_type = str(item.get("classification", "")).strip()
        if diff_type not in ALLOWED_DIFF_TYPES:
            raise RuleUpdateError(
                f"rule_updates[{idx}].classification must be one of {sorted(ALLOWED_DIFF_TYPES)}"
            )

        status = str(item.get("status", "")).strip()
        if status and status not in ALLOWED_RULE_STATUS:
            raise RuleUpdateError(
                f"rule_updates[{idx}].status must be one of {sorted(ALLOWED_RULE_STATUS)}"
            )

        if diff_type == "新增":
            required = ["rule_name", "definition", "boundary", "example"]
            missing = [field for field in required if not str(item.get(field, "")).strip()]
            if missing:
                raise RuleUpdateError(
                    f"rule_updates[{idx}] missing required fields for 新增: {', '.join(missing)}"
                )

        if diff_type == "冲突" and not str(item.get("conflict_resolution", "")).strip():
            raise RuleUpdateError(
                f"rule_updates[{idx}] conflict items require conflict_resolution"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("payload_path", help="Path to a JSON payload file")
    args = parser.parse_args()

    payload_path = Path(args.payload_path).resolve()
    if not payload_path.exists():
        raise RuleUpdateError(f"payload file not found: {payload_path}")

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    validate_payload(payload)
    print("VALID")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuleUpdateError as exc:
        print(f"INVALID: {exc}")
        raise SystemExit(2)
