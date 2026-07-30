import os
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


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python safe_insert_sheet_row.py <document_url> <sheet_name> <row_index> <data_json>")
        sys.exit(1)

    doc_url = sys.argv[1]
    sheet_name = sys.argv[2]
    # row_idx is ignored because we use +append to fulfill the "Append mode" requirement
    try:
        values = normalize_values(json.loads(sys.argv[4]))
    except Exception as exc:
        print(f"Invalid data_json: {exc}")
        sys.exit(1)
    data_json = json.dumps(values, ensure_ascii=False)
    
    # 1. Get sheet info to find sheet_id
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
        
    # 2. Use +append to add to the end (fulfills "Append mode" and "No insert" requirement)
    print(f"Appending to sheet '{sheet_name}' (id: {sheet_id})...")
    res = run_lark_sheets(["sheets", "+append", "--url", doc_url, "--sheet-id", sheet_id, "--values", data_json])
    
    if not res or not res.get("ok"):
        print(f"Append failed: {res}")
        sys.exit(1)
        
    print("Success: Row appended safely.")
