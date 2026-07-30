import sys
import json
import subprocess
from pathlib import Path


def _workspace_root() -> Path:
    p = Path(__file__).resolve()
    for parent in [p, *p.parents]:
        if (parent / "inner_skills").exists():
            return parent
    return Path.cwd().resolve()


def normalize_values(values):
    """确保写入参数为飞书要求的 2D array。

    兼容历史调用方误传单行 1D array 的场景：['a','b','c'] -> [['a','b','c']]。
    """
    if not isinstance(values, list):
        raise ValueError(f"values 必须是 list，当前类型: {type(values).__name__}")
    if not values:
        raise ValueError("values 不能为空")
    if all(not isinstance(item, list) for item in values):
        return [values]
    if all(isinstance(item, list) for item in values):
        return values
    raise ValueError(f"values 必须为 1D 或 2D array，不能混用标量与数组: {values}")


def run_lark_sheets(args):
    cli_path = str(_workspace_root() / "inner_skills" / "lark-sheets" / "bin" / "lark-sheets-cli")
    cmd = [cli_path] + args
    print(f"Running: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"CLI Error: {res.stderr}")
        return None
    try:
        return json.loads(res.stdout)
    except Exception:
        print(f"Failed to parse output: {res.stdout}")
        return None


def _col_letter(n: int) -> str:
    """1 -> A, 2 -> B, ... 26 -> Z, 27 -> AA ..."""
    if n <= 0:
        raise ValueError(f"invalid col index: {n}")
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python safe_insert_sheet_row.py <document_url> <sheet_name> <row_index> <data_json>")
        sys.exit(1)

    doc_url = sys.argv[1]
    sheet_name = sys.argv[2]
    try:
        row_index = int(sys.argv[3])
    except Exception:
        print(f"Invalid row_index: {sys.argv[3]}")
        sys.exit(1)

    try:
        values = normalize_values(json.loads(sys.argv[4]))
    except Exception as exc:
        print(f"Invalid data_json: {exc}")
        sys.exit(1)

    data_json = json.dumps(values, ensure_ascii=False)

    # 1) Get sheet info to find sheet_id
    info = run_lark_sheets(["sheets", "+info", "--url", doc_url])
    if not info or not info.get("ok"):
        print(f"Failed to get spreadsheet info: {info}")
        sys.exit(1)

    sheet_id = None
    for s in info["data"]["sheets"]["sheets"]:
        if s["title"] == sheet_name:
            sheet_id = s["sheet_id"]
            break

    if not sheet_id:
        print(f"Sheet '{sheet_name}' not found.")
        sys.exit(1)

    # 2) Insert/Append
    row_count = len(values)
    col_count = len(values[0]) if values and values[0] else 0
    if col_count <= 0:
        print(f"Invalid values (empty columns): {values}")
        sys.exit(1)

    if row_index and row_index > 0:
        # row_index: 1-based row number. lark-sheets insert-dimension uses 0-indexed positions.
        # To insert at row_index, we insert ROWS in [row_index-1, row_index-1+row_count)
        start = row_index - 1
        end = start + row_count
        print(
            f"Inserting {row_count} row(s) at row_index={row_index} (0-indexed start={start}, end={end})..."
        )
        ins = run_lark_sheets(
            [
                "sheets",
                "+insert-dimension",
                "--url",
                doc_url,
                "--sheet-id",
                sheet_id,
                "--dimension",
                "ROWS",
                "--start-index",
                str(start),
                "--end-index",
                str(end),
                "--inherit-style",
                "BEFORE",
            ]
        )
        if not ins or not ins.get("ok"):
            print(f"Insert failed: {ins}")
            sys.exit(1)

        end_col = _col_letter(col_count)
        end_row = row_index + row_count - 1
        write_range = f"{sheet_id}!A{row_index}:{end_col}{end_row}"
        print(f"Writing values to range {write_range}...")
        res = run_lark_sheets(
            [
                "sheets",
                "+write",
                "--url",
                doc_url,
                "--sheet-id",
                sheet_id,
                "--range",
                write_range,
                "--values",
                data_json,
            ]
        )
        if not res or not res.get("ok"):
            print(f"Write failed: {res}")
            sys.exit(1)

        print("Success: Row inserted safely.")
        sys.exit(0)

    # Default fallback: append to the end
    print(f"Appending to sheet '{sheet_name}' (id: {sheet_id})...")
    res = run_lark_sheets(["sheets", "+append", "--url", doc_url, "--sheet-id", sheet_id, "--values", data_json])

    if not res or not res.get("ok"):
        print(f"Append failed: {res}")
        sys.exit(1)

    print("Success: Row appended safely.")
