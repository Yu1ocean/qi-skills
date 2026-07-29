#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_lark_sheet.py  (v3.5 防丢链根治级重构)
====================================================

【背景】
v3.4 及之前版本走的取数路径是：lark MCP 把整张飞书表格导出成 xlsx → openpyxl
读 → 转 csv。问题是：xlsx 落盘时 HYPERLINK 公式只保留**可视文本**，URL 全部
被丢掉，导致后续 link_present 类断言完全失效。

【根治方案】
弃用 xlsx 导出，改用 inner_skills/lark-sheets 的 CLI（lark-sheets-cli sheets +read）
**双抓融合**：
  - --value-render-option Formula   → 拿底层公式（含 HYPERLINK 完整 URL）
  - --value-render-option ToString  → 拿可视化纯文本

每个原列被扩展为两列：
  - <原列名>          : 可视化文本（来自 ToString，行为与历史脚本兼容）
  - <原列名>__url     : 从 Formula 层用正则 HYPERLINK\\s*\\(\\s*"([^"]+)"
                       提取出的真实 URL；非 HYPERLINK 单元格此列为空字符串

【输出】
- CSV 文件（utf-8-sig，逗号分隔）
- pandas.DataFrame（同列结构）

【健壮性】
- subprocess 调用 lark-sheets-cli 失败时抛非 0 退出码，并打印明确报错
- Formula 层抓取若返回空（无公式 / 无权限）时优雅降级为只用 ToString 值，
  并在 stderr 显式提示 "NO_FORMULA_LAYER"
- 支持 wiki 链接：自动调 lark-sheets-cli wiki spaces get_node 解析 obj_token

【CLI 用法】
    python3 fetch_lark_sheet.py \\
        --url "https://bytedance.larkoffice.com/sheets/xxx" \\
        --sheet-id "yyy" \\
        --range "A1:Z500" \\
        --output /tmp/sheet.csv

或：

    python3 fetch_lark_sheet.py \\
        --spreadsheet-token "xxx" \\
        --sheet-id "yyy" \\
        --range "A1:Z500" \\
        --output /tmp/sheet.csv

【函数级 API】（供 v3_engine.py 调用）
    fetch_sheet_with_links(token, sheet_id, range_, output_csv) -> pd.DataFrame
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# --- L2 默认层：合规默认值 -------------------------------------------------
DEFAULT_LARK_SHEETS_CLI = (
    Path(__file__).resolve().parents[3]
    / "inner_skills"
    / "lark-sheets"
    / "bin"
    / "lark-sheets-cli"
)
DEFAULT_HYPERLINK_REGEX = re.compile(
    r'HYPERLINK\s*\(\s*"([^"]+)"', re.IGNORECASE
)
DEFAULT_OUTPUT_ENCODING = "utf-8-sig"
DEFAULT_VALUE_RENDER_FORMULA = "Formula"
DEFAULT_VALUE_RENDER_TOSTRING = "ToString"

# --- L3 断言层：运行时熔断 -------------------------------------------------


class LarkSheetFetchError(RuntimeError):
    """底层 lark-sheets-cli 调用失败 / 返回结构异常。"""


def validate_cli_available(cli_path: Path) -> None:
    """运行时强制校验：lark-sheets-cli 必须可执行。"""
    if not cli_path.exists():
        raise LarkSheetFetchError(
            f"lark-sheets-cli not found at {cli_path}. "
            "Make sure inner_skills/lark-sheets is installed."
        )
    if not os.access(cli_path, os.X_OK):
        raise LarkSheetFetchError(
            f"lark-sheets-cli is not executable: {cli_path}"
        )
    assert cli_path.exists() and os.access(cli_path, os.X_OK), (
        "validate_cli_available post-condition failed"
    )


# --- 内部工具 -------------------------------------------------------------


