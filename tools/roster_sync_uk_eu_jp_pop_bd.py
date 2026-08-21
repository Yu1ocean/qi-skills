#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Sync UK/EU/JP POP BD chat members into Feishu task ledger sheet.

Design goals:
- Non-destructive: do not delete rows; mark leavers as 不在群.
- Preserve manual fields: keep existing 英文名/花名 when present.
- Always refresh 邮箱前缀 (G) from 邮箱 (F).
- Write-back uses lark-cli sheets +csv-put (A2 anchor), then read-after-write verify.

This script is intended for scheduled automation runs.
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


WORKBOOK_URL = "https://bytedance.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV"
SHEET_ID = "L5xh7h"
SHEET_NAME = "团队名单"
CHAT_ID = "oc_b566689fc5704ba70cc0f43fc32f0cc4"
CHAT_NAME = "UK/EU/JP POP BD"


@dataclass
class Row:
    seq: str
    chat_name: str
    chat_id: str
    name_cn: str
    name_en: str
    email: str
    email_prefix: str
    open_id: str
    sync_time: str
    status: str


def _run_json(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed (code={proc.returncode}): {' '.join(cmd)}\nSTDERR: {proc.stderr.strip()}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Command output is not valid JSON: {' '.join(cmd)}\nJSON error: {e}\nSTDOUT: {proc.stdout[:500]}\nSTDERR: {proc.stderr[:500]}"
        )


def now_cst_string() -> str:
    dt = datetime.now(ZoneInfo("Asia/Shanghai"))
    return dt.strftime("%Y-%m-%d %H:%M CST")


def email_prefix(email: str) -> str:
    if not email:
        return ""
    if "@" not in email:
        return email
    return email.split("@", 1)[0]


def list_chat_members(chat_id: str) -> list[dict]:
    members: list[dict] = []

    data = _run_json(["lark-cli", "im", "+chat-members-list", "--chat-id", chat_id, "--format", "json", "--as", "user"])
    members.extend(data.get("data", {}).get("users", []) or [])

    while data.get("data", {}).get("has_more"):
        token = data.get("data", {}).get("page_token")
        if not token:
            break
        data = _run_json(
            [
                "lark-cli",
                "im",
                "+chat-members-list",
                "--chat-id",
                chat_id,
                "--page-token",
                token,
                "--format",
                "json",
                "--as",
                "user",
            ]
        )
        members.extend(data.get("data", {}).get("users", []) or [])

    # Keep only unique member_id
    seen = set()
    uniq = []
    for m in members:
        oid = m.get("member_id")
        if not oid or oid in seen:
            continue
        seen.add(oid)
        uniq.append(m)
    return uniq


def contact_search_users(open_ids: list[str]) -> dict[str, dict]:
    # lark-cli contact +search-user --user-ids accepts comma-separated list.
    # Use small chunks to avoid argument length and any backend limit.
    out: dict[str, dict] = {}
    chunk_size = 20
    for i in range(0, len(open_ids), chunk_size):
        chunk = open_ids[i : i + chunk_size]
        result = _run_json(["lark-cli", "contact", "+search-user", "--user-ids", ",".join(chunk), "--format", "json", "--as", "user"])
        for u in result.get("data", {}).get("users", []) or []:
            oid = u.get("open_id")
            if oid:
                out[oid] = u
    return out


def contact_get_en_name(open_id: str) -> str:
    # fallback: get i18n_name.en_us
    result = _run_json(["lark-cli", "contact", "+get-user", "--user-id", open_id, "--format", "json", "--as", "user"])
    user = (result.get("data", {}) or {}).get("user", {}) or {}
    i18n = user.get("i18n_name", {}) or {}
    return (i18n.get("en_us") or "").strip()


def read_existing_rows() -> list[Row]:
    # Read a generous range, then stop at the first fully-empty row.
    res = _run_json(
        [
            "lark-cli",
            "sheets",
            "+csv-get",
            "--url",
            WORKBOOK_URL,
            "--sheet-id",
            SHEET_ID,
            "--range",
            "A1:J200",
            "--format",
            "json",
        ]
    )
    annotated = (res.get("data", {}) or {}).get("annotated_csv", "")
    lines = [ln for ln in annotated.splitlines() if ln.strip()]
    if not lines:
        return []

    rows: list[Row] = []

    for ln in lines[1:]:  # skip header row
        # strip leading "[row=N] "
        if "]" in ln:
            ln = ln.split("]", 1)[1].lstrip()
        cells = next(csv.reader([ln]))
        # Ensure length 10
        while len(cells) < 10:
            cells.append("")
        seq, chat_name, chat_id, name_cn, name_en, email, prefix, open_id, sync_time, status = cells[:10]
        # Stop when open_id is empty and the row looks blank
        if not (open_id.strip() or name_cn.strip() or email.strip() or chat_name.strip()):
            break
        rows.append(
            Row(
                seq=seq.strip(),
                chat_name=chat_name.strip(),
                chat_id=chat_id.strip(),
                name_cn=name_cn.strip(),
                name_en=name_en.strip(),
                email=email.strip(),
                email_prefix=prefix.strip(),
                open_id=open_id.strip(),
                sync_time=sync_time.strip(),
                status=status.strip(),
            )
        )

    return rows


