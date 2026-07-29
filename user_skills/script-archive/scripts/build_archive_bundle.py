#!/usr/bin/env python3
import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_NULL = "NULL"
LEDGER_HEADERS = [
    "record_id",
    "batch_id",
    "archived_at",
    "platform",
    "market",
    "category",
    "account_name",
    "video_title",
    "video_url",
    "video_type_tags",
    "hook_summary",
    "methodology_summary",
    "risk_summary",
    "experiment_summary",
    "source_json",
]


def validate_input_files(files: List[Path]) -> None:
    if not files:
        raise ValueError("未提供任何 video-script 结果文件")


def validate_case_payload(case: Dict[str, Any]) -> None:
    if not (case.get("video_url") or case.get("source_url")):
        raise ValueError("案例缺少视频主键")


def validate_archive_outputs(report_path: str, ledger_path: str) -> None:
    if not report_path.endswith(".lark.md"):
        raise ValueError("报告主产物必须是 .lark.md")
    if not ledger_path.endswith(".csv"):
        raise ValueError("台账主产物必须是 .csv")


def discover_files(input_dir: Path, manifest_file: Path | None, files: List[str]) -> List[Path]:
    resolved: List[Path] = []
    if input_dir:
        resolved.extend(sorted(input_dir.glob("*.json")))
    if manifest_file:
        payload = json.loads(manifest_file.read_text(encoding="utf-8"))
        for item in payload.get("files", []):
            resolved.append(Path(item))
    for item in files:
        resolved.append(Path(item))
    uniq = []
    seen = set()
    for path in resolved:
        full = path.resolve()
        if full not in seen:
            seen.add(full)
            uniq.append(full)
    return uniq


def pick_first(data: Dict[str, Any], keys: List[str], default: str = DEFAULT_NULL) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def summarize_tags(value: Any) -> str:
    if isinstance(value, list):
        return "|".join(str(item) for item in value if str(item).strip()) or DEFAULT_NULL
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_NULL


def normalize_case(data: Dict[str, Any], source_json: Path, batch_id: str, idx: int) -> Dict[str, Any]:
    validate_case_payload(data)
    methodology = pick_first(data, ["可复用方法论", "methodology", "methodology_summary"])
    risk = pick_first(data, ["风险与短板", "risk", "risk_summary"])
    experiment = pick_first(data, ["AB实验建议", "experiment", "experiment_summary"])
    structure = pick_first(data, ["结构拆解", "structure_breakdown", "hook_summary"])
    video_title = pick_first(data, ["video_title", "title", "标题"])
    account_name = pick_first(data, ["account_name", "author", "账号"])
    video_url = pick_first(data, ["video_url", "source_url", "url"])
    return {
        "record_id": f"{batch_id}_{idx:03d}",
        "batch_id": batch_id,
        "archived_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "platform": pick_first(data, ["platform", "平台"]),
        "market": pick_first(data, ["market", "市场"]),
        "category": pick_first(data, ["category", "类目"]),
        "account_name": account_name,
        "video_title": video_title,
        "video_url": video_url,
        "video_type_tags": summarize_tags(pick_first(data, ["video_type_tags", "视频类型标签"], [])),
        "hook_summary": structure,
        "methodology_summary": methodology,
        "risk_summary": risk,
        "experiment_summary": experiment,
        "source_json": str(source_json),
    }


