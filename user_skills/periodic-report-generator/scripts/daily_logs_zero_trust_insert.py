#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daily_Logs 零信任安全插入（一键脚本）

目标：把“写日报→归档到 Daily_Logs 台账”的流程固化为可执行脚本，避免脏写/错列。

强约束：
- 必须先通过 MCP 下载台账，读取表头 Schema（第 1 行）
- 当存在【编号】列时必须自动生成主键（DL-YYYYMMDD / DL-YYYYMMDD-02 ...）
- 严格写入三列：[[编号, 日期, 日报内容]]
- 写后即读（RAW 原子锁）：写入后等待 >=2s，再次下载并读回刚写区域逐字段核对

注意：
- 本脚本依赖 feishu-doc-writing-guide 的 safe_insert_sheet_row.py 负责“安全写入/插行”。
- 本脚本不负责 bytedcli 登录；请在 Aime 执行时先挂载 bytedcli-auth 并 include_secrets=true。
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

import openpyxl

try:
    from byted_aime_sdk import call_aime_tool
except Exception as e:  # pragma: no cover
    raise RuntimeError(
        "未找到 byted_aime_sdk（无法调用 MCP）。请在 Aime 环境中执行此脚本。"
    ) from e


DEFAULT_SHEET_URL = "https://bytedance.larkoffice.com/sheets/ECQ0sDwmbhDex9tcUSjlkU7Bgdh"
DEFAULT_SHEET_NAME = "Daily_Logs"
DEFAULT_ROW_INDEX = 2  # 飞书表格行号（1-based）：第 1 行是表头；默认插入第 2 行

REQUIRED_HEADERS = ["编号", "日期", "日报内容"]


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _skill_root() -> Path:
    # scripts/xxx.py -> skill_root
    return Path(__file__).resolve().parents[1]


def _workspace_root() -> Path:
    # 向上回溯直到找到 inner_skills 目录（Aime VM 约定）
    p = Path(__file__).resolve()
    for parent in [p, *p.parents]:
        if (parent / "inner_skills").exists():
            return parent
    # 兜底：当前进程 cwd
    return Path.cwd().resolve()


def _parse_mcp_result_to_obj(res_text: str):
    """兼容 MCP 返回格式。

    call_aime_tool 可能返回：
    - JSON 字符串
    - Python 字面量字符串（如 ['a.xlsx']）
    - 纯文本
    """
    try:
        return json.loads(res_text)
    except Exception:
        pass

    try:
        return ast.literal_eval(res_text)
    except Exception:
        pass

    return res_text


def mcp_download_lark_sheet(document_url: str) -> list[str]:
    res = call_aime_tool(
        toolset="lark",
        tool_name="mcp:lark_lark_download",
        parameters={"document_url": document_url},
        response_format="text",
    )
    obj = _parse_mcp_result_to_obj(res)

    if isinstance(obj, dict) and "file_paths" in obj and isinstance(obj["file_paths"], list):
        return obj["file_paths"]
    if isinstance(obj, list) and all(isinstance(x, str) for x in obj):
        return obj

    raise RuntimeError(f"MCP 下载返回格式异常，无法解析：{res}")


def pick_xlsx(paths: list[str]) -> str:
    for p in paths:
        if str(p).lower().endswith(".xlsx"):
            return p
    raise RuntimeError(f"下载结果中未找到 .xlsx 文件：{paths}")


def read_sheet_headers(xlsx_path: str, sheet_name: str) -> list[str]:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    if sheet_name not in wb.sheetnames:
        raise RuntimeError(
            f"xlsx 中未找到工作表 {sheet_name}。可用工作表：{wb.sheetnames}"
        )
    ws = wb[sheet_name]
    headers: list[str] = []
    for cell in ws[1]:
        v = cell.value
        if v is None:
            break
        v_str = str(v).strip()
        if not v_str:
            break
        headers.append(v_str)
    return headers


