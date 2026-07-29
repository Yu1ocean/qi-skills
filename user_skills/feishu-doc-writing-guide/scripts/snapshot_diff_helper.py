import os
import re
import sys
import json
import requests
import csv
from urllib.parse import urlparse

"""
表格快照与差异对比助手 - 遵循 v5.0 安全准则
1. 质检原貌输出: diff 结果必须以原始数组结构展示，禁止过度美化。
2. 零信任质检: 通过 Snapshot 实现写前备份与写后 diff 验证。
"""


def get_open_api_base(doc_url: str) -> str:
    """Choose correct OpenAPI host for Feishu (CN) vs Lark (Intl)."""
    host = urlparse(doc_url).netloc
    if host.endswith(".larkoffice.com") and host != "bytedance.larkoffice.com":
        return "https://open.larksuite.com"
    return "https://open.feishu.cn"


def get_spreadsheet_token(url):
    match = re.search(r'/sheets/([a-zA-Z0-9]+)', url)
    if match: return match.group(1)
    return None


def get_sheet_id(open_api_base, spreadsheet_token, sheet_name, token):
    """Resolve sheet_id by sheet title to support non-ascii names."""
    url = f"{open_api_base}/open-apis/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    if "Bearer " in token:
        headers["Cookie"] = f"session={token.split(' ')[1]}"

    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return None

    data = resp.json()
    if data.get("code") != 0:
        return None

    for s in data.get("data", {}).get("sheets", []):
        if s.get("title") == sheet_name:
            return s.get("sheet_id")
    return None


def get_sheet_data(open_api_base, spreadsheet_token, sheet_name, token):
    # Use sheet_id to build range; avoids issues with non-ascii sheet titles.
    sheet_id = get_sheet_id(open_api_base, spreadsheet_token, sheet_name, token)
    if not sheet_id:
        return None

    range_str = f"{sheet_id}!A1:Z5000"
    url = f"{open_api_base}/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values/{range_str}?valueRenderOption=ToString"
    headers = {"Authorization": token, "Content-Type": "application/json"}
    if "Bearer " in token:
        headers["Cookie"] = f"session={token.split(' ')[1]}"

    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("code") == 0:
            return data.get("data", {}).get("valueRange", {}).get("values", [])
    return None

def save_snapshot(data, file_path):
    with open(file_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerows(data)

def load_snapshot(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return list(csv.reader(f))

def compare_data(old_data, new_data):
    diff = []
    max_rows = max(len(old_data), len(new_data))
    for i in range(max_rows):
        old_row = old_data[i] if i < len(old_data) else []
        new_row = new_data[i] if i < len(new_data) else []
        if old_row != new_row:
            diff.append({
                "row": i + 1,
                "old": old_row,
                "new": new_row
            })
    return diff

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python snapshot_diff_helper.py <mode:snapshot|diff> <document_url> <sheet_name> [snapshot_file]")
        sys.exit(1)

    mode = sys.argv[1]
    doc_url = sys.argv[2]
    sheet_name = sys.argv[3]
    snapshot_file = sys.argv[4] if len(sys.argv) > 4 else f"snapshot_{sheet_name}.csv"

    token = os.environ.get("AIME_USER_CLOUD_JWT")
    if token and not token.startswith("Bearer "):
        token = f"Bearer {token}"
    
    if not token:
        print("Error: AIME_USER_CLOUD_JWT not found.")
        sys.exit(1)

    ss_token = get_spreadsheet_token(doc_url)
    if not ss_token:
        print(f"Error: Could not extract spreadsheetToken from {doc_url}")
        sys.exit(1)

    open_api_base = get_open_api_base(doc_url)

    if mode == "snapshot":
        data = get_sheet_data(open_api_base, ss_token, sheet_name, token)
        if data is None:
            print(f"Error: Failed to fetch data for sheet '{sheet_name}'.")
            sys.exit(1)
        save_snapshot(data, snapshot_file)
        print(f"Success: Snapshot saved to {snapshot_file}")

    elif mode == "diff":
        if not os.path.exists(snapshot_file):
            print(f"Error: Snapshot file {snapshot_file} not found.")
            sys.exit(1)
        
        old_data = load_snapshot(snapshot_file)
        new_data = get_sheet_data(open_api_base, ss_token, sheet_name, token)
        if new_data is None:
            print(f"Error: Failed to fetch current data for sheet '{sheet_name}'.")
            sys.exit(1)
        
        diff = compare_data(old_data, new_data)
        if not diff:
            print("No differences found.")
        else:
            print(f"Found {len(diff)} changed rows:")
            print(json.dumps(diff, indent=2, ensure_ascii=False))
