#!/usr/bin/env python3
import argparse
import json
import os
import re
from pathlib import Path

DEFAULT_TEXT_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".scss", ".json", ".md"}
RISK_PATTERNS = [
    ("dynamic_eval", re.compile(r"\beval\s*\(|\bnew\s+Function\s*\(")),
    ("inline_script", re.compile(r"<script(?![^>]*src=)[^>]*>", re.IGNORECASE)),
    ("external_script", re.compile(r"<script[^>]+src=[\"']https?://", re.IGNORECASE)),
    ("external_stylesheet", re.compile(r"<link[^>]+href=[\"']https?://", re.IGNORECASE)),
    ("sensitive_context_read", re.compile(r"process\.env|import\.meta\.env|document\.cookie|localStorage|sessionStorage|AIME_USER_CLOUD_JWT")),
    ("iframe_usage", re.compile(r"<iframe\b|createElement\(['\"]iframe['\"]\)", re.IGNORECASE)),
    ("postmessage_usage", re.compile(r"postMessage\s*\(")),
]

ALLOWED_DEP_PREFIXES = (
    "react",
    "react-dom",
    "@types/",
    "@byted",
    "@byte",
    "@ies",
    "@arco",
)


def validate_target(target: Path):
    assert target is not None
    if not target.exists():
        raise FileNotFoundError(f"Path not found: {target}")


def iter_files(target: Path):
    if target.is_file():
        yield target
        return
    for path in target.rglob("*"):
        if path.is_file() and path.suffix.lower() in DEFAULT_TEXT_EXTENSIONS:
            yield path


def scan_file(path: Path):
    findings = []
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return findings

    for risk_name, pattern in RISK_PATTERNS:
        for match in pattern.finditer(content):
            line_no = content.count("\n", 0, match.start()) + 1
            findings.append({
                "risk": risk_name,
                "file": str(path),
                "line": line_no,
                "snippet": content.splitlines()[line_no - 1][:200],
            })
    return findings


def scan_package_json(target: Path):
    findings = []
    package_file = target / "package.json" if target.is_dir() else None
    if not package_file or not package_file.exists():
        return findings
    try:
        package = json.loads(package_file.read_text(encoding="utf-8"))
    except Exception:
        findings.append({"risk": "package_json_parse_error", "file": str(package_file), "line": 1, "snippet": "unable to parse package.json"})
        return findings

    deps = {}
    deps.update(package.get("dependencies", {}))
    deps.update(package.get("devDependencies", {}))
    for dep_name in sorted(deps):
        if not dep_name.startswith(ALLOWED_DEP_PREFIXES):
            findings.append({
                "risk": "third_party_dependency",
                "file": str(package_file),
                "line": 1,
                "snippet": dep_name,
            })
    return findings


def summarize(findings):
    severity_score = 0
    for item in findings:
        if item["risk"] in {"dynamic_eval", "external_script", "sensitive_context_read"}:
            severity_score += 3
        elif item["risk"] in {"inline_script", "third_party_dependency", "iframe_usage", "external_stylesheet"}:
            severity_score += 2
        else:
            severity_score += 1

    if severity_score >= 10:
        level = "high"
    elif severity_score >= 4:
        level = "medium"
    else:
        level = "low"

    advice = {
        "high": [
            "优先改回 AUI 官方组件与快速预览链路。",
            "去掉外链脚本、动态执行与敏感上下文裸读。",
            "补运行时、数据、产品三层兜底。",
        ],
        "medium": [
            "审查是否真的需要这些运行时能力。",
            "补异常边界与静态降级出口。",
        ],
        "low": [
            "整体风险可控，继续保持依赖收敛与降级出口。",
        ],
    }
    return level, advice[level]


def main():
    parser = argparse.ArgumentParser(description="Scan frontend preview assets for stability risks.")
    parser.add_argument("path", help="File or directory to scan")
    args = parser.parse_args()

    target = Path(args.path).resolve()
    validate_target(target)

    findings = []
    for file_path in iter_files(target):
        findings.extend(scan_file(file_path))
    if target.is_dir():
        findings.extend(scan_package_json(target))

    risk_level, advice = summarize(findings)
    output = {
        "path": str(target),
        "risk_level": risk_level,
        "finding_count": len(findings),
        "findings": findings,
        "advice": advice,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
