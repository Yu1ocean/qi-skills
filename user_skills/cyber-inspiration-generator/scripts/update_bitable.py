import sys
import json
import datetime
import subprocess
from pathlib import Path

from scripts.add_record import add_record


APP_TOKEN = "PRbvbUyLqaeITqsXNMRcRCM5nhh"
TABLE_ID = "tbly6lJBR0QYTBfW"
ATTACHMENT_FIELD_ID = "fldsx6ENfb"  # 画廊头图


def _run_json(cmd):
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"command exited {proc.returncode}")
    stdout = proc.stdout.strip()
    json_start = stdout.find("{")
    if json_start < 0:
        raise RuntimeError(f"command returned non-json stdout: {stdout}")
    return json.loads(stdout[json_start:])


def _extract_record_id(add_resp):
    data = add_resp.get("data", {}) if isinstance(add_resp, dict) else {}
    record_ids = data.get("record_id_list") or []
    if record_ids:
        return record_ids[0]
    records = data.get("records") or data.get("data") or []
    if isinstance(records, list) and records:
        return records[0].get("record_id") or records[0].get("id")
    raise RuntimeError(f"无法从写入返回中解析 record_id: {json.dumps(add_resp, ensure_ascii=False)}")


def upload_attachment(record_id, screenshot_path):
    path = Path(screenshot_path)
    if not path.exists():
        raise FileNotFoundError(f"screenshot not found: {screenshot_path}")
    cmd = [
        "lark-cli",
        "base",
        "+record-upload-attachment",
        "--base-token",
        APP_TOKEN,
        "--table-id",
        TABLE_ID,
        "--record-id",
        record_id,
        "--field-id",
        ATTACHMENT_FIELD_ID,
        "--file",
        str(path),
        "--format",
        "json",
    ]
    return _run_json(cmd)


def update_bitable(subject, story_content, fact_content, image_url, screenshot_path, deployed_url):
    card_id = f"EP-CARD-{datetime.datetime.now().strftime('%y%m%d-%H%M')}"
    record_data = {
        "fields": {
            "收录日期": datetime.datetime.now().strftime("%Y-%m-%d 00:00:00"),
            "标题": subject,
            "直达链接": deployed_url,
            "精彩片段内容": f"{story_content}\n\n---\n\n{fact_content}",
            "核心标签": ["数字生命观察记录"],
            "卡片编号": card_id,
            "适用主题": "序章起源",
        }
    }

    print("Adding record to Bitable via lark-cli...")
    add_resp = add_record(APP_TOKEN, TABLE_ID, json.dumps(record_data, ensure_ascii=False))
    record_id = _extract_record_id(add_resp)
    print(f"✅ Bitable record added. record_id={record_id}; card_id={card_id}")

    if screenshot_path and Path(screenshot_path).exists():
        print(f"Uploading screenshot attachment: {screenshot_path}")
        upload_resp = upload_attachment(record_id, screenshot_path)
        print(f"✅ Screenshot attached: {json.dumps(upload_resp, ensure_ascii=False)}")
    else:
        print(f"⚠️ Screenshot path missing or not found, skipped attachment: {screenshot_path}")

    return {"card_id": card_id, "record_id": record_id, "add_resp": add_resp}


if __name__ == "__main__":
    if len(sys.argv) < 7:
        print("Usage: python3 update_bitable.py <subject> <story_content> <fact_content> <image_url> <screenshot_path> <deployed_url>")
        sys.exit(1)

    result = update_bitable(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6])
    print(json.dumps(result, ensure_ascii=False))
