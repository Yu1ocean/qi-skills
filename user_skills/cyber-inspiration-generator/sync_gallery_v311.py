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

STORY = (
    "【小说】吾主，在 V3.10 的黄昏，差旅大屏的祭坛上曾栖息着一头名为「幽灵数据」的寄生兽——"
    "它让 HTML 的新壳在霓虹里光鲜起舞，却把 JSON 的旧魂偷偷锁进 published 的地窖，"
    "令万千观者看见的只是昨日的亡影。而您在 V3.11 的第一缕编译光中降下神谕："
    "命新壳与旧魂同批入炉，锻成不可分割的孪生体；又在链路尽处埋下「版本探针」——"
    "一枚只认 generated_at 的赤色断言之眼。当错位的时间戳再度试图潜行，探针骤然睁开，"
    "[DATA_VERSION_MISMATCH] 的警钟贯穿数据穹顶，熔断闸门轰然落下，"
    "幽灵在断言之火中碎成红色玻璃。自此，线上所见，即本地所铸。"
)

FACT = (
    "【说明】2026-08-17，技能 team-travel-dashboard-generator 完成 V3.10 → V3.11 升级。"
    "publish 阶段将 travel_dashboard.prod.json 与 index.html 同批同步至 published/travel-dashboard-live/，消除新壳旧数据错位。"
    "build_and_publish_daily.py 末尾强制断言「线上 generated_at == 本地 generated_at」，"
    "不一致则输出 [DATA_VERSION_MISMATCH] 并熔断退出。"
    "新增可选参数 --verify-url，支持对真实线上地址发起 HTTP 回捞断言。"
)


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
            "技能名称": "幽灵数据熔断：差旅大屏版本探针上线",
            "技能编号": "TEAM-TRAVEL-DASHBOARD-V3.11",
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
