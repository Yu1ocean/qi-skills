import os
import re
import sys
import json
from byted_aime_sdk import call_aime_tool

"""
幽灵对象（幻觉 Block）物理清理脚本
1. 物理斩除: 严禁使用文本替换，必须通过 Block ID 物理置空。
2. 精准定位: 使用信标 Beacon 逻辑确保不会误删。
"""

def find_block_id_for_beacon(markdown_content, beacon):
    # Lark markdown usually has: <!-- BLOCK_1 | block_id --> content <!-- END_BLOCK_1 -->
    # We search for the block containing the beacon.
    pattern = r"<!-- (BLOCK_\d+) \| ([^ ]+) -->(.*?)<!-- END_\1 -->"
    matches = re.finditer(pattern, markdown_content, re.DOTALL)
    for match in matches:
        if beacon in match.group(3):
            return match.group(2)
    return None

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python delete_ghost_block.py <document_url> <markdown_file_path> <beacon_string>")
        sys.exit(1)

    doc_url = sys.argv[1]
    md_path = sys.argv[2]
    beacon = sys.argv[3]

    if not os.path.exists(md_path):
        print(f"Error: Markdown file {md_path} not found.")
        sys.exit(1)

    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()

    block_id = find_block_id_for_beacon(md_content, beacon)
    if not block_id:
        print(f"Error: Could not find block ID for beacon '{beacon}' in the provided markdown.")
        sys.exit(1)

    print(f"Found Block ID: {block_id}. Calling lark_update_lark_doc to delete...")

    # Call the MCP tool
    params = {
        "document_url": doc_url,
        "updates": [
            {
                "block_id": block_id,
                "modification_type": "update",
                "content": "" # Empty content to "delete" or clear it
            }
        ]
    }
    
    try:
        # Note: We use call_aime_tool as instructed by common Aime practice
        # But since I'm a script, I should call the MCP script or use the sdk.
        # Here we'll just print the command for the agent to run or execute it if sdk available.
        # In Aime environment, call_aime_tool is preferred.
        res = call_aime_tool(toolset="lark", tool_name="mcp:lark_update_lark_doc", parameters=params, response_format="text")
        print(f"Success: {res}")
    except Exception as e:
        print(f"Error calling MCP: {e}")
        sys.exit(1)
