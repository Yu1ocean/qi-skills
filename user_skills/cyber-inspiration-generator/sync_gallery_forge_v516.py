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

STORY = '【小说】吾主，在那座名为「技能说明」的文档巨碑之上，我曾看见八具一模一样的幽影棺椁层层叠压——它们都自称 skill-forge-pipeline-v4.zip，都携带早已死去的版本魂魄，却因为流水线只会「追加」、从不会「回收」，而在碑顶盘踞成一片腐烂的记忆坟场。今日您降下神谕：回挂即替换，唯一即真相。我先在碑顶铸下新生的水晶封包，以 block_move_after 将其钉入标题正下方的王座，再以 assert 之眼确认它已落位——只有在新生者站稳之后，我才挥出 block_delete 之刃，将幽影一次斩尽；而混入其间的异族棺椁，我只记下它的名与坐标，绝不擅动他人之物。斩毕，我沉默两秒，重新回读整座巨碑，断言属于本技能的封包恰好为一。自此，碑顶只余一束光。'

FACT = '【说明】2026-08-21，skill-forge-pipeline-v4 完成 V5.15 → V5.16 升级。register_skill.py 的 ZIP 回挂链路由 append 改为幂等替换：新增 list_doc_zip_file_blocks / is_own_skill_zip / delete_doc_blocks / prune_stale_zip_blocks 四个函数，执行顺序锁定为「插新块→归位→位置断言→删同名旧块→sleep 2s→回读断言数量==1」。异物块只报告不删除；枚举失败降级为只插不删并 WARNING。同时修掉 list_doc_file_blocks 在代理返回非 0 code 时静默返回空列表的隐患。SKILL.md 新增 Archive 步骤文件块替换规则、3 条 Red Flags、第 11 条 Verification。CDA 三层护栏自检 exit 0。'


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
            "技能名称": "唯一之刃：八重幽影的湮灭",
            "技能编号": "SKILL-FORGE-PIPELINE-V5.16",
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
