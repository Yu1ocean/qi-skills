#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""CDA Guardrails Selfcheck

目标：把“写在文档里的规则”固化成三层物理护栏：
- L1 认知层：Common Rationalizations / Red Flags / Verification 顶置
- L2 默认层：合规默认值（Defaults）显式存在
- L3 断言层：运行时 validate/assert + raise 的物理熔断

注意：这是 *技能锻造流水线* 的 Forge 阶段强制 Checkpoint。
- 当自检失败：必须退出码非 0，阻止后续 Celebrate / Archive。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


class GuardrailViolation(RuntimeError):
    pass


@dataclass
class CheckResult:
    ok: bool
    missing: list[str]
    details: list[str]


HIGH_RISK_HINTS = [
    # side-effects / write
    "写", "写入", "更新", "删除", "覆盖", "迁移", "赋权", "权限", "full_access",
    # lark assets
    "docx", "docs", "sheet", "sheets", "bitable", "base", "file", "drive", "云盘",
    # calendar
    "calendar", "日历",
    # concurrency
    "并发", "竞态",
]

MEDIUM_RISK_HINTS = [
    # execution / downstream action
    "执行", "脚本", "命令", "python3", "bash", "run", "deploy",
    "作为写指令", "输入", "操作指令",
]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def collect_corpus(skill_dir: Path) -> str:
    parts: list[str] = []
    for p in sorted(skill_dir.rglob("*")):
        if not p.is_file():
            continue
        if any(seg in {".git", "__pycache__", ".aime"} for seg in p.parts):
            continue
        if p.suffix.lower() not in {".md", ".py", ".txt", ".json"}:
            continue
        parts.append(_read_text(p))
    return "\n".join(parts)


def detect_risk_level(*, corpus: str, forced: str) -> str:
    forced = (forced or "auto").strip().lower()
    if forced in {"high", "medium", "low"}:
        return forced

    c = corpus.lower()
    high = any(h.lower() in c for h in HIGH_RISK_HINTS)
    if high:
        return "high"

    medium = any(h.lower() in c for h in MEDIUM_RISK_HINTS)
    if medium:
        return "medium"

    return "low"


def check_l1(skill_md: str) -> CheckResult:
    # remove yaml frontmatter
    text = re.sub(r"\A---[\s\S]*?---\s*", "", skill_md, count=1)
    head = "\n".join(text.splitlines()[:180])  # top section should contain it

    required = [
        ("Common Rationalizations", r"common\s+rationalizations|常见借口"),
        ("Red Flags", r"red\s+flags|危险信号"),
        ("Verification", r"verification|验收清单|强制验收"),
    ]

    missing = []
    details = []
    for name, pattern in required:
        if not re.search(pattern, head, flags=re.IGNORECASE):
            missing.append(f"L1:{name}")
            details.append(f"- 缺失 L1 认知层模块：{name}（要求在 SKILL.md 顶部出现）")

    return CheckResult(ok=(len(missing) == 0), missing=missing, details=details)


def check_l2(skill_md: str, corpus: str) -> CheckResult:
    # L2 can be satisfied by explicit Defaults section in SKILL.md
    # or by non-empty DEFAULT_ constants in runtime scripts.
    md_ok = bool(re.search(r"合规默认值|\bDefaults\b|默认值", skill_md, flags=re.IGNORECASE))
    py_ok = bool(re.search(r"\bDEFAULT_[A-Z0-9_]+\s*=\s*.+", corpus))

    if md_ok or py_ok:
        return CheckResult(ok=True, missing=[], details=[])

    return CheckResult(
        ok=False,
        missing=["L2:Defaults"],
        details=[
            "- 缺失 L2 默认层：未检测到『合规默认值/Defaults』说明，也未检测到 DEFAULT_* 默认常量",
        ],
    )


def check_l3(corpus: str) -> CheckResult:
    # Require validate/assert + raise in runtime.
    has_validate = bool(re.search(r"\bdef\s+validate_[a-zA-Z0-9_]+\s*\(", corpus))
    has_assert = "assert " in corpus
    has_raise = bool(re.search(r"\braise\s+[A-Za-z0-9_]+", corpus))

    if (has_validate or has_assert) and has_raise:
        return CheckResult(ok=True, missing=[], details=[])

    return CheckResult(
        ok=False,
        missing=["L3:RuntimeAssertions"],
        details=[
            "- 缺失 L3 断言层：未检测到 validate_*/assert 与 raise 组合（要求副作用前的物理熔断）",
        ],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-dir", required=True, help="目标技能目录，例如 user_skills/xxx")
    parser.add_argument("--risk", default="auto", help="风险等级：auto/high/medium/low")
    args = parser.parse_args()

    skill_dir = Path(args.skill_dir).resolve()
    if not skill_dir.is_dir():
        raise GuardrailViolation(f"skill dir not found: {skill_dir}")

    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        raise GuardrailViolation(f"SKILL.md not found: {skill_md_path}")

    skill_md = _read_text(skill_md_path)
    corpus = collect_corpus(skill_dir)

    risk = detect_risk_level(corpus=corpus, forced=args.risk)

    # required layers by risk
    required_layers = ["L1"]
    if risk in {"medium", "high"}:
        required_layers.append("L2")
    if risk == "high":
        required_layers.append("L3")

    results: list[CheckResult] = []
    l1 = check_l1(skill_md)
    results.append(l1)
    if "L2" in required_layers:
        results.append(check_l2(skill_md, corpus))
    if "L3" in required_layers:
        results.append(check_l3(corpus))

    missing = [m for r in results for m in r.missing]
    details = [d for r in results for d in r.details]

    print("\n=== CDA-Guardrails-Selfcheck ===")
    print(f"skill_dir: {skill_dir}")
    print(f"risk: {risk}")
    print(f"required_layers: {', '.join(required_layers)}")

    if missing:
        print("\nFAILED")
        print("missing:")
        for m in missing:
            print(f"- {m}")
        if details:
            print("\ndetails:")
            for d in details:
                print(d)
        return 2

    print("\nPASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GuardrailViolation as exc:
        print(f"FAILED\n- error: {exc}")
        raise SystemExit(2)
