#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""FABE validator for product-copywriting.

用法示例：
1) 传入 JSON 字符串
python3 scripts/fabe_validator.py --json '{"产品名称":"便携咖啡机","Feature":["680g 机身"],"Advantage":["可单手启动萃取"],"Benefit":["通勤路上 3 分钟喝到热咖啡"],"Evidence":["实测 180 秒完成加热萃取"]}'

2) 传入 JSON 文件
python3 scripts/fabe_validator.py --file references/demo_complete.json

3) 严格模式（只要 FABE 不完整就直接熔断）
python3 scripts/fabe_validator.py --file references/demo_incomplete.json --strict
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class ValidationError(RuntimeError):
    """用于脚本输入、结构或业务门槛校验失败时的显式熔断。"""


DEFAULT_REQUIRED_FIELDS = ["feature", "advantage", "benefit", "evidence"]
DEFAULT_DIRECTION_COUNT = 3
DEFAULT_OUTPUT_LANGUAGE = "zh-CN"
DEFAULT_EMPTY_MARKERS = {"", "暂无", "没有", "无", "待补充", "未知", "n/a", "none", "null", "待确认"}
DEFAULT_VAGUE_BENEFIT_PATTERNS = [
    r"更好",
    r"更方便",
    r"更高级",
    r"更舒适",
    r"更轻松",
    r"更省心",
    r"更稳定",
    r"更专业",
    r"体验更好",
    r"品质更高",
    r"更有质感",
    r"更适合",
]
DEFAULT_CONCRETE_BENEFIT_HINTS = [
    "分钟", "小时", "秒", "天", "周", "月", "年",
    "℃", "度", "ml", "L", "g", "kg",
    "热", "冷", "温度", "口感", "通勤", "出门", "会议", "排队", "等待",
    "省时", "节省", "减少", "避免", "不漏", "防漏", "轻", "便携", "收纳",
    "续航", "清洗", "冲洗", "掌控", "安心", "松弛", "体面", "提神", "稳定",
]
DEFAULT_WEAK_EVIDENCE_MARKERS = {"用户都说好", "反馈不错", "效果很好", "应该可以", "感觉不错"}

ALIASES = {
    "product_name": ["product_name", "产品名称", "产品名", "name", "product"],
    "category": ["category", "产品类别", "品类", "类目", "product_category"],
    "feature": ["feature", "features", "Feature", "特征", "产品特征"],
    "advantage": ["advantage", "advantages", "Advantage", "优势", "产品优势"],
    "benefit": ["benefit", "benefits", "Benefit", "利益", "用户收益", "收益"],
    "evidence": ["evidence", "Evidence", "证据", "证明", "背书", "支撑依据"],
    "target_audience": ["target_audience", "目标人群", "人群", "适用人群"],
    "usage_scenario": ["usage_scenario", "使用场景", "场景"],
    "tone": ["tone", "希望传达的情绪", "气质", "文风", "参考文风"],
    "forbidden": ["forbidden", "禁用词", "禁区", "禁忌"],
}


@dataclass
class ValidationReport:
    product_name: str
    category: str
    ready_for_copywriting: bool
    missing_fields: list[str]
    vague_benefit_items: list[str]
    evidence_issues: list[str]
    weak_evidence_items: list[str]
    follow_up_questions: list[str]
    normalized_fabe: dict[str, list[str]]


def validate_input_source(args: argparse.Namespace) -> None:
    has_json = bool(args.json)
    has_file = bool(args.file)
    if has_json == has_file:
        raise ValidationError("必须且只能提供 --json 或 --file 其中之一。")


def validate_path(path: Path) -> None:
    if not path.exists():
        raise ValidationError(f"输入文件不存在：{path}")
    if not path.is_file():
        raise ValidationError(f"输入路径不是文件：{path}")


def load_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.json:
        raw = args.json
    else:
        file_path = Path(args.file).expanduser().resolve()
        validate_path(file_path)
        raw = file_path.read_text(encoding="utf-8")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"输入不是合法 JSON：{exc}") from exc

    validate_payload_schema(payload)
    return payload


def validate_payload_schema(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValidationError("顶层 JSON 必须是对象（object / dict）。")

    if not payload:
        raise ValidationError("输入对象不能为空。")

    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            continue
        if isinstance(value, list):
            if not all(isinstance(item, (str, int, float, bool)) for item in value):
                raise ValidationError(f"字段 {key!r} 的列表中存在不支持的复杂对象；请改成字符串列表。")
            continue
        raise ValidationError(f"字段 {key!r} 仅支持字符串、标量或字符串列表，当前类型为 {type(value).__name__}。")


def pick_first(payload: dict[str, Any], aliases: list[str]) -> Any:
    for alias in aliases:
        if alias in payload:
            return payload[alias]
    return None


def to_text_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        items = [part.strip() for part in re.split(r"[\n；;]+", str(value)) if part.strip()]

    if any("\u0000" in item for item in items):
        raise ValidationError(f"字段 {field_name!r} 中包含非法空字符。")
    return items


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for canonical, aliases in ALIASES.items():
        normalized[canonical] = pick_first(payload, aliases)

    normalized["product_name"] = str(normalized.get("product_name") or "").strip()
    normalized["category"] = str(normalized.get("category") or "").strip()
    normalized["target_audience"] = to_text_list(normalized.get("target_audience"), field_name="target_audience")
    normalized["usage_scenario"] = to_text_list(normalized.get("usage_scenario"), field_name="usage_scenario")
    normalized["tone"] = to_text_list(normalized.get("tone"), field_name="tone")
    normalized["forbidden"] = to_text_list(normalized.get("forbidden"), field_name="forbidden")

    for field in DEFAULT_REQUIRED_FIELDS:
        normalized[field] = to_text_list(normalized.get(field), field_name=field)

    validate_business_minimum(normalized)
    return normalized


def validate_business_minimum(normalized: dict[str, Any]) -> None:
    content_count = sum(len(normalized[field]) for field in DEFAULT_REQUIRED_FIELDS)
    if content_count == 0:
        raise ValidationError("至少要提供一部分 FABE 信息，不能四项都为空。")

    if not normalized["product_name"] and not normalized["category"]:
        raise ValidationError("至少提供『产品名称』或『产品类别』之一，便于后续文案判题。")


def is_empty_marker(text: str) -> bool:
    return text.strip().lower() in DEFAULT_EMPTY_MARKERS


def is_vague_benefit(text: str) -> bool:
    clean = re.sub(r"[\s，。、“”‘’：:；;,.!?！？()（）\-]", "", text)
    if not clean:
        return True

    if is_empty_marker(text):
        return True

    generic_hit = any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in DEFAULT_VAGUE_BENEFIT_PATTERNS)
    concrete_hit = any(hint.lower() in text.lower() for hint in DEFAULT_CONCRETE_BENEFIT_HINTS)

    if generic_hit and not concrete_hit:
        return True

    if len(clean) <= 8 and not concrete_hit:
        return True

    return False


