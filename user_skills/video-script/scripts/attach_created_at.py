#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
attach_created_at —— 给 video-script 拆解结果注入创建时间元数据。

# [FIELD-CREATED_AT-v1] 创建时间字段，来源平台 publish_time，禁止删除
# 来源：ledger_year_audit_20260821 / DEC-20260821（热门剧本沉淀 P0 治理）

用途
----
video-script 的 case JSON 在交给下游 `script-archive` 之前，必须带上视频原始
发布时间（`created_at`）与时效状态（`freshness_status`）。否则归档端只能拿到
「不知道多久以前」的脚本案例 —— 这正是本轮 P0 审计发现的中位年龄 436 天问题。

字段契约（与 script-archive 两侧对齐，避免二次清洗）
--------------------------------------------------
    created_at        : `YYYY-MM-DD`；解析失败为字符串 `NULL`
    created_at_source : publish_time | metadata | snowflake | NULL
    freshness_status  : ✅ 时效内 | ⚠️ 历史存量 | ❓ 待核实

用法
----
    # 单文件原地注入
    python3 scripts/attach_created_at.py --in case.json --in-place

    # 目录批量 + 输出到新目录
    python3 scripts/attach_created_at.py --input-dir results/ --output-dir enriched/

    # 只做校验（不写盘），缺字段即非 0 退出
    python3 scripts/attach_created_at.py --input-dir results/ --verify-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from created_at_resolver import (  # noqa: E402
    SENTINEL_NULL,
    classify_freshness,
    resolve_created_at,
)


# [FIELD-CREATED_AT-v1] 创建时间字段，来源平台 publish_time，禁止删除
def enrich_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """
    注入 created_at / created_at_source / freshness_status。

    publish_time 缺失时走 video_id snowflake 反解；仍失败写字符串 `NULL`
    —— 严禁空串 / None / 0 / 今天，那会让断链案例伪装成有效时效数据。
    """
    created_at, source = resolve_created_at(case, null_sentinel=SENTINEL_NULL)
    case["created_at"] = created_at
    case["created_at_source"] = source
    case["freshness_status"] = classify_freshness(created_at)
    return case


def assert_case_created_at(case: Dict[str, Any], label: str = "case") -> None:
    """L3 运行时断言：输出结构必须含合法 created_at，缺失或空值即熔断。"""
    value = case.get("created_at")
    if value is None or str(value).strip() in {"", "0", "None"}:
        raise ValueError(
            f"[FIELD-CREATED_AT-v1] {label} 的 created_at 为空/None/0，"
            f"必须为 YYYY-MM-DD 或字符串 {SENTINEL_NULL}"
        )
    text = str(value).strip()
    if text != SENTINEL_NULL and not _is_iso_date(text):
        raise ValueError(
            f"[FIELD-CREATED_AT-v1] {label} 的 created_at={text!r} 格式非法，必须为 YYYY-MM-DD"
        )
    if not str(case.get("freshness_status", "")).strip():
        raise ValueError(f"[FIELD-CREATED_AT-v1] {label} 缺少 freshness_status 字段")


def _is_iso_date(text: str) -> bool:
    import re

    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", text))


def collect_files(args: argparse.Namespace) -> List[Path]:
    files: List[Path] = []
    if args.input_dir:
        files.extend(sorted(Path(args.input_dir).glob("*.json")))
    for item in args.input_file or []:
        files.append(Path(item))
    if not files:
        raise ValueError("未提供任何 case JSON（--input-dir / --in）")
    return files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Attach created_at / freshness metadata to video-script case JSON"
    )
    parser.add_argument("--input-dir")
    parser.add_argument("--in", "--input-file", dest="input_file", action="append", default=[])
    parser.add_argument("--output-dir")
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    files = collect_files(args)
    rows = []
    for path in files:
        case = json.loads(path.read_text(encoding="utf-8"))
        if args.verify_only:
            assert_case_created_at(case, label=path.name)
        else:
            case = enrich_case(case)
            assert_case_created_at(case, label=path.name)
            if args.in_place:
                path.write_text(
                    json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            elif args.output_dir:
                out_dir = Path(args.output_dir)
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / path.name).write_text(
                    json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8"
                )
        rows.append(
            {
                "file": path.name,
                "video_title": case.get("video_title") or case.get("title") or "NULL",
                "created_at": case.get("created_at"),
                "created_at_source": case.get("created_at_source"),
                "freshness_status": case.get("freshness_status"),
            }
        )

    print(json.dumps({"count": len(rows), "cases": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
