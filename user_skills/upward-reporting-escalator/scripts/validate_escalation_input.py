#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ALLOWED_STAGES = {1, 2, 3}

L5_TRIGGER_KEYWORDS = {
    "performance": ["绩效", "自评", "职级", "调级", "评估", "校准"],
    "seller_focused": ["seller-focused", "seller focused", "seller", "商家", "招商", "卖家"],
    "owner_scope": ["owner", "负责人", "区域", "类目", "市场负责人", "业务负责人"],
    "level": ["L5", "l5", "level 5", "领域专家"],
}

L5_DIMENSIONS = [
    "角色定位",
    "业务范围",
    "策略与判断",
    "结构性解法",
    "生态协同",
    "外部影响力",
    "卖家策略",
]


class ValidationError(ValueError):
    pass


def load_payload(args):
    if args.json:
        return json.loads(args.json)
    if args.file:
        return json.loads(Path(args.file).read_text(encoding="utf-8"))
    raise ValidationError("必须通过 --json 或 --file 提供输入。")


def normalize_multiversion(payload):
    versions = payload.get("versions")
    if versions is None:
        return []
    if not isinstance(versions, list):
        raise ValidationError("versions 必须是数组。")
    normalized = []
    for idx, item in enumerate(versions, start=1):
        if not isinstance(item, dict):
            raise ValidationError(f"versions[{idx}] 必须是对象。")
        text = str(item.get("text", "")).strip()
        if not text:
            raise ValidationError(f"versions[{idx}] 缺少 text。")
        label = str(item.get("label", f"v{idx}")).strip() or f"v{idx}"
        normalized.append({"label": label, "text": text})
    return normalized


def validate_target_stage(payload):
    target_stage = payload.get("target_stage", 3)
    if isinstance(target_stage, str) and target_stage.isdigit():
        target_stage = int(target_stage)
    if target_stage not in ALLOWED_STAGES:
        raise ValidationError("target_stage 只能是 1 / 2 / 3。")
    return target_stage


def validate_source_text(payload, versions):
    source_text = str(payload.get("source_text", "")).strip()
    if not source_text and not versions:
        raise ValidationError("source_text 不能为空；若是多轮复盘，可改传 versions。")
    if source_text and len(source_text) < 20:
        raise ValidationError("source_text 过短，无法支撑向上汇报升级判断（至少 20 字）。")
    return source_text


def validate_decision_anchors(payload, target_stage):
    anchors = {
        "goal_anchor": str(payload.get("goal_anchor", "")).strip(),
        "time_window": str(payload.get("time_window", "")).strip(),
        "resource_binding": str(payload.get("resource_binding", "")).strip(),
        "support_request": str(payload.get("support_request", "")).strip(),
    }
    missing_for_stage3 = [k for k, v in anchors.items() if not v]
    if target_stage == 3 and len(missing_for_stage3) == len(anchors):
        raise ValidationError(
            "目标是第三版决策稿，但 goal_anchor / time_window / resource_binding / support_request 至少要提供一项。"
        )
    return anchors, missing_for_stage3


def detect_l5_benchmark(payload, source_text, versions):
    explicit_flag = bool(payload.get("enable_l5_benchmark", False))
    context_fields = [
        source_text,
        str(payload.get("context", "")),
        str(payload.get("audience", "")),
        str(payload.get("role_context", "")),
    ]
    context_fields.extend(item["text"] for item in versions)
    haystack = "\n".join(context_fields).lower()

    matched = []
    for group, keywords in L5_TRIGGER_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in haystack:
                matched.append({"group": group, "keyword": keyword})
                break

    enabled = explicit_flag or bool(matched)
    reasons = []
    if explicit_flag:
        reasons.append("explicit_flag")
    reasons.extend(f"{item['group']}:{item['keyword']}" for item in matched)

    missing_evidence_fields = [
        field
        for field in ["goal_anchor", "time_window", "resource_binding", "support_request", "business_scope", "stakeholders"]
        if not str(payload.get(field, "")).strip()
    ]

    return {
        "enabled": enabled,
        "reasons": reasons,
        "dimensions": L5_DIMENSIONS if enabled else [],
        "evidence_missing": missing_evidence_fields if enabled else [],
        "note": "L5 对标层已开启：先输出 gap 分析，缺失材料标注为证据待补。" if enabled else "L5 对标层未自动开启。",
    }


def validate_payload(payload):
    if not isinstance(payload, dict):
        raise ValidationError("输入必须是 JSON 对象。")

    versions = normalize_multiversion(payload)
    target_stage = validate_target_stage(payload)
    source_text = validate_source_text(payload, versions)
    anchors, missing_for_stage3 = validate_decision_anchors(payload, target_stage)
    l5_benchmark = detect_l5_benchmark(payload, source_text, versions)

    return {
        "target_stage": target_stage,
        "has_source_text": bool(source_text),
        "source_text_length": len(source_text),
        "version_count": len(versions),
        "anchors_present": [k for k, v in anchors.items() if v],
        "anchors_missing": missing_for_stage3,
        "l5_benchmark": l5_benchmark,
        "status": "ok",
    }


def main():
    parser = argparse.ArgumentParser(description="校验向上汇报三阶升级输入是否充分。")
    parser.add_argument("--json", help="直接传入 JSON 字符串")
    parser.add_argument("--file", help="传入 JSON 文件路径")
    args = parser.parse_args()

    payload = load_payload(args)
    result = validate_payload(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except ValidationError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
