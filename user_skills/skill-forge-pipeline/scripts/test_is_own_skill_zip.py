#!/usr/bin/env python3
"""Self-check for is_own_skill_zip() suffix tightening (V5.22)."""
import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location(
    "register_skill", pathlib.Path(__file__).with_name("register_skill.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SKILL = "skill-forge-pipeline"
CASES = [
    ("skill-forge-pipeline.zip", True),
    ("skill-forge-pipeline_v5.22.zip", True),
    ("skill-forge-pipeline_5.21.zip", True),
    ("skill-forge-pipeline (1).zip", True),
    ("skill-forge-pipeline-v4.zip", False),
    ("skill-forge-pipeline-v4_5.15.zip", False),
    ("skill-forge-pipeline_beta.zip", False),
    ("skill-forge-pipeline_old.zip", False),
    ("other-skill.zip", False),
]

failed = 0
for fname, expect in CASES:
    got = mod.is_own_skill_zip(fname, SKILL)
    ok = got == expect
    failed += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'} {fname} -> {got} (expect {expect})")

print("RESULT:", "ALL PASS" if not failed else f"{failed} FAILED")
sys.exit(1 if failed else 0)
