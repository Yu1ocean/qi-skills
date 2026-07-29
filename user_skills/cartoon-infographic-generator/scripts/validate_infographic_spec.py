#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

REQUIRED_TOP_LEVEL = [
    "title",
    "ratio",
    "language",
    "style",
    "modules",
]


def validate_spec(spec: dict) -> None:
    missing = [k for k in REQUIRED_TOP_LEVEL if k not in spec or spec[k] in (None, "", [])]
    if missing:
        raise ValueError(f"Missing required field(s): {', '.join(missing)}")

    if spec["ratio"] not in {"9:16", "16:9"}:
        raise ValueError("ratio must be either '9:16' or '16:9'")

    if spec["language"] not in {"中文", "中文简体", "zh-CN", "zh"}:
        raise ValueError("language must be Chinese for this skill")

    modules = spec["modules"]
    if not isinstance(modules, list):
        raise ValueError("modules must be a list")
    if not 3 <= len(modules) <= 5:
        raise ValueError("modules count must be between 3 and 5")

    for idx, module in enumerate(modules, start=1):
        if not isinstance(module, dict):
            raise ValueError(f"module #{idx} must be an object")
        if not module.get("heading"):
            raise ValueError(f"module #{idx} missing heading")
        bullets = module.get("bullets")
        if not isinstance(bullets, list) or not bullets:
            raise ValueError(f"module #{idx} must contain non-empty bullets")
        if len(bullets) > 4:
            raise ValueError(f"module #{idx} has too many bullets (>4)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate infographic spec before image generation")
    parser.add_argument("--file", required=True, help="Path to infographic spec JSON")
    args = parser.parse_args()

    spec_path = Path(args.file)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    validate_spec(spec)
    print("OK: infographic spec is valid")


if __name__ == "__main__":
    main()