def build_report(cases: List[Dict[str, Any]], summary: Dict[str, Any]) -> str:
    top_tags = ", ".join(f"{k}×{v}" for k, v in summary["top_tags"].items()) or DEFAULT_NULL
    lines = [
        "## L1 结论先行",
        "",
        f"- 本批次共归档 **{summary['case_count']}** 条视频脚本案例。",
        f"- 高频视频类型标签：**{top_tags}**。",
        f"- 观察到的共性方法论：**{summary['methodology_brief']}**。",
        "",
        "<callout icon=\"bulb\" bgc=\"3\">",
        "  先本地成包，再走 MCP 写飞书：报告稿 `.lark.md` + 台账 `.csv` + 摘要 `.json` 必须同时存在。",
        "</callout>",
        "",
        "---",
        "",
        "## L2 批次方法论摘要",
        "",
        "1. **共性钩子**：优先看前三秒的利益承诺、反差、悬念或身份锁定。",
        "2. **主体推进**：高表现案例通常不是单点金句，而是连续的信息推进。",
        "3. **转化衔接**：内容高潮后紧跟 CTA 或结果展示，转化更顺。",
        "",
        "## L2 代表案例速览",
        "",
        "<table header-row=\"true\" header-col=\"false\" col-widths=\"180,140,260\">",
        "  <tr>",
        "    <td>视频</td>",
        "    <td>类型标签</td>",
        "    <td>可复用方法论</td>",
        "  </tr>",
    ]
    for case in cases[:10]:
        lines.extend([
            "  <tr>",
            f"    <td>{case['video_title']}</td>",
            f"    <td>{case['video_type_tags']}</td>",
            f"    <td>{case['methodology_summary']}</td>",
            "  </tr>",
        ])
    lines.extend([
        "</table>",
        "",
        "## L2 分案例拆解索引",
        "",
    ])
    for index, case in enumerate(cases, start=1):
        lines.extend([
            f"### 案例 {index}：{case['video_title']}",
            "",
            f"- **账号**：{case['account_name']}",
            f"- **视频链接**：[{case['video_url']}]({case['video_url']})",
            f"- **类型标签**：{case['video_type_tags']}",
            f"- **结构 / 钩子**：{case['hook_summary']}",
            f"- **可复用方法论**：{case['methodology_summary']}",
            f"- **风险与短板**：{case['risk_summary']}",
            f"- **AB 实验建议**：{case['experiment_summary']}",
            "",
        ])
    return "\n".join(lines) + "\n"


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build archive bundle from video-script json results")
    parser.add_argument("--input-dir")
    parser.add_argument("--manifest-file")
    parser.add_argument("--input-file", action="append", default=[])
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--report-file", required=True)
    parser.add_argument("--ledger-file", required=True)
    parser.add_argument("--summary-file", required=True)
    args = parser.parse_args()

    validate_archive_outputs(args.report_file, args.ledger_file)
    input_dir = Path(args.input_dir).resolve() if args.input_dir else None
    manifest_file = Path(args.manifest_file).resolve() if args.manifest_file else None
    files = discover_files(input_dir, manifest_file, args.input_file)
    validate_input_files(files)

    batch_id = f"SAR_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    cases: List[Dict[str, Any]] = []
    for idx, file_path in enumerate(files, start=1):
        data = json.loads(Path(file_path).read_text(encoding="utf-8"))
        cases.append(normalize_case(data, Path(file_path), batch_id, idx))

    tag_counter: Counter[str] = Counter()
    for case in cases:
        for tag in case["video_type_tags"].split("|"):
            tag = tag.strip()
            if tag and tag != DEFAULT_NULL:
                tag_counter[tag] += 1

    summary = {
        "batch_id": batch_id,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "case_count": len(cases),
        "top_tags": dict(tag_counter.most_common(5)),
        "methodology_brief": "高表现案例通常同时具备强钩子、连续推进和清晰 CTA。",
        "source_files": [str(path) for path in files],
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / args.report_file
    ledger_path = output_dir / args.ledger_file
    summary_path = output_dir / args.summary_file

    report_path.write_text(build_report(cases, summary), encoding="utf-8")
    write_csv(ledger_path, cases)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    result = {
        "batch_id": batch_id,
        "report_path": str(report_path.resolve()),
        "ledger_path": str(ledger_path.resolve()),
        "summary_path": str(summary_path.resolve()),
        "case_count": len(cases),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
