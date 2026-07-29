#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ALLOWED_HIRE_RECOMMENDATIONS = {
    "建议录用",
    "推进补面（指定补面问题）",
    "可保留观望",
    "暂缓",
    "不建议录用",
}
ALLOWED_CONFIDENCE = {"已证实", "高概率", "待验证"}
ALLOWED_SEVERITY = {"high", "medium", "low"}
ALLOWED_UNCERTAINTY = {"high", "medium", "low"}
ALLOWED_IMPACT = {"critical", "notable", "limited"}
ALLOWED_JOB_FAMILIES = {"BD", "MKT"}
ALLOWED_SUB_TYPES = {None, "MKT_LD"}
ALLOWED_FOLLOWUP_PRIORITY = {None, "high", "medium", "low"}
DEFAULT_RADAR_DIMENSIONS = {
    "业务理解", "结构化拆解", "数据敏感度", "推动力", "协同影响力", "学习迭代力"
}
MKT_LD_RADAR_DIMENSIONS = {
    "会讲故事，专业长板显著。", "会打仗", "会算账", "强领导力"
}


def validate_meta(payload: dict) -> None:
    meta = payload.get("meta", {})
    if meta.get("skill_name") != "interview-matrix-evaluator":
        raise ValueError("meta.skill_name must be interview-matrix-evaluator")
    if meta.get("analysis_language") != "zh-CN":
        raise ValueError("meta.analysis_language must be zh-CN")
    if int(meta.get("candidate_count", 0)) < 2:
        raise ValueError("meta.candidate_count must be >= 2")


def validate_decision_anchor(payload: dict) -> None:
    anchor = payload.get("decision_anchor", {})
    job_family = anchor.get("job_family")
    sub_type = anchor.get("sub_type")
    if job_family not in ALLOWED_JOB_FAMILIES:
        allowed = ", ".join(sorted(ALLOWED_JOB_FAMILIES))
        raise ValueError(f"decision_anchor.job_family must be one of [{allowed}], got {job_family!r}")
    if sub_type not in ALLOWED_SUB_TYPES:
        raise ValueError("decision_anchor.sub_type must be NULL or MKT_LD")
    if sub_type == "MKT_LD" and job_family != "MKT":
        raise ValueError("decision_anchor.sub_type=MKT_LD requires decision_anchor.job_family=MKT")


def validate_candidate_summaries(payload: dict) -> None:
    summaries = payload.get("candidate_summaries", [])
    if len(summaries) < 2:
        raise ValueError("candidate_summaries must contain at least 2 candidates")
    for idx, item in enumerate(summaries, start=1):
        if item.get("confidence_status") not in ALLOWED_CONFIDENCE:
            raise ValueError(f"candidate_summaries[{idx}] invalid confidence_status")
        if item.get("input_validity") == "invalid_input" and not item.get("invalid_reason"):
            raise ValueError(f"candidate_summaries[{idx}] invalid_input requires invalid_reason")


def validate_radar_overlay(payload: dict) -> None:
    radar = payload.get("radar_overlay", {})
    dimensions = radar.get("dimensions", [])
    if len(dimensions) < 4:
        raise ValueError("radar_overlay.dimensions must contain at least 4 dimensions")
    names = {item.get("dimension_name") for item in dimensions}
    anchor = payload.get("decision_anchor", {})
    expected_profile = "MKT_LD" if anchor.get("job_family") == "MKT" and anchor.get("sub_type") == "MKT_LD" else "default"
    if radar.get("radar_profile") != expected_profile:
        raise ValueError(f"radar_overlay.radar_profile must be {expected_profile}")
    if expected_profile == "MKT_LD":
        missing = MKT_LD_RADAR_DIMENSIONS - names
        extra = names - MKT_LD_RADAR_DIMENSIONS
        if missing or extra:
            raise ValueError(f"MKT_LD radar dimensions mismatch, missing={sorted(missing)}, extra={sorted(extra)}")
    else:
        missing = DEFAULT_RADAR_DIMENSIONS - names
        if missing:
            raise ValueError(f"Missing default radar dimensions: {sorted(missing)}")
    candidate_count = int(payload.get("meta", {}).get("candidate_count", 0))
    for idx, item in enumerate(dimensions, start=1):
        scores = item.get("candidate_scores", [])
        if len(scores) != candidate_count:
            raise ValueError(
                f"radar_overlay.dimensions[{idx}] candidate_scores count mismatch: expected {candidate_count}, got {len(scores)}"
            )