def inspect_evidence(items: list[str]) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    weak_items: list[str] = []
    if not items:
        issues.append("Evidence 缺失")
        return issues, weak_items

    for item in items:
        if is_empty_marker(item):
            issues.append("Evidence 含空值占位")
            continue
        if item in DEFAULT_WEAK_EVIDENCE_MARKERS:
            weak_items.append(item)

    return issues, weak_items


def build_follow_up_questions(missing_fields: list[str], vague_benefit_items: list[str], evidence_issues: list[str], weak_evidence_items: list[str]) -> list[str]:
    questions: list[str] = []

    if "feature" in missing_fields:
        questions.append("这款产品最核心的客观特征是什么？请给出配置、材质、功能、结构或参数。")
    if "advantage" in missing_fields:
        questions.append("和普通方案、旧方案或竞品相比，它的具体优势在哪里？")
    if "benefit" in missing_fields:
        questions.append("这些优势最终会给用户带来什么可感知的结果？请避免只写『更好/更方便』。")
    if vague_benefit_items:
        questions.append("你提供的 Benefit 还偏空，请把它改写成具体结果，例如节省什么时间、减少什么麻烦、获得什么感受。")
    if "evidence" in missing_fields or evidence_issues:
        questions.append("这项卖点有什么证据支持？请补充数据、测试结果、认证、用户反馈、案例或对比信息。")
    if weak_evidence_items:
        questions.append("当前 Evidence 偏口语化或不可验证，请补成可核验的事实依据。")

    return questions


def build_report(normalized: dict[str, Any]) -> ValidationReport:
    missing_fields = [field for field in DEFAULT_REQUIRED_FIELDS if not normalized[field] or all(is_empty_marker(item) for item in normalized[field])]
    benefit_items = [item for item in normalized["benefit"] if not is_empty_marker(item)]
    vague_benefit_items = [item for item in benefit_items if is_vague_benefit(item)]
    evidence_issues, weak_evidence_items = inspect_evidence(normalized["evidence"])

    ready = not missing_fields and not vague_benefit_items and not evidence_issues
    follow_up_questions = build_follow_up_questions(missing_fields, vague_benefit_items, evidence_issues, weak_evidence_items)

    return ValidationReport(
        product_name=normalized["product_name"],
        category=normalized["category"],
        ready_for_copywriting=ready,
        missing_fields=missing_fields,
        vague_benefit_items=vague_benefit_items,
        evidence_issues=evidence_issues,
        weak_evidence_items=weak_evidence_items,
        follow_up_questions=follow_up_questions,
        normalized_fabe={field: normalized[field] for field in DEFAULT_REQUIRED_FIELDS},
    )


def validate_fabe_ready(report: ValidationReport) -> None:
    if report.ready_for_copywriting:
        return

    reasons: list[str] = []
    if report.missing_fields:
        reasons.append(f"缺失字段：{', '.join(report.missing_fields)}")
    if report.vague_benefit_items:
        reasons.append(f"Benefit 过于空泛：{' | '.join(report.vague_benefit_items)}")
    if report.evidence_issues:
        reasons.append(f"Evidence 问题：{' | '.join(report.evidence_issues)}")

    raise ValidationError("FABE 未补齐，禁止进入文案生成。" + "；".join(reasons))


def main() -> int:
    parser = argparse.ArgumentParser(description="校验产品文案输入是否满足 FABE 基本门槛。")
    parser.add_argument("--json", help="直接传入 JSON 字符串")
    parser.add_argument("--file", help="传入 JSON 文件路径")
    parser.add_argument("--strict", action="store_true", help="若 FABE 未补齐，则直接以异常熔断")
    parser.add_argument("--compact", action="store_true", help="输出紧凑 JSON，而不是 pretty JSON")
    args = parser.parse_args()

    validate_input_source(args)
    payload = load_payload(args)
    normalized = normalize_payload(payload)
    report = build_report(normalized)

    if args.strict:
        validate_fabe_ready(report)

    output = asdict(report)
    output["defaults"] = {
        "direction_count": DEFAULT_DIRECTION_COUNT,
        "output_language": DEFAULT_OUTPUT_LANGUAGE,
        "required_fields": DEFAULT_REQUIRED_FIELDS,
    }
    output["summary"] = "FABE 完整，可进入五法与三方向文案生成。" if report.ready_for_copywriting else "FABE 仍需补全，建议先追问再写文案。"

    if args.compact:
        print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