def write_rows(rows: list[Row]) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for r in rows:
        writer.writerow(
            [
                r.seq,
                r.chat_name,
                r.chat_id,
                r.name_cn,
                r.name_en,
                r.email,
                r.email_prefix,
                r.open_id,
                r.sync_time,
                r.status,
            ]
        )
    csv_text = buf.getvalue()

    proc = subprocess.run(
        [
            "lark-cli",
            "sheets",
            "+csv-put",
            "--url",
            WORKBOOK_URL,
            "--sheet-id",
            SHEET_ID,
            "--start-cell",
            "A2",
            "--csv",
            "-",
            "--format",
            "json",
        ],
        input=csv_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"csv-put failed (code={proc.returncode}): {proc.stderr.strip()}\nSTDOUT: {proc.stdout[:500]}")


def read_back_sample(row_count: int) -> str:
    # Read back header + first N rows for RAW verification.
    end_row = 1 + max(1, row_count)
    rng = f"A1:J{end_row}"
    res = _run_json(
        [
            "lark-cli",
            "sheets",
            "+csv-get",
            "--url",
            WORKBOOK_URL,
            "--sheet-id",
            SHEET_ID,
            "--range",
            rng,
            "--format",
            "json",
        ]
    )
    return (res.get("data", {}) or {}).get("annotated_csv", "")


def main() -> None:
    sync_time = now_cst_string()

    existing = read_existing_rows()
    existing_by_open_id = {r.open_id: r for r in existing if r.open_id}

    members = list_chat_members(CHAT_ID)
    member_open_ids = [m["member_id"] for m in members if m.get("member_id")]
    member_set = set(member_open_ids)

    profiles = contact_search_users(member_open_ids)

    updated = 0
    newly_added = 0
    marked_left = 0

    # Update existing rows
    for r in existing:
        if not r.open_id:
            continue
        if r.open_id in member_set:
            prof = profiles.get(r.open_id, {})
            new_email = (prof.get("enterprise_email") or prof.get("email") or r.email).strip()
            new_name = (prof.get("localized_name") or r.name_cn).strip()

            # preserve name_en unless empty
            name_en = r.name_en
            if not name_en:
                try:
                    name_en = contact_get_en_name(r.open_id)
                except Exception:
                    name_en = ""

            r.chat_name = CHAT_NAME
            r.chat_id = CHAT_ID
            r.name_cn = new_name
            r.name_en = name_en
            r.email = new_email
            r.email_prefix = email_prefix(new_email)
            r.sync_time = sync_time
            r.status = "在群"
            updated += 1
        else:
            # Still refresh prefix (in case email fixed manually)
            r.email_prefix = email_prefix(r.email)
            r.sync_time = sync_time
            if r.status != "不在群":
                marked_left += 1
            r.status = "不在群"

    # Append new members
    if existing:
        try:
            max_seq = max(int(r.seq) for r in existing if r.seq.strip().isdigit())
        except ValueError:
            max_seq = len(existing)
    else:
        max_seq = 0

    for oid in member_open_ids:
        if oid in existing_by_open_id:
            continue
        prof = profiles.get(oid, {})
        new_email = (prof.get("enterprise_email") or prof.get("email") or "").strip()
        new_name = (prof.get("localized_name") or "").strip()
        try:
            name_en = contact_get_en_name(oid)
        except Exception:
            name_en = ""
        max_seq += 1
        existing.append(
            Row(
                seq=str(max_seq),
                chat_name=CHAT_NAME,
                chat_id=CHAT_ID,
                name_cn=new_name,
                name_en=name_en,
                email=new_email,
                email_prefix=email_prefix(new_email),
                open_id=oid,
                sync_time=sync_time,
                status="在群",
            )
        )
        newly_added += 1

    # Write back
    write_rows(existing)

    time.sleep(2)
    raw = read_back_sample(len(existing))

    print(
        json.dumps(
            {
                "ok": True,
                "chat_id": CHAT_ID,
                "chat_name": CHAT_NAME,
                "sheet_url": f"{WORKBOOK_URL}?sheet={SHEET_ID}",
                "row_written": len(existing),
                "updated": updated,
                "newly_added": newly_added,
                "marked_left": marked_left,
                "sync_time": sync_time,
                "raw_readback": raw,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