def validate_zero_trust_matrix(payload: dict) -> None:
    matrix = payload.get("zero_trust_matrix", [])
    if not matrix:
        raise ValueError("zero_trust_matrix must not be empty")
    for idx, item in enumerate(matrix, start=1):
        if item.get("severity") not in ALLOWED_SEVERITY:
            raise ValueError(f"zero_trust_matrix[{idx}] invalid severity")
        if item.get("uncertainty") not in ALLOWED_UNCERTAINTY:
            raise ValueError(f"zero_trust_matrix[{idx}] invalid uncertainty")
        if item.get("business_impact") not in ALLOWED_IMPACT:
            raise ValueError(f"zero_trust_matrix[{idx}] invalid business_impact")


def validate_ranking(payload: dict) -> None:
    rankings = payload.get("ranking_result", [])
    candidate_count = int(payload.get("meta", {}).get("candidate_count", 0))
    if len(rankings) != candidate_count:
        raise ValueError("ranking_result length must equal meta.candidate_count")
    ranking_values = sorted(item.get("ranking") for item in rankings)
    expected = list(range(1, candidate_count + 1))
    if ranking_values != expected:
        raise ValueError(f"ranking_result ranking must be consecutive integers {expected}, got {ranking_values}")
    for idx, item in enumerate(rankings, start=1):
        if item.get("hire_recommendation") not in ALLOWED_HIRE_RECOMMENDATIONS:
            raise ValueError(f"ranking_result[{idx}] invalid hire_recommendation")
        if not item.get("core_tradeoff_reason"):
            raise ValueError(f"ranking_result[{idx}] missing core_tradeoff_reason")


def validate_top_pick(payload: dict) -> None:
    final = payload.get("final_recommendation", {})
    top_pick = final.get("top_pick_candidate_id")
    ranked_ids = {item.get("candidate_id") for item in payload.get("ranking_result", [])}
    if top_pick is not None and top_pick not in ranked_ids:
        raise ValueError("final_recommendation.top_pick_candidate_id must appear in ranking_result")


def validate_followup_interview(payload: dict) -> None:
    followup = payload.get("followup_interview", {})
    candidate_id = followup.get("candidate_id")
    priority = followup.get("priority")
    if priority not in ALLOWED_FOLLOWUP_PRIORITY:
        raise ValueError("followup_interview.priority must be high/medium/low/NULL")
    ranked_ids = {item.get("candidate_id") for item in payload.get("ranking_result", [])}
    if candidate_id is not None and candidate_id not in ranked_ids:
        raise ValueError("followup_interview.candidate_id must appear in ranking_result when not NULL")
    if candidate_id is None:
        if priority is not None:
            raise ValueError("followup_interview.priority must be NULL when candidate_id is NULL")
        if followup.get("focus_questions") or followup.get("target_dimensions"):
            raise ValueError("followup_interview focus_questions/target_dimensions must be empty when candidate_id is NULL")
    else:
        if not followup.get("focus_questions"):
            raise ValueError("followup_interview.focus_questions must not be empty when candidate_id is set")
        if not followup.get("target_dimensions"):
            raise ValueError("followup_interview.target_dimensions must not be empty when candidate_id is set")


def validate_interviewer_feedback(payload: dict) -> None:
    feedback = payload.get("interviewer_feedback", [])
    if not feedback:
        raise ValueError("interviewer_feedback must not be empty")
    for idx, item in enumerate(feedback, start=1):
        if not item.get("interviewer_name"):
            raise ValueError(f"interviewer_feedback[{idx}] missing interviewer_name")
        suggestions = item.get("suggestions", [])
        if not (1 <= len(suggestions) <= 2):
            raise ValueError(f"interviewer_feedback[{idx}] suggestions count must be 1 or 2")


def validate_matrix_output(payload: dict) -> None:
    validate_meta(payload)
    validate_decision_anchor(payload)
    validate_candidate_summaries(payload)
    validate_radar_overlay(payload)
    validate_zero_trust_matrix(payload)
    validate_ranking(payload)
    validate_top_pick(payload)
    validate_followup_interview(payload)
    validate_interviewer_feedback(payload)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 scripts/validate_matrix_output.py <output_json_path>")
    path = Path(sys.argv[1])
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_matrix_output(payload)
    print("[PASSED] interview-matrix-evaluator output validation passed")
