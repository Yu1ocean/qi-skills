#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ALLOWED_BUSINESS_ABILITY = {"不推荐", "中性", "强推荐", "不可错过"}
ALLOWED_JOB_FAMILIES = {"BD", "MKT"}
JOB_FAMILY_PROMPT_ROUTES = {
    "BD": "prompts/bd_model.md",
    "MKT": "prompts/mkt_model.md",
}
REQUIRED_BYTESTYLE_DIMENSIONS = {
    "始终创业", "多元兼容", "坦诚清晰", "求真务实", "敢为极致", "共同成长"
}


def resolve_job_family_prompt(job_family: str) -> str:
    route = JOB_FAMILY_PROMPT_ROUTES.get(job_family)
    if not route:
        allowed = ", ".join(sorted(ALLOWED_JOB_FAMILIES))
        raise ValueError(
            f"岗位-能力模型错配：无法为 job_family={job_family!r} 匹配能力模型。"
            f"当前仅支持 {allowed}。"
        )
    return route


def validate_transcript_source(payload: dict) -> None:
    transcript_source = payload.get("input_alignment", {}).get("transcript_source")
    if not transcript_source:
        raise ValueError("Missing required input_alignment.transcript_source")


def validate_job_family(payload: dict) -> None:
    job_family = payload.get("input_alignment", {}).get("job_family")
    if job_family not in ALLOWED_JOB_FAMILIES:
        allowed = ", ".join(sorted(ALLOWED_JOB_FAMILIES))
        raise ValueError(
            f"input_alignment.job_family must be one of [{allowed}], got {job_family!r}"
        )
    prompt_route = resolve_job_family_prompt(job_family)
    skill_root = Path(__file__).resolve().parents[1]
    prompt_path = skill_root / prompt_route
    if not prompt_path.exists():
        raise ValueError(
            f"岗位能力模型文件缺失：job_family={job_family!r} 应加载 {prompt_route}"
        )


def validate_business_ability(payload: dict) -> None:
    ability = payload.get("final_conclusion", {}).get("business_ability")
    if ability not in ALLOWED_BUSINESS_ABILITY:
        raise ValueError(f"Invalid business ability: {ability}")


def validate_star_timestamps(payload: dict) -> None:
    evidences = payload.get("star_evidence", [])
    if not evidences:
        raise ValueError("star_evidence must not be empty")
    for idx, item in enumerate(evidences, start=1):
        if not item.get("timestamp"):
            raise ValueError(f"star_evidence[{idx}] missing timestamp")


def validate_byte_style_dimensions(payload: dict) -> None:
    scores = payload.get("final_conclusion", {}).get("byte_style", {}).get("dimension_scores", [])
    dimensions = {item.get("dimension") for item in scores}
    missing = REQUIRED_BYTESTYLE_DIMENSIONS - dimensions
    if missing:
        raise ValueError(f"Missing ByteStyle dimensions: {sorted(missing)}")


def validate_output(payload: dict) -> None:
    validate_transcript_source(payload)
    validate_job_family(payload)
    validate_business_ability(payload)
    validate_star_timestamps(payload)
    validate_byte_style_dimensions(payload)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 scripts/validate_output.py <output_json_path>")
    path = Path(sys.argv[1])
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_output(payload)
    print("[PASSED] interview-hologram-scanner output validation passed")
