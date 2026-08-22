#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EU AM 效率分析 · 分层读写架构构建器（3 底表 + 3 阅读视图）

底表层（机器层，全字段 ~100 列，每日覆盖）：
  1. 全量底表            : 源全量，不筛选
  2. 全量_AM招商推进     : AM优先级 == "AM招商推进" 且 历史入驻 != 1（覆盖已有 sheet 8953af）
  3. BD底表              : 负责BD 非空 且 历史入驻 != 1

阅读层（人类层，38 列固定表头 + INDEX+MATCH 动态引用）：
  4. 全量_阅读视图        -> 全量底表
  5. AM招商推进_阅读视图  -> 全量_AM招商推进
  6. BD_阅读视图          -> BD底表

约束：所有飞书读写只走 lark-cli；长整型 ID 列强制文本；写入前先 +workbook-info；
      不新建备份 sheet、不删除任何已有 sheet（历史入驻 / AM分析 绝对不动）。

用法：
  python3 build_layered_sheets.py --dry-run
  python3 build_layered_sheets.py --layer base     # 只跑底表层
  python3 build_layered_sheets.py --layer view     # 只跑阅读层
  python3 build_layered_sheets.py                  # 全跑 + 零信任质检
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

LARK_CLI = os.environ.get("LARK_CLI", "/usr/local/bin/lark-cli")
BASE_TOKEN = "MPN9bUhBTaUsgcsrN92m2Oq0yde"
TABLE_ID = "tbl5IlstItZOpInx"
URL = "https://bytedance.my.larkoffice.com/sheets/RvpVsoUODhqCXJt4rFgm1M6ky2e"

# ---- 不可触碰的 sheet（白名单外一律不写）
PROTECTED = {"历史入驻", "AM分析", "分析基盘_阅读视图"}

SHEET_FULL = "【1.全量底表】"
SHEET_AM = "【2.AM底表】"
SHEET_BD = "【3.BD底表】"
VIEW_FULL = "【1.全量看板】"
VIEW_AM = "【2.AM看板】"
VIEW_BD = "【3.BD看板】"

# (底表名, 阅读视图名, 筛选口径 key)
LAYERS = [
    (SHEET_FULL, VIEW_FULL, "all"),
    (SHEET_AM, VIEW_AM, "am"),
    (SHEET_BD, VIEW_BD, "bd"),
]
FILTER_DESC = {
    "all": "无筛选（源全量）",
    "am": 'AM优先级 == "AM招商推进" 且 历史入驻 != 1',
    "bd": "负责BD 非空（非 None / 非空串 / strip 后非空）且 历史入驻 != 1",
}

QA_NULL_COLS = ["负责AM", "AM优先级"]
QA_NULL_THRESHOLD = 0.05
QA_RAW_SAMPLE = 5
WRITE_CHUNK_ROWS = 300
CST = timezone(timedelta(hours=8))
TEXT_FORCE_KEYS = ("seller_id", "shop_id", "shopid", "leads_id", "临时id", "id")

HERE = os.path.dirname(os.path.abspath(__file__))


def now_cst() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S CST")


def log(msg: str) -> None:
    print(f"[{now_cst()}] {msg}", flush=True)


class SyncError(RuntimeError):
    pass