def list_existing_ids(xlsx_path: str, sheet_name: str) -> set[str]:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb[sheet_name]
    ids: set[str] = set()
    # 第一列：编号；从第 2 行开始
    for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
        v = row[0]
        if v is None:
            continue
        s = str(v).strip()
        if s:
            ids.add(s)
    return ids


def gen_daily_log_id(date_str: str, existing: set[str]) -> str:
    yyyymmdd = date_str.replace("-", "")
    base = f"DL-{yyyymmdd}"
    if base not in existing:
        return base

    # 冲突时追加递增后缀：-02, -03 ...
    i = 2
    while True:
        cand = f"{base}-{i:02d}"
        if cand not in existing:
            return cand
        i += 1


def read_row_values(xlsx_path: str, sheet_name: str, row_index: int, col_count: int) -> list[str | None]:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb[sheet_name]
    row = []
    for col in range(1, col_count + 1):
        row.append(ws.cell(row=row_index, column=col).value)
    # 统一转 str 便于比对
    return [None if v is None else str(v) for v in row]


def write_dlq(skill_root: Path, payload: dict) -> Path:
    dlq_dir = skill_root / "assets" / "dlq"
    _ensure_dir(dlq_dir)

    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    p = dlq_dir / f"daily_logs_dlq_{ts}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def snapshot(skill_root: Path, xlsx_path: str, stage: str) -> Path:
    snap_dir = skill_root / "assets" / "snapshots"
    _ensure_dir(snap_dir)

    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = snap_dir / f"daily_logs_{stage}_{ts}.xlsx"
    shutil.copyfile(xlsx_path, dst)
    return dst


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily_Logs 零信任安全插入（一键脚本）")
    parser.add_argument("--sheet-url", default=DEFAULT_SHEET_URL, help="飞书表格链接")
    parser.add_argument("--sheet-name", default=DEFAULT_SHEET_NAME, help="工作表名称")
    parser.add_argument("--date", default=dt.date.today().strftime("%Y-%m-%d"), help="日期 YYYY-MM-DD")
    parser.add_argument("--content", required=True, help="日报内容（建议约 100 字）")
    parser.add_argument("--row-index", type=int, default=DEFAULT_ROW_INDEX, help="插入行号（1-based），默认 2")
    parser.add_argument("--dry-run", action="store_true", help="只做 Schema 回捞与主键生成，不实际写入")

    args = parser.parse_args()

    skill_root = _skill_root()
    workspace_root = _workspace_root()

    # 1) MCP 下载（读 Schema）
    file_paths = mcp_download_lark_sheet(args.sheet_url)
    xlsx_path = pick_xlsx(file_paths)
    if not os.path.isabs(xlsx_path):
        xlsx_path = str((workspace_root / xlsx_path).resolve())

    pre_snap = snapshot(skill_root, xlsx_path, stage="pre")

    headers = read_sheet_headers(xlsx_path, args.sheet_name)
    if headers[: len(REQUIRED_HEADERS)] != REQUIRED_HEADERS:
        dlq_file = write_dlq(
            skill_root,
            {
                "type": "Daily_Logs_SchemaMismatch",
                "timestamp": dt.datetime.now().isoformat(),
                "sheet_url": args.sheet_url,
                "sheet_name": args.sheet_name,
                "expected_headers_prefix": REQUIRED_HEADERS,
                "actual_headers": headers,
                "payload": {
                    "date": args.date,
                    "content": args.content,
                },
                "note": "⚠️[数据断链_待自愈] Schema 不匹配，已熔断写入。",
            },
        )
        raise RuntimeError(
            "Daily_Logs 表头 Schema 不符合预期，已熔断并落 DLQ："
            f"\n- 预期前缀：{REQUIRED_HEADERS}"
            f"\n- 实际表头：{headers}"
            f"\n- DLQ：{dlq_file}"
        )

    existing_ids = list_existing_ids(xlsx_path, args.sheet_name)
    row_id = gen_daily_log_id(args.date, existing_ids)

    row_data = [[row_id, args.date, args.content]]

    print("[Schema] headers:")
    print(json.dumps(headers, ensure_ascii=False))
    print("[Insert] row_data:")
    print(json.dumps(row_data, ensure_ascii=False))
    print(f"[Snapshot] pre: {pre_snap}")

    if args.dry_run:
        print("[DryRun] 已跳过实际写入。")
        return 0

    # 2) 安全写入（委托 feishu-doc-writing-guide）
    safe_insert = (
        workspace_root
        / "user_skills"
        / "feishu-doc-writing-guide"
        / "scripts"
        / "safe_insert_sheet_row.py"
    )
    if not safe_insert.exists():
        raise RuntimeError(
            "未找到 feishu-doc-writing-guide/scripts/safe_insert_sheet_row.py。"
            "请确认该 Skill 已安装且路径可用。"
        )

    # 用 subprocess 调用，避免强耦合脚本内部实现。
    import subprocess

    cmd = [
        sys.executable,
        str(safe_insert),
        args.sheet_url,
        args.sheet_name,
        str(args.row_index),
        json.dumps(row_data, ensure_ascii=False),
    ]

    print("[Write] running:")
    print(" ".join(cmd))

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        dlq_file = write_dlq(
            skill_root,
            {
                "type": "Daily_Logs_InsertFailed",
                "timestamp": dt.datetime.now().isoformat(),
                "sheet_url": args.sheet_url,
                "sheet_name": args.sheet_name,
                "row_index": args.row_index,
                "row_data": row_data,
                "stderr": proc.stderr,
                "stdout": proc.stdout,
                "note": "⚠️[数据断链_待自愈] 写入失败，已落 DLQ。",
            },
        )
        raise RuntimeError(
            "safe_insert_sheet_row.py 执行失败，已熔断并落 DLQ："
            f"\n- DLQ：{dlq_file}"
            f"\n- stderr：\n{proc.stderr}"
        )

    print("[Write] ok. stdout:")
    print(proc.stdout)

    # 3) 写后即读（RAW 原子锁）
    time.sleep(2)

    file_paths_after = mcp_download_lark_sheet(args.sheet_url)
    xlsx_after = pick_xlsx(file_paths_after)
    if not os.path.isabs(xlsx_after):
        xlsx_after = str((workspace_root / xlsx_after).resolve())

    post_snap = snapshot(skill_root, xlsx_after, stage="post")

    read_back = read_row_values(xlsx_after, args.sheet_name, args.row_index, col_count=3)

    expected = [row_id, args.date, args.content]
    expected_str = [str(x) for x in expected]

    print("[Snapshot] post:")
    print(str(post_snap))

    print("[ReadAfterWrite] read_back (raw array):")
    print(json.dumps([read_back], ensure_ascii=False))

    if read_back != expected_str:
        dlq_file = write_dlq(
            skill_root,
            {
                "type": "Daily_Logs_ReadAfterWriteMismatch",
                "timestamp": dt.datetime.now().isoformat(),
                "sheet_url": args.sheet_url,
                "sheet_name": args.sheet_name,
                "row_index": args.row_index,
                "expected": expected_str,
                "read_back": read_back,
                "snapshots": {
                    "pre": str(pre_snap),
                    "post": str(post_snap),
                },
                "note": "⚠️[数据断链_待自愈] 写后即读不一致，已熔断并落 DLQ。",
            },
        )
        raise RuntimeError(
            "写后即读 RAW 校验失败（不一致），已熔断并落 DLQ："
            f"\n- expected：{expected_str}"
            f"\n- read_back：{read_back}"
            f"\n- DLQ：{dlq_file}"
        )

    print("[OK] 写入并核对一致。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print("[FATAL]", str(e))
        traceback.print_exc()
        raise
