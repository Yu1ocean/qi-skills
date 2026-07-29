import csv
import json
import re
import subprocess
import time
from pathlib import Path

BASE_TOKEN = "MPN9bUhBTaUsgcsrN92m2Oq0yde"
TABLE_ID = "tbl5IlstItZOpInx"
VIEW_ID = "vewm2HQxRS"

SHEET_URL = "https://bytedance.my.larkoffice.com/sheets/N8Eusg9nShiup0tWZEKmmEiJy5V"
AI_SHEET_NAME = "AI_Data"
OFFICIAL_SHEET_NAME = "正式表"

OUT_AI_CSV = Path("ai_data_view_order.csv")
OUT_OFFICIAL_CSV = Path("official_formula_2000.csv")


def run_lark_json(cmd: list[str]) -> dict:
    p = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    s = p.stdout
    i = s.find("{")
    if i == -1:
        raise RuntimeError(f"No JSON found. stderr=\n{p.stderr}\nstdout=\n{p.stdout}")
    return json.loads(s[i:])


def col_letter(n: int) -> str:
    # 1-based
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def main():
    # 1) read first page to get view-ordered fields
    first = run_lark_json([
        "lark-cli", "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--view-id", VIEW_ID,
        "--offset", "0",
        "--limit", "1",
        "--format", "json",
    ])
    # record-list returns `fields` as a list of field names (strings) in the view's visible order
    header = first["data"]["fields"]

    # 2) page through all records (data is already aligned with `fields` order)
    all_rows = []
    offset = 0
    limit = 200
    while True:
        resp = run_lark_json([
            "lark-cli", "base", "+record-list",
            "--base-token", BASE_TOKEN,
            "--table-id", TABLE_ID,
            "--view-id", VIEW_ID,
            "--offset", str(offset),
            "--limit", str(limit),
            "--format", "json",
        ])
        rows = resp["data"]["data"]
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < limit:
            break
        offset += limit

    # fetch field meta (type + select.multiple)
    fields_meta_resp = run_lark_json([
        "lark-cli", "base", "+field-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--format", "json",
    ])
    fields_meta = fields_meta_resp["data"]["fields"]
    meta_by_name = {f.get("name"): f for f in fields_meta}

    def normalize_value(v, field_meta):
        """Convert bitable cell values to plain text per the user's cleaning rules."""
        if v is None:
            return ""

        ftype = (field_meta or {}).get("type")

        # text field: strip markdown links like [@Name](https://...) -> Name
        if ftype == "text" and isinstance(v, str):
            # find all markdown link display texts
            matches = re.findall(r"\[([^\]]+)\]\(https?://[^)]+\)", v)
            if matches:
                cleaned = []
                for m in matches:
                    name = m.strip()
                    if name.startswith("@"):
                        name = name[1:].strip()
                    if name:
                        cleaned.append(name)
                if cleaned:
                    return ", ".join(cleaned)
            return v

        # user field: list of {id,name}
        if ftype in {"user", "created_by", "updated_by"}:
            if isinstance(v, list):
                names = []
                for it in v:
                    if isinstance(it, dict) and it.get("name"):
                        names.append(it["name"])
                    elif isinstance(it, str):
                        names.append(it)
                return ", ".join(names)
            if isinstance(v, dict) and v.get("name"):
                return v["name"]
            return str(v)

        # options / lookup often come back as list of strings
        if ftype in {"select", "multi_select", "lookup"}:
            if isinstance(v, list):
                # list of strings or dicts
                out = []
                for it in v:
                    if isinstance(it, dict) and it.get("name"):
                        out.append(it["name"])
                    elif isinstance(it, str):
                        out.append(it)
                    else:
                        out.append(str(it))
                return ", ".join(out)
            return str(v)

        # group chat / attachment may be list of dicts with name
        if ftype in {"group_chat", "attachment"}:
            if isinstance(v, list):
                out = []
                for it in v:
                    if isinstance(it, dict) and it.get("name"):
                        out.append(it["name"])
                    elif isinstance(it, str):
                        out.append(it)
                return ", ".join(out)
            return str(v)

        # generic fallback: flatten list/dict to human-readable text, avoid JSON strings
        if isinstance(v, list):
            return ", ".join([str(x) for x in v])
        if isinstance(v, dict):
            if v.get("name"):
                return str(v["name"])
            return str(v)

        return v

    # align metas to header order
    header_metas = [meta_by_name.get(name) for name in header]

    def norm_row(row):
        return [normalize_value(v, header_metas[i]) for i, v in enumerate(row)]

    # 3) chunked overwrite AI_Data via csv-put (avoid single-call timeout)
    # NOTE: sheets +csv-put RPC has a tight 5s timeout; use very small chunks + retry to avoid server timeouts.
    chunk_size = 10  # rows per call (excluding header)

    # write header + first chunk
    def write_csv(path: Path, rows: list[list]):
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
            for r in rows:
                w.writerow(r)

    # optional: keep one full csv snapshot for audit/debug
    OUT_AI_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_csv(OUT_AI_CSV, [header] + [norm_row(r) for r in all_rows])

    def csv_put(sheet_name: str, start_cell: str, csv_path: Path, retries: int = 6):
        for attempt in range(retries):
            try:
                subprocess.run([
                    "lark-cli", "sheets", "+csv-put",
                    "--url", SHEET_URL,
                    "--sheet-name", sheet_name,
                    "--start-cell", start_cell,
                    "--csv", f"@{csv_path}",
                    "--allow-overwrite",
                    "--format", "json",
                ], check=True)
                return
            except subprocess.CalledProcessError:
                if attempt == retries - 1:
                    raise
                time.sleep(2 * (attempt + 1))

    # header block
    header_block_rows = [header] + [norm_row(r) for r in all_rows[:chunk_size]]
    tmp = Path("_tmp_ai_000.csv")
    write_csv(tmp, header_block_rows)
    csv_put(AI_SHEET_NAME, "A1", tmp)

    # subsequent blocks (data only)
    start_index = chunk_size
    block_idx = 1
    while start_index < len(all_rows):
        block = [norm_row(r) for r in all_rows[start_index:start_index + chunk_size]]
        tmp = Path(f"_tmp_ai_{block_idx:03d}.csv")
        write_csv(tmp, block)
        start_row = 1 + start_index + 1  # header(1) + already-written data + 1-based
        csv_put(AI_SHEET_NAME, f"A{start_row}", tmp)
        start_index += chunk_size
        block_idx += 1

    # 4) chunked overwrite 正式表 formulas (2000 rows)
    max_rows = 2000

    # optional full csv snapshot
    formula_rows_all = [header]
    for r in range(2, max_rows + 2):
        formula_rows_all.append([f"='AI_Data'!{col_letter(c)}{r}" for c in range(1, len(header) + 1)])
    write_csv(OUT_OFFICIAL_CSV, formula_rows_all)

    # header block (header + first chunk of formula rows)
    header_block_rows = formula_rows_all[: 1 + chunk_size]
    tmp = Path("_tmp_official_000.csv")
    write_csv(tmp, header_block_rows)
    csv_put(OFFICIAL_SHEET_NAME, "A1", tmp)

    # subsequent blocks
    start_row = 1 + chunk_size + 1
    idx = 1
    pos = 1 + chunk_size
    while pos < len(formula_rows_all):
        block = formula_rows_all[pos:pos + chunk_size]
        tmp = Path(f"_tmp_official_{idx:03d}.csv")
        write_csv(tmp, block)
        csv_put(OFFICIAL_SHEET_NAME, f"A{start_row}", tmp)
        pos += chunk_size
        start_row += chunk_size
        idx += 1

    # 6) RAW readback: header + row2 first 10 cells
    readback_header = run_lark_json([
        "lark-cli", "sheets", "+cells-get",
        "--url", SHEET_URL,
        "--sheet-name", AI_SHEET_NAME,
        "--range", "A1:CE1",
        "--include", "value",
        "--format", "json",
    ])

    readback_row2 = run_lark_json([
        "lark-cli", "sheets", "+cells-get",
        "--url", SHEET_URL,
        "--sheet-name", AI_SHEET_NAME,
        "--range", "A2:J2",
        "--include", "value",
        "--format", "json",
    ])

    result = {
        "field_count": len(header),
        "record_count": len(all_rows),
        "top10_fields": header[:10],
        "row2_first10_raw": readback_row2,
        "ai_csv": str(OUT_AI_CSV),
        "official_csv": str(OUT_OFFICIAL_CSV),
        "cells_get_header_raw": readback_header,
    }
    Path("fix_ai_data_view_order_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"top10_fields": header[:10], "field_count": len(header), "record_count": len(all_rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
