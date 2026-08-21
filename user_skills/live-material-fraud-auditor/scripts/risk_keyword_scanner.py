#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""材质造假 / 品牌授权风险关键词扫描器（只做召回，不做定性）。

输入：`HH:MM:SS` 绝对时间戳的逐字稿 Markdown。
输出：可取证命中表（JSON + CSV），字段：
    timestamp / seconds / text / category / risk_level / matched_keywords
    / groups / rule / need_human_review / review_reason / neighbor_window

风险判定完全按 SKILL.md 第 5 节，词表外化在 references/*.yaml。
所有输出行在落盘前都过 audit_guard.validate_hit_row()，四要素缺一即熔断。

用法：
    python3 scripts/risk_keyword_scanner.py --transcript transcript.md \
        --out-json hits.json --out-csv hits.csv
    python3 scripts/risk_keyword_scanner.py --self-test
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_guard import (  # noqa: E402
    DEFAULT_NEIGHBOR_WINDOW,
    AuditGuardError,
    parse_absolute_timestamp,
    validate_hit_row,
    validate_timestamp_absolute,
)

SKILL_ROOT = Path(__file__).resolve().parent.parent
MATERIAL_YAML = SKILL_ROOT / "references" / "material_risk_keywords.yaml"
BRAND_YAML = SKILL_ROOT / "references" / "brand_risk_keywords.yaml"

RISK_HIGH = "🔴 高"
RISK_MID_HIGH = "🟡 中-高"

# 逐字稿行形态：`- [00:01:23] text` / `[00:01:23] text` / `00:01:23 text` / `00:01:23 | text`
LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?\[?(?P<ts>\d{2,3}:[0-5]\d:[0-5]\d)\]?\s*(?:[|\-–:]\s*)?(?P<text>.+?)\s*$"
)


@dataclass
class Utterance:
    timestamp: str
    seconds: int
    text: str


@dataclass
class Hit:
    timestamp: str
    seconds: int
    text: str
    category: str
    risk_level: str
    matched_keywords: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    rule: str = ""
    need_human_review: bool = False
    review_reason: str = ""
    neighbor_window: str = ""


# ------------------------------------------------------------------ loading ---


def load_keyword_library(path: Path) -> dict[str, Any]:
    """载入词表；缺文件 / 结构不对直接熔断，避免静默降级成空词表跑出 0 命中。"""
    if not path.is_file():
        raise AuditGuardError(f"keyword library not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("groups"), dict):
        raise AuditGuardError(f"keyword library {path.name} must contain a 'groups' mapping")
    total = sum(len(g.get("keywords") or []) for g in data["groups"].values())
    if total == 0:
        raise AuditGuardError(f"keyword library {path.name} has zero keywords; refuse to scan")
    return data


def parse_transcript(text: str) -> list[Utterance]:
    """解析逐字稿；时间戳必须是绝对偏移且不倒退（复用 L3 闸门）。"""
    utterances: list[Utterance] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("|"):
            continue
        matched = LINE_RE.match(line)
        if not matched:
            continue
        stamp = matched.group("ts")
        body = matched.group("text").strip()
        if not body:
            continue
        utterances.append(Utterance(stamp, parse_absolute_timestamp(stamp), body))
    if not utterances:
        raise AuditGuardError(
            "no HH:MM:SS utterance parsed from transcript; "
            "check the transcript uses absolute offsets"
        )
    validate_timestamp_absolute([u.timestamp for u in utterances])
    return utterances


# ----------------------------------------------------------------- matching ---


def _find(keywords: Sequence[str], haystack_lower: str) -> list[str]:
    return [kw for kw in keywords if kw.lower() in haystack_lower]


def _group_hits(library: dict[str, Any], text_lower: str) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for group_name, group in library["groups"].items():
        found = _find(group.get("keywords") or [], text_lower)
        if found:
            hits[group_name] = found
    return hits


def _window(utterances: list[Utterance], index: int, size: int) -> list[Utterance]:
    start = max(0, index - size)
    end = min(len(utterances), index + size + 1)
    return utterances[start:end]


def scan(
    utterances: list[Utterance],
    material_lib: dict[str, Any],
    brand_lib: dict[str, Any],
    neighbor_window: int = DEFAULT_NEIGHBOR_WINDOW,
) -> list[Hit]:
    clarifiers = [c.lower() for c in (material_lib.get("clarifiers") or [])]
    escalation = [c.lower() for c in (brand_lib.get("escalation_components") or [])]
    confusable = brand_lib.get("asr_confusable") or {}

    material_label = material_lib.get("category_label", "材质造假")
    brand_label = brand_lib.get("category_label", "品牌/正品宣称")

    hits: list[Hit] = []

    for idx, utt in enumerate(utterances):
        text_lower = utt.text.lower()
        window = _window(utterances, idx, neighbor_window)
        window_text_lower = " ".join(u.text for u in window).lower()
        window_desc = f"{window[0].timestamp}~{window[-1].timestamp}"

        has_clarifier = any(c in window_text_lower for c in clarifiers)

        mat_hits = _group_hits(material_lib, text_lower)
        mat_window_hits = _group_hits(material_lib, window_text_lower)

        # ---- 材质造假 ----
        if mat_hits:
            rule = "material_claim_single"
            risk = RISK_MID_HIGH
            need_review = False
            reason = ""

            gold_claim = bool(mat_window_hits.get("real_gold_claim"))
            purity = bool(mat_window_hits.get("purity_stamp"))
            endorsement = bool(mat_window_hits.get("test_endorsement"))
            solid_claim = any(
                kw in window_text_lower for kw in ("solid", "no hollow", "real gold", "real golden")
            )

            if gold_claim and purity:
                rule = "real_gold_plated + 14K stamp"
                risk = RISK_HIGH
            if endorsement and solid_claim:
                rule = (
                    f"{rule} | test_endorsement + solid/real-gold"
                    if risk == RISK_HIGH
                    else "test_endorsement + solid/real-gold"
                )
                risk = RISK_HIGH

            if risk == RISK_HIGH and has_clarifier:
                risk = RISK_MID_HIGH
                need_review = True
                reason = "近邻窗口出现镀金澄清词，🔴 降级为 🟡 并转人工回听确认"

            hits.append(
                Hit(
                    timestamp=utt.timestamp,
                    seconds=utt.seconds,
                    text=utt.text,
                    category=material_label,
                    risk_level=risk,
                    matched_keywords=sorted({kw for kws in mat_hits.values() for kw in kws}),
                    groups=sorted(mat_hits.keys()),
                    rule=rule,
                    need_human_review=need_review,
                    review_reason=reason,
                    neighbor_window=window_desc,
                )
            )

        # ---- 品牌 / 正品宣称 ----
        brand_hits = _group_hits(brand_lib, text_lower)
        if brand_hits:
            matched_kws = sorted({kw for kws in brand_hits.values() for kw in kws})
            escalated = [kw for kw in escalation if kw in window_text_lower]
            if escalated:
                risk = RISK_HIGH
                rule = f"brand_claim + material_component({', '.join(escalated)}) within ±{neighbor_window} 句"
            else:
                risk = RISK_MID_HIGH
                rule = "brand_claim_single (需联查商品标题/详情页/包装/评论)"

            need_review = False
            reasons: list[str] = []
            for kw in matched_kws:
                info = confusable.get(kw.lower())
                if info:
                    need_review = True
                    reasons.append(f"{kw}: {info.get('note', 'ASR 疑似误识别')}")
            if need_review:
                reasons.append("疑似项不得作为已确认事实，需人工回听后定性")

            hits.append(
                Hit(
                    timestamp=utt.timestamp,
                    seconds=utt.seconds,
                    text=utt.text,
                    category=brand_label,
                    risk_level=risk,
                    matched_keywords=matched_kws,
                    groups=sorted(brand_hits.keys()),
                    rule=rule,
                    need_human_review=need_review,
                    review_reason="；".join(reasons),
                    neighbor_window=window_desc,
                )
            )

    for hit in hits:
        validate_hit_row(asdict(hit))
    return hits


# ------------------------------------------------------------------- output ---

CSV_FIELDS = [
    "timestamp",
    "seconds",
    "text",
    "category",
    "risk_level",
    "matched_keywords",
    "groups",
    "rule",
    "need_human_review",
    "review_reason",
    "neighbor_window",
]


def summarize(hits: list[Hit]) -> dict[str, Any]:
    return {
        "total": len(hits),
        "by_category": {
            cat: sum(1 for h in hits if h.category == cat)
            for cat in sorted({h.category for h in hits})
        },
        "by_risk_level": {
            lvl: sum(1 for h in hits if h.risk_level == lvl)
            for lvl in sorted({h.risk_level for h in hits})
        },
        "need_human_review": sum(1 for h in hits if h.need_human_review),
    }


def write_outputs(hits: list[Hit], out_json: Path | None, out_csv: Path | None) -> dict[str, Any]:
    summary = summarize(hits)
    payload = {"summary": summary, "hits": [asdict(h) for h in hits]}
    if out_json:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if out_csv:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        with out_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for hit in hits:
                row = asdict(hit)
                row["matched_keywords"] = "; ".join(row["matched_keywords"])
                row["groups"] = "; ".join(row["groups"])
                writer.writerow(row)
    return payload


# ---------------------------------------------------------------- self test ---

SAMPLE_TRANSCRIPT = """# sample transcript
- [00:00:05] welcome back guys, this one is real gold plated
- [00:00:35] you can see the 14K stamp right here on the clasp
- [00:01:10] it is waterproof, you can take a shower with it
- [00:02:00] this piece is solid, and it can pass the diamond test
- [00:02:30] let me check the comments for a second
- [00:02:45] thank you for the roses, appreciate it
- [00:03:00] we will ship out tomorrow morning
- [00:03:20] we are the official store for this design
- [00:03:40] link is in the basket down below
- [00:04:00] any question just type it here
- [00:04:20] moving on to the next piece now
- [00:05:00] this is just plating, gold color only, real golden look with 14K stamp
- [00:06:00] that is all for today, thanks for staying
"""


def self_test() -> int:
    print("risk_keyword_scanner self-test")
    material_lib = load_keyword_library(MATERIAL_YAML)
    brand_lib = load_keyword_library(BRAND_YAML)
    print(f"  [ok] libraries loaded (material groups={len(material_lib['groups'])}, "
          f"brand groups={len(brand_lib['groups'])})")

    utterances = parse_transcript(SAMPLE_TRANSCRIPT)
    assert len(utterances) == 13, f"expected 13 utterances, got {len(utterances)}"
    print(f"  [ok] parsed {len(utterances)} utterances with absolute timestamps")

    hits = scan(utterances, material_lib, brand_lib)
    summary = summarize(hits)
    print(f"  [ok] hits={summary['total']} by_risk={summary['by_risk_level']} "
          f"need_review={summary['need_human_review']}")

    by_ts = {}
    for hit in hits:
        by_ts.setdefault(hit.timestamp, []).append(hit)

    # 规则 1：real gold plated + 14K stamp 近邻叠加 -> 🔴 高
    high_material = [h for h in hits if h.category.startswith("材质") and h.risk_level == RISK_HIGH]
    assert high_material, "expected at least one 🔴 material hit"
    print(f"  [ok] rule real_gold+14K fired ({len(high_material)} rows)")

    # 规则 2：pass the diamond test + solid -> 🔴 高
    endorsement = [h for h in hits if "test_endorsement" in h.rule]
    assert endorsement, "expected test_endorsement escalation"
    print("  [ok] rule test_endorsement+solid fired")

    # 规则 3：official 单独出现 -> 🟡 中-高 且 need_human_review
    official = [h for h in by_ts.get("00:03:20", []) if h.category.startswith("品牌")]
    assert official, "expected brand hit at 00:03:20"
    assert official[0].risk_level == RISK_MID_HIGH, official[0].risk_level
    assert official[0].need_human_review is True, "official must be flagged for human review"
    print("  [ok] official -> 🟡 中-高 + need_human_review (老主顾 误识别隔离)")

    # 规则 4：澄清词把 🔴 降级为 🟡 并转人工
    clarified = [h for h in by_ts.get("00:05:00", []) if h.category.startswith("材质")]
    assert clarified, "expected material hit at 00:05:00"
    assert clarified[0].risk_level == RISK_MID_HIGH, clarified[0].risk_level
    assert clarified[0].need_human_review is True
    print("  [ok] clarifier downgrade 🔴 -> 🟡 + need_human_review")

    # 无风险句不得产出命中
    assert "00:06:00" not in by_ts, "clean utterance must not produce hits"
    print("  [ok] clean utterance produced no hit (no false positive)")

    # 负例：相对时间戳必须熔断
    try:
        parse_transcript("- [01:10] relative offset only\n")
    except AuditGuardError:
        print("  [ok] relative timestamp transcript -> blocked as expected")
    else:
        raise SystemExit("  [FAIL] relative timestamp transcript was accepted")

    print("SELF-TEST PASSED")
    return 0


# ---------------------------------------------------------------------- CLI ---


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="material/brand risk keyword scanner")
    parser.add_argument("--transcript", help="transcript markdown with HH:MM:SS absolute offsets")
    parser.add_argument("--out-json", help="hit table JSON output path")
    parser.add_argument("--out-csv", help="hit table CSV output path")
    parser.add_argument("--material-yaml", default=str(MATERIAL_YAML))
    parser.add_argument("--brand-yaml", default=str(BRAND_YAML))
    parser.add_argument("--neighbor-window", type=int, default=DEFAULT_NEIGHBOR_WINDOW)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    if not args.transcript:
        parser.error("--transcript is required (or use --self-test)")

    transcript_path = Path(args.transcript)
    if not transcript_path.is_file():
        raise AuditGuardError(f"transcript not found: {transcript_path}")

    material_lib = load_keyword_library(Path(args.material_yaml))
    brand_lib = load_keyword_library(Path(args.brand_yaml))
    utterances = parse_transcript(transcript_path.read_text(encoding="utf-8"))
    hits = scan(utterances, material_lib, brand_lib, args.neighbor_window)
    payload = write_outputs(
        hits,
        Path(args.out_json) if args.out_json else None,
        Path(args.out_csv) if args.out_csv else None,
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AuditGuardError as exc:
        print(f"SCAN BLOCKED: {exc}", file=sys.stderr)
        sys.exit(2)
