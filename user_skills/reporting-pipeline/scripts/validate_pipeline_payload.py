#!/usr/bin/env python3
"""Validate reporting-pipeline handoff payload before formal output."""
import json
import sys
from pathlib import Path

REQUIRED_TOP_LEVEL = ["raw_inputs", "scenario", "deliverable"]
REQUIRED_DELIVERABLE = ["s1_materials", "s2_escalated_versions", "s3_scorecard"]


def fail(message: str) -> None:
    raise SystemExit(f"FAILED: {message}")


def validate_pipeline_payload(data: dict) -> None:
    """Runtime gate before any formal reporting or Feishu archival side effect."""
    if not isinstance(data, dict):
        raise ValueError("payload must be a JSON object")


def main() -> None:
    if len(sys.argv) != 2:
        fail("Usage: validate_pipeline_payload.py <payload.json>")
    path = Path(sys.argv[1])
    if not path.exists():
        fail(f"payload file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_pipeline_payload(data)

    for key in REQUIRED_TOP_LEVEL:
        if key not in data or data[key] in (None, "", []):
            fail(f"missing required top-level field: {key}")

    deliverable = data.get("deliverable")
    if not isinstance(deliverable, dict):
        fail("deliverable must be an object")

    for key in REQUIRED_DELIVERABLE:
        if key not in deliverable or deliverable[key] in (None, "", []):
            fail(f"missing required deliverable field: {key}")

    materials = deliverable.get("s1_materials")
    if not isinstance(materials, list) or not 1 <= len(materials) <= 5:
        fail("s1_materials must contain 1-5 focused work items")

    for idx, item in enumerate(materials, 1):
        if not isinstance(item, dict):
            fail(f"s1_materials[{idx}] must be an object")
        for field in ["topic", "role", "impact", "source", "evidence_status"]:
            if not item.get(field):
                fail(f"s1_materials[{idx}] missing {field}")

    versions = deliverable.get("s2_escalated_versions")
    if not isinstance(versions, dict):
        fail("s2_escalated_versions must be an object")
    for field in ["judgement_draft", "decision_draft"]:
        if not versions.get(field):
            fail(f"s2_escalated_versions missing {field}")

    scorecard = deliverable.get("s3_scorecard")
    if not isinstance(scorecard, dict):
        fail("s3_scorecard must be an object")
    score = scorecard.get("total_score")
    if not isinstance(score, (int, float)) or not 0 <= score <= 10:
        fail("s3_scorecard.total_score must be a number between 0 and 10")

    print("OK: reporting-pipeline payload contract passed")


if __name__ == "__main__":
    main()
