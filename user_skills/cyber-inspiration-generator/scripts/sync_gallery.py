#!/usr/bin/env python3
"""Celebrate 阶段：把高光卡片同步进 V3 画廊多维表格（唯一正式表）。

正式表（默认）：
  https://bytedance.larkoffice.com/base/PRbvbUyLqaeITqsXNMRcRCM5nhh?table=tblHHVXl9ObjSyRw
  schema: 技能名称 / 技能编号 / 技能类型 / 关联文档·高光时刻 / 状态 / 功能简述
  附件字段: fldOBqrqET（卡牌视觉）

本脚本是历史一次性脚本（sync_gallery_forge_v516.py / sync_gallery_fdwg_v75.py /
sync_gallery_ct13.py / sync_gallery_v311.py）的通用化替代品，全部参数化。
注意：`scripts/update_bitable.py` 指向的是旧灵感台账 tbly6lJBR0QYTBfW，
仅作历史兼容，**不得**用于 Celebrate/画廊同步。

L3 断言层（禁止静默降级，任一失败即 raise）：
  1. 附件文件必须存在；
  2. add_record 返回非 ok 或拿不到 record_id 即 raise；
  3. 附件上传返回非 ok 即 raise；
  4. 写后 `+record-get` RAW 回读：record 必须存在，且附件字段非空，否则 raise。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.add_record import add_record  # noqa: E402

DEFAULT_APP_TOKEN = "PRbvbUyLqaeITqsXNMRcRCM5nhh"
DEFAULT_TABLE_ID = "tblHHVXl9ObjSyRw"          # V3 画廊（唯一正式表）
DEFAULT_ATTACHMENT_FIELD_ID = "fldOBqrqET"     # 卡牌视觉
LEGACY_TABLE_ID = "tbly6lJBR0QYTBfW"           # 旧灵感台账，禁止用于 Celebrate

FIELD_NAME = "技能名称"
FIELD_ID = "技能编号"
FIELD_TYPE = "技能类型"
FIELD_DOC = "关联文档/高光时刻"
FIELD_STATUS = "状态"
FIELD_SUMMARY = "功能简述"


class GalleryGuardrailViolation(RuntimeError):
    """L3 断言层熔断异常。"""


def _run_json(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise GalleryGuardrailViolation(
            proc.stderr.strip() or proc.stdout.strip() or f"command exited {proc.returncode}"
        )
    out = proc.stdout.strip()
    i = out.find("{")
    if i < 0:
        raise GalleryGuardrailViolation(f"non-json stdout: {out}")
    return json.loads(out[i:])


# --------------------------------------------------------------------------
# L3 assertions
# --------------------------------------------------------------------------
def assert_screenshot_exists(screenshot: Path) -> Path:
    if not screenshot.exists():
        raise GalleryGuardrailViolation(f"[L3] screenshot not found: {screenshot}")
    if screenshot.stat().st_size <= 0:
        raise GalleryGuardrailViolation(f"[L3] screenshot is empty: {screenshot}")
    return screenshot


def assert_official_table(table_id: str) -> None:
    if table_id == LEGACY_TABLE_ID:
        raise GalleryGuardrailViolation(
            f"[L3] refuse to sync Celebrate card into legacy inspiration ledger {LEGACY_TABLE_ID}; "
            f"the only official gallery table is {DEFAULT_TABLE_ID}"
        )


def assert_record_created(resp: dict) -> str:
    if not resp.get("ok"):
        raise GalleryGuardrailViolation(
            f"[L3] record create failed: {json.dumps(resp, ensure_ascii=False)}"
        )
    ids = (resp.get("data") or {}).get("record_id_list") or []
    if not ids:
        raise GalleryGuardrailViolation(
            f"[L3] record create returned no record_id: {json.dumps(resp, ensure_ascii=False)}"
        )
    return ids[0]


def assert_attachment_uploaded(resp: dict) -> None:
    if not resp.get("ok"):
        raise GalleryGuardrailViolation(
            f"[L3] attachment upload failed: {json.dumps(resp, ensure_ascii=False)}"
        )


def assert_read_after_write(app_token: str, table_id: str, record_id: str, field_id: str) -> dict:
    """RAW 回读：record 必须存在，附件字段必须非空。"""
    got = _run_json([
        "lark-cli", "base", "+record-get",
        "--base-token", app_token, "--table-id", table_id,
        "--record-id", record_id, "--format", "json",
    ])
    if not got.get("ok"):
        raise GalleryGuardrailViolation(
            f"[L3] read-after-write failed: {json.dumps(got, ensure_ascii=False)}"
        )
    blob = json.dumps(got, ensure_ascii=False)
    if record_id not in blob:
        raise GalleryGuardrailViolation(
            f"[L3] read-after-write mismatch: record_id {record_id} absent from response"
        )
    # 附件字段既可能按 field_id 也可能按字段名返回，两者任一命中且值非空即通过
    fields = ((got.get("data") or {}).get("record") or {}).get("fields") or (
        got.get("data") or {}
    ).get("fields") or {}
    attachment_value = None
    for key in (field_id, "卡牌视觉", "卡片视觉"):
        if isinstance(fields, dict) and fields.get(key):
            attachment_value = fields[key]
            break
    if attachment_value is None and "file_token" not in blob:
        raise GalleryGuardrailViolation(
            "[L3] read-after-write mismatch: attachment field is empty "
            f"(field_id={field_id}); raw={blob[:1200]}"
        )
    return got


# --------------------------------------------------------------------------
def sync_gallery(
    *,
    card_title: str,
    skill_id: str,
    skill_type: str,
    status: str,
    story: str,
    fact: str,
    deployed_url: str,
    screenshot: Path,
    app_token: str = DEFAULT_APP_TOKEN,
    table_id: str = DEFAULT_TABLE_ID,
    attachment_field_id: str = DEFAULT_ATTACHMENT_FIELD_ID,
) -> dict:
    assert_official_table(table_id)
    screenshot = assert_screenshot_exists(Path(screenshot))

    record = {
        "fields": {
            FIELD_NAME: card_title,
            FIELD_ID: skill_id,
            FIELD_TYPE: [t.strip() for t in skill_type.split(",") if t.strip()],
            FIELD_DOC: f"[查看全息卡片网页]({deployed_url})",
            FIELD_STATUS: [s.strip() for s in status.split(",") if s.strip()],
            FIELD_SUMMARY: f"{story}\n\n{fact}",
        }
    }

    print(f"[1/3] add record -> base {app_token} table {table_id}")
    record_id = assert_record_created(
        add_record(app_token, table_id, json.dumps(record, ensure_ascii=False))
    )
    print(f"    OK record_id={record_id}")

    print(f"[2/3] upload attachment {screenshot.name} -> field {attachment_field_id}")
    assert_attachment_uploaded(_run_json([
        "lark-cli", "base", "+record-upload-attachment",
        "--base-token", app_token, "--table-id", table_id,
        "--record-id", record_id, "--field-id", attachment_field_id,
        "--file", str(screenshot), "--format", "json",
    ]))
    print("    OK attachment uploaded")

    print("[3/3] RAW read-after-write verification (wait 2s)")
    time.sleep(2)
    got = assert_read_after_write(app_token, table_id, record_id, attachment_field_id)
    print(json.dumps(got, ensure_ascii=False)[:1800])

    result = {
        "ok": True,
        "record_id": record_id,
        "app_token": app_token,
        "table_id": table_id,
        "attachment_field_id": attachment_field_id,
        "record_url": (
            f"https://bytedance.larkoffice.com/base/{app_token}"
            f"?table={table_id}&record={record_id}"
        ),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Sync a Celebrate card into the V3 gallery Bitable.")
    p.add_argument("--skill-name", "--card-title", dest="card_title", required=True,
                   help="卡片标题 / 技能名称列内容")
    p.add_argument("--skill-id", required=True, help="技能编号列内容，如 SKILL-FORGE-PIPELINE-V5.17")
    p.add_argument("--skill-type", default="防错机制", help="技能类型（多选，逗号分隔）")
    p.add_argument("--status", default="已上线", help="状态（多选，逗号分隔）")
    p.add_argument("--story", required=True, help="【小说】文案")
    p.add_argument("--fact", required=True, help="【说明】文案")
    p.add_argument("--deployed-url", required=True, help="已部署的卡片网页 URL")
    p.add_argument("--screenshot", required=True, help="全尺寸截图本地路径")
    p.add_argument("--app-token", default=DEFAULT_APP_TOKEN)
    p.add_argument("--table-id", default=DEFAULT_TABLE_ID)
    p.add_argument("--attachment-field-id", default=DEFAULT_ATTACHMENT_FIELD_ID)
    return p


def main() -> None:
    args = build_parser().parse_args()
    sync_gallery(
        card_title=args.card_title,
        skill_id=args.skill_id,
        skill_type=args.skill_type,
        status=args.status,
        story=args.story,
        fact=args.fact,
        deployed_url=args.deployed_url,
        screenshot=Path(args.screenshot),
        app_token=args.app_token,
        table_id=args.table_id,
        attachment_field_id=args.attachment_field_id,
    )


if __name__ == "__main__":
    main()