def run_cli(args: list[str], *, stdin_data: str | None = None, timeout: int = 900) -> dict:
    proc = subprocess.run([LARK_CLI] + args, input=stdin_data,
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise SyncError(f"lark-cli rc={proc.returncode}: {' '.join(args[:4])}\n{proc.stderr[:2000]}")
    out = proc.stdout.strip()
    if not out:
        raise SyncError(f"空 stdout: {' '.join(args[:4])}")
    payload = json.loads(out)
    if "ok" in payload and not payload.get("ok"):
        raise SyncError(f"ok=false: {json.dumps(payload.get('error'), ensure_ascii=False)}")
    return payload


# ------------------------------------------------------------------ 归一化
def norm_scalar(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        for key in ("name", "text", "value", "en_name", "full_address", "link", "file_token"):
            if v.get(key):
                return norm_scalar(v[key])
        return ""
    if isinstance(v, list):
        return ",".join(p for p in (norm_scalar(i) for i in v) if p)
    return str(v)


# ------------------------------------------------------------------ 读源
def fetch_fields() -> list[str]:
    p = run_cli(["base", "+field-list", "--base-token", BASE_TOKEN,
                 "--table-id", TABLE_ID, "--format", "json"])
    return [f["name"] for f in p["data"]["fields"]]


def canonical_header(records: list[dict], api_fields: list[str]) -> list[str]:
    keys: set[str] = set(api_fields)
    for r in records:
        keys |= set(r.keys())
    keys.discard("record_id")
    return ["record_id"] + sorted(keys)


def fetch_records(cache: str | None = None) -> list[dict]:
    if cache and os.path.exists(cache):
        with open(cache, encoding="utf-8") as fh:
            recs = [json.loads(l) for l in fh if l.strip()]
        log(f"复用本地缓存 {cache}: {len(recs)} 行")
        return recs
    records: list[dict] = []
    offset, page = 0, 0
    tmpdir = os.path.join(HERE, "layer_tmp")
    os.makedirs(tmpdir, exist_ok=True)
    while True:
        page += 1
        out_path = os.path.relpath(os.path.join(tmpdir, f"rec_{page}.ndjson"), os.getcwd())
        if not out_path.startswith("."):
            out_path = "./" + out_path
        p = run_cli(["base", "+record-list", "--base-token", BASE_TOKEN, "--table-id", TABLE_ID,
                     "--limit", "2000", "--offset", str(offset),
                     "--output", out_path, "--overwrite",
                     "--minimal-stdout", "--format", "ndjson"])
        d = p.get("data", p)
        cnt = int(d.get("records_count", 0))
        art = d.get("record_file") or out_path
        if not os.path.exists(art):
            art = out_path
        with open(art, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    records.append(json.loads(line))
        log(f"  分页 {page}: +{cnt} (累计 {len(records)}) has_more={d.get('has_more')}")
        if not d.get("has_more") or cnt == 0:
            break
        offset += cnt
        time.sleep(0.3)
    if cache:
        with open(cache, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return records


def is_hist_settled(r: dict) -> bool:
    """历史入驻 == 1（兼容数字 1 / 浮点 1.0 / 字符串 "1" / 布尔 True，norm_scalar 已统一归一）"""
    return norm_scalar(r.get("历史入驻")) == "1"


def filter_records(records: list[dict], key: str) -> list[dict]:
    if key == "all":
        # 全量快照语义：不加任何筛选（含历史入驻商家）
        return list(records)
    if key == "am":
        return [r for r in records
                if norm_scalar(r.get("AM优先级")) == "AM招商推进" and not is_hist_settled(r)]
    if key == "bd":
        return [r for r in records
                if norm_scalar(r.get("负责BD")) != "" and not is_hist_settled(r)]
    raise ValueError(key)


# ------------------------------------------------------------------ 矩阵
def is_text_col(col: str) -> bool:
    low = col.lower()
    return any(k in low for k in TEXT_FORCE_KEYS)


def _num_ok(s: str) -> bool:
    try:
        f = float(s)
    except ValueError:
        return False
    return len(s.lstrip("-").replace(".", "")) <= 15 and abs(f) < 1e15


def build(header: list[str], rows: list[dict]) -> tuple[list[list], dict]:
    txt = [[norm_scalar(r[c]) if c in r else "" for c in header] for r in rows]
    dtypes, numeric_idx = {}, set()
    for j, col in enumerate(header):
        if is_text_col(col):
            dtypes[col] = "object"
            continue
        vals = [line[j] for line in txt if line[j] != ""]
        if vals and all(_num_ok(v) for v in vals):
            dtypes[col] = "float64"
            numeric_idx.add(j)
        else:
            dtypes[col] = "object"
    matrix = [[(float(v) if v != "" else None) if j in numeric_idx else v
               for j, v in enumerate(line)] for line in txt]
    return matrix, dtypes


def col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ------------------------------------------------------------------ 写入
def workbook_sheets() -> dict:
    p = run_cli(["sheets", "+workbook-info", "--url", URL, "--format", "json"])
    return {s["sheet_name"]: s for s in p["data"]["sheets"]}


def guard(sheet: str) -> None:
    if sheet in PROTECTED:
        raise SyncError(f"拒绝写入受保护 sheet: {sheet}")


def clear_sheet(sheet: str, ncols: int, keep_rows: int = 12000) -> None:
    guard(sheet)
    last = col_letter(ncols + 5)
    run_cli(["sheets", "+cells-clear", "--url", URL, "--sheet-name", sheet,
             "--range", f"{sheet}!A1:{last}{keep_rows}", "--scope", "all",
             "--yes", "--format", "json"])
    log(f"  [{sheet}] 已清空 A1:{last}{keep_rows}")


def write_header(sheet: str, header: list[str], dtypes: dict) -> None:
    guard(sheet)
    item = {"name": sheet, "start_cell": "A1", "mode": "overwrite", "header": True,
            "columns": header, "data": [], "dtypes": dtypes}
    run_cli(["sheets", "+table-put", "--url", URL, "--sheets", "-", "--format", "json"],
            stdin_data=json.dumps({"sheets": [item]}, ensure_ascii=False))


def put_rows(sheet: str, header: list[str], dtypes: dict, matrix: list[list]) -> None:
    guard(sheet)
    for i in range(0, len(matrix), WRITE_CHUNK_ROWS):
        chunk = matrix[i:i + WRITE_CHUNK_ROWS]
        item = {"name": sheet, "start_cell": f"A{i + 2}", "mode": "overwrite",
                "header": False, "columns": header, "data": chunk, "dtypes": dtypes}
        run_cli(["sheets", "+table-put", "--url", URL, "--sheets", "-", "--format", "json"],
                stdin_data=json.dumps({"sheets": [item]}, ensure_ascii=False))
        log(f"  [{sheet}] rows {i + 1}-{i + len(chunk)} @A{i + 2} ✓")
        time.sleep(0.35)


# ------------------------------------------------------------------ 阅读视图
COLS = ("新leads_id, 品牌名, 公司名, EU行业, 负责AM, 负责BD, 行业小组长, 跟进状态, AM优先级, "
        "线索来源, 一级类目, 二级类目, 一级商家标签, 是否T3+, 历史入驻, 新增入驻, 已触达, 有意愿, "
        "入驻中, 已入驻, 可售数, 活跃数, EU_入驻时间, UK_入驻时间, EU_完成上架可售, UK_完成上架可售, "
        "EU_T等级, UK_T等级, EU_30d GMV, UK_30d GMV, EU_global seller id, UK_global seller id, "
        "详细原因, 原因汇总, EU_匹配global_seller_id, UK_匹配global_seller_id, 跟进日期, 是否分析基盘"
        ).split(", ")
DERIVED = {"详细原因", "原因汇总", "是否分析基盘"}
IDX = {c: i + 1 for i, c in enumerate(COLS)}
_T = col_letter(IDX["已入驻"])
_W, _X = col_letter(IDX["EU_入驻时间"]), col_letter(IDX["UK_入驻时间"])
_AE, _AF = col_letter(IDX["EU_global seller id"]), col_letter(IDX["UK_global seller id"])
_AI, _AJ = col_letter(IDX["EU_匹配global_seller_id"]), col_letter(IDX["UK_匹配global_seller_id"])
_AG = col_letter(IDX["详细原因"])


def lookup(sb: str, letter: str, nrow: int) -> str:
    m = f"MATCH({letter}$1,'{sb}'!$A$1:$DB$1,0)"
    core = f"INDEX('{sb}'!$A$2:$DB${nrow + 1},ROW()-1,{m})"
    return f'=IFERROR(IF({core}="","",{core}),"")'


def xlook(sb: str, name: str, nrow: int) -> str:
    m = f"MATCH(\"{name}\",'{sb}'!$A$1:$DB$1,0)"
    return f"IFERROR(INDEX('{sb}'!$A$2:$DB${nrow + 1},ROW()-1,{m}),\"\")"


def derived_formula(col: str, sb: str, nrow: int) -> str:
    if col == "是否分析基盘":
        return "=1"
    if col == "详细原因":
        eu, uk = f"({_AE}2&{_AI}2)", f"({_AF}2&{_AJ}2)"
        chk = xlook(sb, "校验填写seller_id", nrow)
        return (f'=IF({_T}2<>1,"",'
                f'IF(AND({eu}="",{uk}=""),"未填写seller_id",'
                f'IF(AND({_W}2<>"",{eu}="",{uk}<>""),"该seller_id市场归属EU，错填成UK",'
                f'IF(AND({_X}2<>"",{uk}="",{eu}<>""),"该seller_id市场归属UK，错填成EU",'
                f'IF(ISNUMBER(SEARCH("未填",{chk})),"未填写seller_id","")))))')
    if col == "原因汇总":
        d = f"{_AG}2"
        return (f'=IF({d}="","",'
                f'IF(AND(ISNUMBER(SEARCH("seller_id",{d})),'
                f'OR(ISNUMBER(SEARCH("未填",{d})),ISNUMBER(SEARCH("错填",{d})),'
                f'ISNUMBER(SEARCH("填错",{d})))),"seller_id错填/未填/填错列",{d}))')
    raise ValueError(col)


def build_view(view: str, sb: str, nrow: int) -> dict:
    guard(view)
    run_cli(["sheets", "+table-put", "--url", URL, "--sheets", "-", "--format", "json"],
            stdin_data=json.dumps({"sheets": [{"name": view, "columns": COLS, "data": [],
                                               "dtypes": {c: "object" for c in COLS},
                                               "header": True}]}, ensure_ascii=False))
    log(f"  [{view}] 38 列表头就绪 -> 引用 {sb} (数据行 {nrow})")
    for i, col in enumerate(COLS, start=1):
        letter = col_letter(i)
        f = derived_formula(col, sb, nrow) if col in DERIVED else lookup(sb, letter, nrow)
        cells = [[{"formula": f}] for _ in range(nrow)]
        run_cli(["sheets", "+cells-set", "--url", URL, "--sheet-name", view,
                 "--range", f"{view}!{letter}2:{letter}{nrow + 1}", "--cells", "-",
                 "--format", "json"],
                stdin_data=json.dumps(cells, ensure_ascii=False))
        time.sleep(0.15)
    log(f"  [{view}] 38 列公式写入完成")
    time.sleep(3)
    v = run_cli(["sheets", "+formula-verify", "--url", URL, "--sheet-name", view,
                 "--format", "json"])
    d = v.get("data", v)
    return {"view": view, "base": sb, "rows": nrow,
            "status": d.get("status"), "total_errors": d.get("total_errors")}


# ------------------------------------------------------------------ 质检
def read_back(sheet: str, rng: str) -> list[list[str]]:
    p = run_cli(["sheets", "+csv-get", "--url", URL, "--sheet-name", sheet,
                 "--range", f"{sheet}!{rng}", "--format", "json"])
    d = p["data"]
    rows = d.get("values")
    if rows is None:
        import csv as _csv, io
        text = d.get("csv") or d.get("annotated_csv") or ""
        lines = []
        for ln in text.splitlines():
            if ln.startswith("[row=") and "] " in ln:
                ln = ln.split("] ", 1)[1]
            lines.append(ln)
        rows = list(_csv.reader(io.StringIO("\n".join(lines))))
    return [[norm_scalar(c) for c in r] for r in rows]


def qa_rowcount(sheet: str, expected: int) -> dict:
    rows = read_back(sheet, f"A1:A{expected + 50}")
    actual = sum(1 for r in rows[1:] if r and r[0] != "")
    return {"name": f"行数断言[{sheet}]", "pass": actual == expected,
            "detail": f"线上非空数据行 {actual} vs 源过滤后 {expected}"}


def qa_header(sheet: str, header: list[str]) -> dict:
    got = read_back(sheet, f"A1:{col_letter(len(header))}1")
    got = got[0] if got else []
    norm = lambda s: s.replace("\n", " ").strip()
    diffs = [f"col{col_letter(i + 1)}: 期望={header[i]!r} 实际={(got[i] if i < len(got) else '')!r}"
             for i in range(len(header))
             if norm(got[i] if i < len(got) else "") != norm(header[i])]
    return {"name": f"表头列序一致[{sheet}]", "pass": not diffs,
            "detail": f"{len(header)} 列逐列比对；差异 {len(diffs)} 处"
                      + ("" if not diffs else " | " + "; ".join(diffs[:5]))}


def qa_null(sheet: str, header: list[str], matrix: list[list], require_bd: bool,
            null_cols: list[str] | None = None) -> dict:
    """G7: 空值率断言仅适用于 AM 相关底表；全量/BD 底表的 负责AM 高空值率是源数据事实，不构成 FAIL。"""
    idx = {c: i for i, c in enumerate(header)}
    n = len(matrix) or 1
    ok, details = True, []
    if null_cols is None:
        null_cols = QA_NULL_COLS
    if not null_cols:
        details.append("负责AM/AM优先级 空值率断言按 G7 豁免（源数据事实，非 FAIL）")
    for col in null_cols:
        if col not in idx:
            details.append(f"{col} 字段不存在 -> SKIP")
            continue
        empty = sum(1 for r in matrix if norm_scalar(r[idx[col]]) == "")
        rate = empty / n
        p = rate < QA_NULL_THRESHOLD
        ok = ok and p
        details.append(f"{col} 空值率 {rate:.2%} ({empty}/{n}) -> {'PASS' if p else 'FAIL'}")
    if require_bd:
        j = idx.get("负责BD")
        nonempty = sum(1 for r in matrix if norm_scalar(r[j]) != "") if j is not None else 0
        p = nonempty == len(matrix) and len(matrix) > 0
        ok = ok and p
        details.append(f"负责BD 非空率 {nonempty}/{len(matrix)} -> {'PASS' if p else 'FAIL'}")
    return {"name": f"关键字段空值率[{sheet}]", "pass": ok, "detail": "; ".join(details)}


def qa_raw(sheet: str, header: list[str], matrix: list[list]) -> dict:
    if not matrix:
        return {"name": f"RAW 回捞[{sheet}]", "pass": False, "detail": "无数据"}
    picks = sorted(random.sample(range(len(matrix)), min(QA_RAW_SAMPLE, len(matrix))))
    last = col_letter(len(header))
    diffs, eye, txt_fail = [], [], []
    for i in picks:
        rn = i + 2
        got = read_back(sheet, f"A{rn}:{last}{rn}")
        g = got[0] if got else []
        for j, col in enumerate(header):
            e = norm_scalar(matrix[i][j])
            a = norm_scalar(g[j]) if j < len(g) else ""
            if e == a:
                continue
            try:
                if e and a and abs(float(e) - float(a)) < 1e-6:
                    continue
            except ValueError:
                pass
            diffs.append(f"row{rn}.{col}: 写={e!r} 读={a!r}")
        item = {"sheet_row": rn}
        for c in ("负责AM", "品牌名", "EU行业"):
            j = header.index(c) if c in header else None
            val = norm_scalar(g[j]) if (j is not None and j < len(g)) else ""
            item[c] = val
            if val != "" and val in ("0", "1"):
                txt_fail.append(f"row{rn}.{c}={val!r} 疑似数字化")
        eye.append(item)
        print(f"    RAW row{rn} | 负责AM={item['负责AM']!r} | 品牌名={item['品牌名']!r} | EU行业={item['EU行业']!r}")
    return {"name": f"RAW 回捞 5 行[{sheet}]", "pass": (not diffs) and (not txt_fail),
            "detail": f"抽样 {len(picks)} 行 x {len(header)} 字段；逐字段差异 {len(diffs)} 处；"
                      f"文字性检查异常 {len(txt_fail)} 处"
                      + ("" if not diffs else " | " + "; ".join(diffs[:8]))
                      + ("" if not txt_fail else " | " + "; ".join(txt_fail[:5])),
            "eyeball": eye}


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--layer", choices=["base", "view", "all"], default="all")
    ap.add_argument("--cache", default=os.path.join(HERE, "layer_tmp", "records.ndjson"))
    args = ap.parse_args()

    log("=== 分层架构构建开始 ===")
    before = workbook_sheets()
    log("现状 workbook: " + ", ".join(f"{k}({v['sheet_id']},{v['row_count']}r/{v['column_count']}c)"
                                     for k, v in before.items()))

    api_fields = fetch_fields()
    records = fetch_records(args.cache)
    header = canonical_header(records, api_fields)
    log(f"源总行数={len(records)} 确定性列序={len(header)} 列")

    sets = {}
    for sb, view, key in LAYERS:
        rows = filter_records(records, key)
        m, dt = build(header, rows)
        sets[sb] = {"view": view, "key": key, "rows": rows, "matrix": m, "dtypes": dt}
        log(f"  {sb}: {len(rows)} 行  [{FILTER_DESC[key]}]")

    if args.dry_run:
        print(json.dumps({"cols": len(header),
                          "counts": {k: len(v["rows"]) for k, v in sets.items()},
                          "filters": {k: FILTER_DESC[v["key"]] for k, v in sets.items()}},
                         ensure_ascii=False, indent=2))
        return 0

    qa, views = [], []
    if args.layer in ("base", "all"):
        for sb, s in sets.items():
            log(f"--- 写入底表 {sb} ---")
            if sb in workbook_sheets():
                clear_sheet(sb, len(header))
            else:
                log(f"  [{sb}] 不存在 -> 由 +table-put 自动新建")
            write_header(sb, header, s["dtypes"])
            time.sleep(0.5)
            put_rows(sb, header, s["dtypes"], s["matrix"])
        time.sleep(3)
        for sb, s in sets.items():
            log(f"--- 质检底表 {sb} ---")
            qa.append(qa_rowcount(sb, len(s["rows"])))
            qa.append(qa_header(sb, header))
            qa.append(qa_null(sb, header, s["matrix"], require_bd=(sb == SHEET_BD),
                              null_cols=(QA_NULL_COLS if sb == SHEET_AM else [])))
            qa.append(qa_raw(sb, header, s["matrix"]))

    if args.layer in ("view", "all"):
        for sb, s in sets.items():
            log(f"--- 构建阅读视图 {s['view']} ---")
            views.append(build_view(s["view"], sb, len(s["rows"])))

    for q in qa:
        log(f"[QA] {q['name']}: {'PASS' if q['pass'] else 'FAIL'} — {q['detail']}")
    for v in views:
        log(f"[QA] formula-verify[{v['view']}]: status={v['status']} total_errors={v['total_errors']}")

    after = workbook_sheets()
    result = {"ts": now_cst(), "cols": len(header), "source_rows": len(records),
              "bases": {k: {"rows": len(v["rows"]), "filter": FILTER_DESC[v["key"]],
                            "sheet_id": after.get(k, {}).get("sheet_id")} for k, v in sets.items()},
              "views": views, "qa": qa,
              "sheets": {k: v["sheet_id"] for k, v in after.items()},
              "overall": all(q["pass"] for q in qa) and all(not v["total_errors"] for v in views)}
    with open(os.path.join(HERE, "layered_result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["overall"] else 3


if __name__ == "__main__":
    sys.exit(main())
