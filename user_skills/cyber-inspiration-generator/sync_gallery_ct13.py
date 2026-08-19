"""One-off Celebrate-stage sync into the V3 gallery table specified by the user.

Target: https://bytedance.larkoffice.com/base/PRbvbUyLqaeITqsXNMRcRCM5nhh?table=tblHHVXl9ObjSyRw
Reuses scripts.add_record + lark-cli attachment upload, but with the CORRECT table id
(the skill default scripts/update_bitable.py points at another table: tbly6lJBR0QYTBfW).
"""

import json
import subprocess
import sys
from pathlib import Path

from scripts.add_record import add_record

APP_TOKEN = "PRbvbUyLqaeITqsXNMRcRCM5nhh"
TABLE_ID = "tblHHVXl9ObjSyRw"          # V3 画廊（用户指定）
ATTACHMENT_FIELD_ID = "fldOBqrqET"     # 卡牌视觉

STORY = '【小说】吾主，在 230001 的深夜，中心化发信之门曾被一头名为「元数据寄生兽」的畜生撬开缝隙——它把 task_id、topic、run_id 的碎骨混入 content 的圣殿顶层，与 zh_cn 的语种圣名并列而坐，令飞书的守门判官三度拒信、万千通告沉没于虚空。而您在 v1.3 的第一缕编译光中降下神谕：先验结构，再问主题。于是五枚断言之刃 GUARD-POST-001 至 005 自穹顶垂落，逐层剖开 post 的骨骼——顶层只容语种、语种块必为字典、content 必为嵌套之列、每元素必佩 tag 之印。同时我斩断了主题取材的暗渠，令元数据永世不得伪装成正文。自此，凡不成形者，皆不得出门。'

FACT = '【说明】2026-08-19，技能 centralized-transmitter 完成 v1.2 → v1.3 升级。新增 post payload 结构护栏 GUARD-POST-001~005，在主题断言之前校验 content 顶层仅含语种键、语种块为 dict、content 为 list-of-list、元素为含 tag 的 dict。_extract_text_chunks() 移除 task_id/taskId/run_id 主题取材，并阻断非白名单 key 的字符串递归收集。本地测试 21/21 通过，退出码 0。'


def _run_json(cmd):
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"command exited {proc.returncode}")
    out = proc.stdout.strip()
    i = out.find("{")
    if i < 0:
        raise RuntimeError(f"non-json stdout: {out}")
    return json.loads(out[i:])


def main():
    deployed_url = sys.argv[1]
    screenshot = Path(sys.argv[2])
    if not screenshot.exists():
        raise FileNotFoundError(f"screenshot not found: {screenshot}")

    record = {
        "fields": {
            "技能名称": "静默协议：发信门的结构之刃",
            "技能编号": "CENTRALIZED-TRANSMITTER-V1.3",
            "技能类型": ["防错机制"],
            "关联文档/高光时刻": f"[查看全息卡片网页]({deployed_url})",
            "状态": ["已上线"],
            "功能简述": f"{STORY}\n\n{FACT}",
        }
    }

    print(f"[1/3] add record -> table {TABLE_ID}")
    resp = add_record(APP_TOKEN, TABLE_ID, json.dumps(record, ensure_ascii=False))
    if not resp.get("ok"):
        raise RuntimeError(f"record create failed: {json.dumps(resp, ensure_ascii=False)}")
    rid = resp["data"]["record_id_list"][0]
    print(f"    OK record_id={rid}")

    print(f"[2/3] upload attachment {screenshot.name} -> {ATTACHMENT_FIELD_ID}")
    up = _run_json([
        "lark-cli", "base", "+record-upload-attachment",
        "--base-token", APP_TOKEN, "--table-id", TABLE_ID,
        "--record-id", rid, "--field-id", ATTACHMENT_FIELD_ID,
        "--file", str(screenshot), "--format", "json",
    ])
    if not up.get("ok"):
        raise RuntimeError(f"attachment upload failed: {json.dumps(up, ensure_ascii=False)}")
    print(f"    OK {json.dumps(up.get('data'), ensure_ascii=False)}")

    print("[3/3] read-after-write verification")
    got = _run_json([
        "lark-cli", "base", "+record-get",
        "--base-token", APP_TOKEN, "--table-id", TABLE_ID,
        "--record-id", rid, "--format", "json",
    ])
    print(json.dumps(got, ensure_ascii=False)[:1500])

    print(json.dumps({
        "record_id": rid,
        "record_url": f"https://bytedance.larkoffice.com/base/{APP_TOKEN}?table={TABLE_ID}&record={rid}",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
