#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EU AM 效率漏斗诊断 —— 薄封装 CLI（v1.0）

说明（如实标注）：
    本文件是围绕 `am_analysis_core.run_diagnosis` 新写的**薄封装 CLI**，
    并非从任何既有 `funnel_stage_analyzer.py` 迁移而来（该文件在源项目中不存在，
    漏斗阶段诊断能力本身已内聚在 `am_analysis_core.py`）。

职责：
    1. 读入快照 JSON（或 CSV 明细）→ 调用内核计算漏斗阶段 / 段转化 / 瓶颈；
    2. 在任何落盘副作用之前执行 L3 运行时断言（validate_*），失败即 raise 熔断；
    3. 导出结构化 JSON 结果。

用法：
    python3 scripts/run_funnel_diagnosis.py --snapshots snap.json --dim 行业 --out result.json
    python3 scripts/run_funnel_diagnosis.py --csv 明细_分析基盘.csv --dim 负责AM --out result.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from am_analysis_core import (  # noqa: E402
    FunnelSpec,
    build_snapshots_from_dataframe,
    export_json,
    run_diagnosis,
)

# ---------------------------------------------------------------------------
# L2 合规默认值（Defaults）
# ---------------------------------------------------------------------------
DEFAULT_DIM_NAME = "负责AM"
DEFAULT_OUTPUT_JSON = "am_funnel_diagnosis.json"
DEFAULT_SHEET_URL = "https://bytedance.my.larkoffice.com/sheets/Bi8msSkCqhBywbtRGlomkoYJylg"
DEFAULT_SHEET_NAME = "明细_分析基盘"
DEFAULT_EXCLUDE_AMS = ("罗才鑫",)
DEFAULT_BACKGROUND_COLOR = "#FFFFFF"  # 白底强制
DEFAULT_ZERO_TRUST = True


class DiagnosisGuardViolation(RuntimeError):
    """L3 断言层：物理熔断异常。"""


# ---------------------------------------------------------------------------
# L3 运行时断言层
# ---------------------------------------------------------------------------
def validate_input_path(path: str) -> Path:
    p = Path(path)
    if not p.is_file():
        raise DiagnosisGuardViolation(f"输入文件不存在，禁止继续：{p}")
    return p


def validate_snapshots(snapshots: dict) -> None:
    if not isinstance(snapshots, dict) or not snapshots:
        raise DiagnosisGuardViolation("snapshots 为空或结构非法，禁止进入计算。")
    assert all(isinstance(k, str) for k in snapshots), "snapshots key 必须为字符串"


def validate_zero_trust_passed(result: dict) -> None:
    """零信任校验必须 PASS，否则熔断，禁止导出/对外交付。"""
    checks = result.get("validation") or result.get("zero_trust") or {}
    status = str(checks.get("status", "")).upper() if isinstance(checks, dict) else ""
    fails = []
    if isinstance(checks, dict):
        items = checks.get("checks") or checks.get("items") or []
        if isinstance(items, list):
            fails = [c for c in items if str(c.get("status", "")).upper() == "FAIL"]
    if status == "FAIL" or fails:
        raise DiagnosisGuardViolation(
            f"零信任校验未通过（status={status}, fails={len(fails)}），禁止导出结果。"
        )


def validate_output_written(path: str) -> None:
    p = Path(path)
    if not p.is_file() or p.stat().st_size <= 2:
        raise DiagnosisGuardViolation(f"输出文件未真实落盘或为空：{p}")


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--snapshots", help="快照 JSON 路径")
    src.add_argument("--csv", help="明细 CSV 路径（由飞书 lark-sheets MCP 链路导出）")
    ap.add_argument("--dim", default=DEFAULT_DIM_NAME, help=f"分组维度列名，默认 {DEFAULT_DIM_NAME}")
    ap.add_argument("--out", default=DEFAULT_OUTPUT_JSON, help="结果 JSON 输出路径")
    ap.add_argument("--week-col", default=None, help="CSV 模式下的周次列名（可选）")
    args = ap.parse_args()

    if args.snapshots:
        p = validate_input_path(args.snapshots)
        snapshots = json.loads(p.read_text(encoding="utf-8"))
    else:
        import pandas as pd

        p = validate_input_path(args.csv)
        df = pd.read_csv(p)
        df = df[~df.get(args.dim, "").astype(str).isin(DEFAULT_EXCLUDE_AMS)]
        kwargs = {"week_col": args.week_col} if args.week_col else {}
        snapshots = build_snapshots_from_dataframe(df, dim_name=args.dim, **kwargs)

    validate_snapshots(snapshots)

    result = run_diagnosis(snapshots, spec=FunnelSpec.default(), dim_name=args.dim)
    if DEFAULT_ZERO_TRUST:
        validate_zero_trust_passed(result)

    export_json(result, args.out)
    validate_output_written(args.out)

    print(f"OK dim={args.dim} entities={len(snapshots)} out={os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DiagnosisGuardViolation as exc:
        print(f"FAILED（L3 熔断）: {exc}", file=sys.stderr)
        raise SystemExit(2)