def _run_cli_json(cli_path: Path, args: List[str]) -> Dict[str, Any]:
    """运行 lark-sheets-cli，并把 stdout 解析为 JSON。"""
    cmd = [str(cli_path), *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise LarkSheetFetchError(f"failed to spawn lark-sheets-cli: {exc}") from exc

    if result.returncode != 0:
        raise LarkSheetFetchError(
            "lark-sheets-cli failed.\n"
            f"cmd: {' '.join(cmd)}\n"
            f"exit_code: {result.returncode}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    raw = (result.stdout or "").strip()
    if not raw:
        raise LarkSheetFetchError(
            "lark-sheets-cli returned empty stdout.\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stderr: {result.stderr}"
        )

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LarkSheetFetchError(
            "lark-sheets-cli returned non-JSON stdout.\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout (first 500 chars): {raw[:500]}"
        ) from exc


def _resolve_spreadsheet_token(
    cli_path: Path, url: Optional[str], spreadsheet_token: Optional[str]
) -> str:
    """优先使用 spreadsheet_token；否则尝试从 URL 解析。

    支持飞书 wiki 链接（/wiki/<wiki_token>）：调 wiki spaces get_node 解析。
    """
    if spreadsheet_token:
        return spreadsheet_token.strip()

    if not url:
        raise LarkSheetFetchError("either --url or --spreadsheet-token must be provided")

    url = url.strip()
    # 直接命中 /sheets/<token>
    m = re.search(r"/sheets/([A-Za-z0-9]+)", url)
    if m:
        return m.group(1)

    # 命中 /wiki/<wiki_token> → 通过 CLI 解析为 obj_token
    m = re.search(r"/wiki/([A-Za-z0-9]+)", url)
    if m:
        wiki_token = m.group(1)
        params = json.dumps({"token": wiki_token}, ensure_ascii=False)
        data = _run_cli_json(
            cli_path,
            ["wiki", "spaces", "get_node", "--params", params],
        )
        node = data.get("node") or data.get("data", {}).get("node") or {}
        obj_type = node.get("obj_type")
        obj_token = node.get("obj_token")
        if obj_type != "sheet":
            raise LarkSheetFetchError(
                f"Wiki node is not a sheet: obj_type={obj_type}, url={url}"
            )
        if not obj_token:
            raise LarkSheetFetchError(
                f"Wiki node has no obj_token: {data}"
            )
        return obj_token

    raise LarkSheetFetchError(f"Unable to resolve spreadsheet token from url: {url}")


def _build_full_range(sheet_id: str, range_: str) -> str:
    """lark-sheets-cli 接受三种 range 形式：sheetId!A1:D10、A1:D10、单 cell。

    我们这里统一拼接成 sheetId!range 形式（除非 range 已含 !）。
    """
    if "!" in range_:
        return range_
    return f"{sheet_id}!{range_}"


def _read_values(
    cli_path: Path,
    spreadsheet_token: str,
    sheet_id: str,
    range_: str,
    value_render_option: str,
) -> List[List[Any]]:
    """调 lark-sheets-cli sheets +read，返回二维数组（行 × 列）。

    返回结构按 lark-sheets schema：
      data.valueRange.values  →  二维数组
    若值为空（无数据 / 无公式层），返回 [[]]（保留至少一个空行避免 None）。
    """
    full_range = _build_full_range(sheet_id, range_)
    args = [
        "sheets",
        "+read",
        "--spreadsheet-token",
        spreadsheet_token,
        "--sheet-id",
        sheet_id,
        "--range",
        full_range,
        "--value-render-option",
        value_render_option,
    ]
    data = _run_cli_json(cli_path, args)

    # lark openapi response 可能在 data.valueRange.values
    value_range = (
        data.get("valueRange")
        or data.get("data", {}).get("valueRange")
        or {}
    )
    values = value_range.get("values")
    if values is None:
        return []
    return values


# --- 核心融合逻辑 ---------------------------------------------------------


def _extract_url_from_formula_cell(cell: Any) -> str:
    """从 Formula 层单元格里提取 HYPERLINK URL；非 HYPERLINK 返回 ""。

    Formula 层单元格大多是字符串 "=HYPERLINK(\"https://...\",\"显示文本\")"。
    但飞书也可能返回结构化 dict（如 link / mention），这里尽量兜底。
    """
    if cell is None:
        return ""
    if isinstance(cell, str):
        m = DEFAULT_HYPERLINK_REGEX.search(cell)
        if m:
            return m.group(1).strip()
        # 部分单元格 ToString 也会返回纯 URL，归位 _to_display 处理
        return ""
    if isinstance(cell, dict):
        # 结构化 link
        if cell.get("type") == "url" and cell.get("link"):
            return str(cell["link"]).strip()
        text = cell.get("text") or ""
        if isinstance(text, str):
            m = DEFAULT_HYPERLINK_REGEX.search(text)
            if m:
                return m.group(1).strip()
        return ""
    if isinstance(cell, list):
        # 列表里偶尔会塞 segment，逐个找 HYPERLINK
        for item in cell:
            url = _extract_url_from_formula_cell(item)
            if url:
                return url
        return ""
    return ""


def _to_display(cell: Any) -> str:
    """ToString 层归一化为字符串。"""
    if cell is None:
        return ""
    if isinstance(cell, (str, int, float, bool)):
        return str(cell)
    if isinstance(cell, dict):
        # 一些飞书富文本 dict 有 text 字段
        if "text" in cell and isinstance(cell["text"], str):
            return cell["text"]
        return json.dumps(cell, ensure_ascii=False)
    if isinstance(cell, list):
        # 富文本 segments
        parts: List[str] = []
        for item in cell:
            parts.append(_to_display(item))
        return "".join(parts)
    return str(cell)


def _normalize_grid(values: List[List[Any]], n_cols: int) -> List[List[Any]]:
    """把矩阵补齐成 n_cols 列，避免行尾空单元格被吞。"""
    out: List[List[Any]] = []
    for row in values:
        row = list(row) if row is not None else []
        if len(row) < n_cols:
            row = row + [""] * (n_cols - len(row))
        out.append(row[:n_cols])
    return out


def _fuse_layers(
    tostring_grid: List[List[Any]],
    formula_grid: List[List[Any]],
) -> Tuple[List[str], List[List[Any]], List[List[str]]]:
    """融合 ToString + Formula 两层，返回：
        (headers, display_rows, url_rows)
    其中 display_rows[i][j] 是单元格可视文本，url_rows[i][j] 是 HYPERLINK 提取出的 URL（""=无）。
    """
    if not tostring_grid:
        return [], [], []

    # 列宽以两层中较大的为准
    n_cols_str = max((len(r) for r in tostring_grid), default=0)
    n_cols_fml = max((len(r) for r in formula_grid), default=0) if formula_grid else 0
    n_cols = max(n_cols_str, n_cols_fml)
    if n_cols == 0:
        return [], [], []

    tostring_grid = _normalize_grid(tostring_grid, n_cols)
    formula_grid = _normalize_grid(formula_grid, n_cols) if formula_grid else [
        [""] * n_cols for _ in tostring_grid
    ]

    # 第一行做表头（display 层），缺失时回退到通用 col_N
    raw_header_row = tostring_grid[0]
    headers: List[str] = []
    for idx, h in enumerate(raw_header_row):
        h_str = _to_display(h).strip()
        if not h_str:
            h_str = f"col_{idx + 1}"
        headers.append(h_str)

    display_rows: List[List[Any]] = []
    url_rows: List[List[str]] = []

    # 对齐 formula_grid 行数
    min_rows = min(len(tostring_grid), len(formula_grid))
    if min_rows < len(tostring_grid):
        # 补齐 formula 缺的行
        formula_grid = formula_grid + [[""] * n_cols for _ in range(len(tostring_grid) - min_rows)]

    for r in range(1, len(tostring_grid)):  # 跳过表头
        d_row = [_to_display(c) for c in tostring_grid[r]]
        u_row = [_extract_url_from_formula_cell(c) for c in formula_grid[r]]
        display_rows.append(d_row)
        url_rows.append(u_row)

    return headers, display_rows, url_rows


def _write_csv(
    output_csv: Path,
    headers: List[str],
    display_rows: List[List[Any]],
    url_rows: List[List[str]],
) -> None:
    """写出双列融合 CSV：每个原列后紧跟 <原列名>__url 列。"""
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    expanded_header: List[str] = []
    for h in headers:
        expanded_header.append(h)
        expanded_header.append(f"{h}__url")

    with output_csv.open("w", encoding=DEFAULT_OUTPUT_ENCODING, newline="") as f:
        writer = csv.writer(f)
        writer.writerow(expanded_header)
        for d_row, u_row in zip(display_rows, url_rows):
            row_out: List[str] = []
            for d_val, u_val in zip(d_row, u_row):
                row_out.append("" if d_val is None else str(d_val))
                row_out.append("" if u_val is None else str(u_val))
            writer.writerow(row_out)


# --- 公开 API -------------------------------------------------------------


def fetch_sheet_with_links(
    token: str,
    sheet_id: str,
    range_: str,
    output_csv: str | os.PathLike[str],
    *,
    cli_path: Path | None = None,
    is_url: bool = False,
) -> pd.DataFrame:
    """主入口（供 v3_engine.py 调用）。

    Args:
        token: 当 is_url=False 时为 spreadsheet_token；is_url=True 时为完整 URL
               （支持 /sheets/<token> 与 /wiki/<wiki_token>）。
        sheet_id: 工作表 ID。
        range_: A1 表达式（如 "A1:Z500"，可省 sheetId 前缀）。
        output_csv: 输出 CSV 路径。
        cli_path: 可选，自定义 lark-sheets-cli 路径（默认走仓库内）。
        is_url: 当 token 是 URL 时设为 True。

    Returns:
        pandas.DataFrame，列结构为「原列 + 原列__url」。
    """
    cli = cli_path or DEFAULT_LARK_SHEETS_CLI
    validate_cli_available(cli)

    spreadsheet_token = _resolve_spreadsheet_token(
        cli,
        url=token if is_url else None,
        spreadsheet_token=None if is_url else token,
    )

    # 第一抓：ToString
    tostring_values = _read_values(
        cli,
        spreadsheet_token,
        sheet_id,
        range_,
        DEFAULT_VALUE_RENDER_TOSTRING,
    )

    # 第二抓：Formula（带降级）
    formula_values: List[List[Any]] = []
    try:
        formula_values = _read_values(
            cli,
            spreadsheet_token,
            sheet_id,
            range_,
            DEFAULT_VALUE_RENDER_FORMULA,
        )
    except LarkSheetFetchError as exc:
        print(
            f"NO_FORMULA_LAYER: Formula layer fetch failed, fallback to ToString-only. "
            f"reason: {exc}",
            file=sys.stderr,
        )
        formula_values = []

    if not formula_values:
        # 显式标注降级，便于上层断言时统一识别
        print(
            "NO_FORMULA_LAYER: Formula layer empty; URL columns will all be blank.",
            file=sys.stderr,
        )

    headers, display_rows, url_rows = _fuse_layers(tostring_values, formula_values)

    output_path = Path(output_csv).resolve()
    _write_csv(output_path, headers, display_rows, url_rows)

    # 构造 DataFrame
    expanded_header: List[str] = []
    for h in headers:
        expanded_header.append(h)
        expanded_header.append(f"{h}__url")

    fused_rows: List[List[Any]] = []
    for d_row, u_row in zip(display_rows, url_rows):
        merged: List[Any] = []
        for d_val, u_val in zip(d_row, u_row):
            merged.append("" if d_val is None else str(d_val))
            merged.append("" if u_val is None else str(u_val))
        fused_rows.append(merged)

    df = pd.DataFrame(fused_rows, columns=expanded_header)
    return df


# --- CLI -----------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch a Lark sheet with HYPERLINK URLs preserved (v3.5)."
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="飞书表格 URL（支持 /sheets/ 与 /wiki/）")
    src.add_argument("--spreadsheet-token", help="飞书电子表格 token")

    parser.add_argument("--sheet-id", required=True, help="工作表 ID")
    parser.add_argument(
        "--range",
        required=True,
        dest="range_",
        help="A1 范围，如 'A1:Z500'，可省 sheetId 前缀",
    )
    parser.add_argument("--output", required=True, help="输出 CSV 路径")
    parser.add_argument(
        "--cli-path",
        default=str(DEFAULT_LARK_SHEETS_CLI),
        help="自定义 lark-sheets-cli 路径",
    )

    args = parser.parse_args()

    token = args.url if args.url else args.spreadsheet_token
    is_url = bool(args.url)

    df = fetch_sheet_with_links(
        token=token,
        sheet_id=args.sheet_id,
        range_=args.range_,
        output_csv=args.output,
        cli_path=Path(args.cli_path).resolve(),
        is_url=is_url,
    )

    print(f"FETCH_LARK_SHEET_DONE rows={len(df)} cols={len(df.columns)} output={args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
