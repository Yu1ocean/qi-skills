"""One-off Celebrate-stage sync into the V3 gallery table (feishu-doc-writing-guide v7.5).

Target: https://bytedance.larkoffice.com/base/PRbvbUyLqaeITqsXNMRcRCM5nhh?table=tblHHVXl9ObjSyRw
Pattern copied from sync_gallery_ct13.py (2026-08-19) — same table id / attachment field id.
"""

import json
import subprocess
import sys
from pathlib import Path

from scripts.add_record import add_record

APP_TOKEN = "PRbvbUyLqaeITqsXNMRcRCM5nhh"
TABLE_ID = "tblHHVXl9ObjSyRw"          # V3 画廊（用户指定）
ATTACHMENT_FIELD_ID = "fldOBqrqET"     # 卡牌视觉

STORY = "【小说】吾主，在 G 列的深渊里，我曾亲眼看着三枚本该各自发光的标签——EU、UK、JP——被一根名为「逗号」的锁链焊死成一具畸形的连体怪物。飞书的校验判官抬眼一瞥，认定这个叫「EU,UK,JP」的东西从不存在于任何选项名册，于是在单元格右上角烙下猩红的裁决角标，药丸熄灭，光泽尽失。最狡诈之处在于：当只写下孤零零一个「EU」时，怪物会伪装成顺民，让人误以为天下太平——这是最恶毒的偶发正常。而您在 v7.5 的第一道编译光中降下神谕：多选之值，本是数组，绝非字符。于是我挥出 multiple_values 的结构之刃，将连体怪物斩为三枚独立的灵魂，各自归位、各自发光；又在写入之门前立下 TRAP6-A/B/C 三重断言，凡携带分隔符者、凡以 value 冒充数组者、凡越出选项名册者，皆当场熔断，不得入内。自此，药丸永不熄灭。"

FACT = "【说明】2026-08-21，技能 feishu-doc-writing-guide 完成 v7.4 → v7.5 升级。新增「陷阱6：多选单元格逗号串写入导致药丸不渲染 + 红色校验角标」，锁定多选列写入通道为 +cells-set 的 multiple_values 结构化数组，禁用 value 纯文本与 +csv-put。Verification 新增第 10 条多选结构化写入收敛，写后必须 +cells-get --include value,multiple_values 回读断言。新增 L3 断言脚本 scripts/multiselect_write_guard.py，覆盖逗号串污染、结构缺失、选项越界三类熔断，本地 3 用例实跑通过（正例 exit=0，反例 exit=1）。"


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
            "技能名称": "多选之刃：药丸的解构重生",
            "技能编号": "SKL-2604-010-V7.5",
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
    print(json.dumps(got, ensure_ascii=False)[:1800])

    print(json.dumps({
        "record_id": rid,
        "record_url": f"https://bytedance.larkoffice.com/base/{APP_TOKEN}?table={TABLE_ID}&record={rid}",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
