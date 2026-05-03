#!/usr/bin/env python3
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import quote, urlparse

import requests

DEFAULT_EMAIL = "yuqinan@bytedance.com"
DEFAULT_OPEN_API_BASE = "https://fsopen.bytedance.net"
DEFAULT_UPLOAD_API_BASE = "https://open.feishu.cn"

# --- SSOT (Single Source of Truth) Version Sync Bus ---
# We treat `version:` in the target skill's SKILL.md frontmatter as SSOT.
# During Archive, we bump version (Major: +1.0 / Minor: +0.1) and sync it to:
# 1) local SKILL.md
# 2) Feishu skill inventory sheet (Version column)
# 3) (optional) Feishu skill doc version marker
DEFAULT_SSOT_SPREADSHEET_TOKEN = "ECQ0sDwmbhDex9tcUSjlkU7Bgdh"
DEFAULT_SSOT_SHEET_NAME = "专属技能清单"
DEFAULT_SSOT_SHEET_NAME_FALLBACKS = ["专属技能清单_Sheet"]

DEFAULT_SSOT_VERSION_HEADERS = ["版本号", "版本", "version", "Version"]
DEFAULT_SSOT_ID_HEADERS = ["技能编号", "Skill ID", "skill_id", "SkillID", "ID", "编号", "包 ID"]
DEFAULT_SSOT_NAME_HEADERS = ["技能名称", "技能名", "name", "Name"]

REQUIRED_DOC_TEMPLATE_MARKERS = [
    "🔑 触发词",
    "📖 案例实录",
]


class GuardrailViolation(RuntimeError):
    """Hard-stop exception for guardrail violations."""


def validate_doc_template_markers(doc_url: str) -> None:
    """L1/L2 doc-structure validator for skill docs.

    We validate markers AFTER downloading the doc via Lark MCP.
    """

    markdown_path = download_doc_markdown(doc_url)
    content = markdown_path.read_text(encoding="utf-8", errors="ignore")

    missing = [m for m in REQUIRED_DOC_TEMPLATE_MARKERS if m not in content]
    if missing:
        raise GuardrailViolation(
            "Skill doc template markers missing: " + ", ".join(missing)
        )


def run_cda_guardrails_selfcheck(skill_dir: Path, risk: str = "auto") -> str:
    """CDA Guardrails checkpoint: fail-fast before side effects."""

    selfcheck_script = Path(__file__).resolve().parent / "cda_guardrails_selfcheck.py"
    if not selfcheck_script.exists():
        raise FileNotFoundError(f"CDA selfcheck script not found: {selfcheck_script}")

    return run_subprocess(
        [
            "python3",
            str(selfcheck_script),
            "--skill-dir",
            str(skill_dir),
            "--risk",
            risk,
        ],
        "CDA-Guardrails-Selfcheck",
    )


def get_workspace_root() -> Path:
    env_path = os.environ.get("IRIS_WORKSPACE_PATH")
    if env_path:
        return Path(env_path).resolve()
    return Path(__file__).resolve().parents[3]


def get_raw_cloud_jwt() -> str:
    raw = (os.environ.get("AIME_USER_CLOUD_JWT") or "").strip()
    if not raw:
        raise RuntimeError(
            "Missing env var AIME_USER_CLOUD_JWT. Run this script with include_secrets=true."
        )
    return raw


def ensure_bearer_token() -> str:
    raw = get_raw_cloud_jwt()
    if raw.startswith("Bearer "):
        return raw
    return f"Bearer {raw}"


def build_headers(bearer_token: str, content_type: Optional[str] = None) -> Dict[str, str]:
    headers = {"Authorization": bearer_token}
    if content_type:
        headers["Content-Type"] = content_type
    if bearer_token.startswith("Bearer "):
        headers["Cookie"] = f"session={bearer_token.split(' ', 1)[1]}"
    return headers


def call_with_retry(action: str, callback: Callable[[], Any], attempts: int = 3, delay: float = 2.0) -> Any:
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return callback()
        except Exception as exc:  # noqa: PERF203
            last_error = exc
            if attempt == attempts:
                break
            print(f"⚠️ {action} failed on attempt {attempt}/{attempts}: {exc}")
            time.sleep(delay)
    raise RuntimeError(f"{action} failed after {attempts} attempts: {last_error}")


def create_skill_zip(skill_dir: Path, output_zip: Path) -> Path:
    if not skill_dir.is_dir():
        raise FileNotFoundError(f"Skill directory not found: {skill_dir}")

    skip_names = {".git", "__pycache__", ".DS_Store"}
    output_zip.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(skill_dir.rglob("*")):
            if any(part in skip_names for part in path.parts):
                continue
            if path == output_zip:
                continue
            arcname = Path(skill_dir.name) / path.relative_to(skill_dir)
            archive.write(path, arcname)

    return output_zip.resolve()


def get_root_folder_token(bearer_token: str, open_api_base: str) -> str:
    url = f"{open_api_base}/open-apis/drive/explorer/v2/root_folder/meta"
    response = requests.get(url, headers=build_headers(bearer_token), timeout=30)
    data = response.json()
    if response.status_code != 200 or data.get("code") != 0:
        raise RuntimeError(f"get root folder failed: http={response.status_code}, resp={data}")
    token = data.get("data", {}).get("token")
    if not token:
        raise RuntimeError(f"root folder token missing in response: {data}")
    return token


def upload_zip_to_drive(
    bearer_token: str,
    open_api_base: str,
    file_path: Path,
    parent_node: str = "",
) -> str:
    url = f"{open_api_base}/open-apis/drive/v1/files/upload_all"
    with file_path.open("rb") as file_obj:
        response = requests.post(
            url,
            headers=build_headers(bearer_token),
            data={
                "file_name": file_path.name,
                "parent_type": "explorer",
                "parent_node": parent_node,
                "size": str(file_path.stat().st_size),
            },
            files={"file": (file_path.name, file_obj)},
            timeout=300,
        )
    data = response.json()
    if response.status_code != 200 or data.get("code") != 0:
        raise RuntimeError(f"drive upload failed: http={response.status_code}, resp={data}")
    file_token = data.get("data", {}).get("file_token")
    if not file_token:
        raise RuntimeError(f"file_token missing after drive upload: {data}")
    return file_token


def add_permission_member(
    bearer_token: str,
    open_api_base: str,
    file_token: str,
    email: str,
    perm: str = "full_access",
) -> Dict[str, Any]:
    url = f"{open_api_base}/open-apis/drive/v1/permissions/{file_token}/members"
    response = requests.post(
        url,
        params={"type": "file", "need_notification": "false"},
        headers=build_headers(bearer_token, "application/json; charset=utf-8"),
        json={
            "member_type": "email",
            "member_id": email,
            "perm": perm,
            "type": "user",
        },
        timeout=30,
    )
    return {"http_status": response.status_code, "data": response.json()}


def update_permission_member(
    bearer_token: str,
    open_api_base: str,
    file_token: str,
    email: str,
    perm: str = "full_access",
) -> Dict[str, Any]:
    member_id = quote(email, safe="")
    url = f"{open_api_base}/open-apis/drive/v1/permissions/{file_token}/members/{member_id}"
    response = requests.put(
        url,
        params={"type": "file", "need_notification": "false"},
        headers=build_headers(bearer_token, "application/json; charset=utf-8"),
        json={"member_type": "email", "perm": perm, "type": "user"},
        timeout=30,
    )
    return {"http_status": response.status_code, "data": response.json()}


def ensure_drive_permission(
    bearer_token: str,
    open_api_base: str,
    file_token: str,
    email: str,
    perm: str = "full_access",
) -> None:
    create_result = add_permission_member(bearer_token, open_api_base, file_token, email, perm)
    if create_result["http_status"] == 200 and create_result["data"].get("code") == 0:
        return

    update_result = update_permission_member(bearer_token, open_api_base, file_token, email, perm)
    if update_result["http_status"] == 200 and update_result["data"].get("code") == 0:
        return

    raise RuntimeError(
        "grant drive permission failed\n"
        f"- create: {create_result}\n"
        f"- update: {update_result}"
    )


def build_drive_file_url(doc_url: str, file_token: str) -> str:
    parsed = urlparse(doc_url)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc or "bytedance.larkoffice.com"
    return f"{scheme}://{netloc}/file/{file_token}"


def run_subprocess(command: list[str], action: str) -> str:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"{action} failed with exit code {result.returncode}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout.strip()


# -----------------------------
# SSOT: Version Sync Bus
# -----------------------------

def ensure_bytedcli_auth() -> None:
    """Authenticate via bytedcli (required before MCP-based Feishu ops).

    NOTE: this expects the script to be executed with `include_secrets=true`
    so that IRIS_USER_CLOUD_JWT is available.
    """

    workspace_root = get_workspace_root()
    auth_script = workspace_root / "inner_skills/bytedcli-auth/scripts/bytedcli_auth.sh"
    if not auth_script.exists():
        raise FileNotFoundError(f"bytedcli auth script not found: {auth_script}")

    print("🔐 Ensuring bytedcli login (bytedcli-auth)...")
    run_subprocess(["bash", str(auth_script)], "bytedcli-auth")


def _normalize_version_to_int_pair(raw: str) -> Tuple[int, int]:
    raw = (raw or "").strip()
    raw = raw.lstrip("vV")

    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?$", raw)
    if not m:
        raise ValueError(f"Unsupported version format: {raw!r} (expected X.Y or X.Y.Z)")
    return int(m.group(1)), int(m.group(2))


def _format_version_pair(major: int, minor: int) -> str:
    return f"{major}.{minor}"


def read_skill_version_from_skill_md(skill_dir: Path) -> str:
    """Read SSOT version from target skill's SKILL.md frontmatter."""

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"SKILL.md not found: {skill_md}")

    content = skill_md.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"(?m)^version:\s*([^\n]+)\s*$", content)
    if not m:
        raise ValueError(f"version field not found in SKILL.md: {skill_md}")

    major, minor = _normalize_version_to_int_pair(m.group(1).strip())
    return _format_version_pair(major, minor)


def bump_version(current_version: str, bump_type: str) -> str:
    major, minor = _normalize_version_to_int_pair(current_version)
    bump_type = (bump_type or "").strip().lower()

    if bump_type == "major":
        return _format_version_pair(major + 1, 0)
    if bump_type == "minor":
        return _format_version_pair(major, minor + 1)

    raise ValueError(f"Unsupported bump type: {bump_type!r} (expected major/minor)")


def write_skill_md_version(skill_dir: Path, new_version: str) -> None:
    """Sync point #1: overwrite SSOT version in local SKILL.md."""

    skill_md = skill_dir / "SKILL.md"
    content = skill_md.read_text(encoding="utf-8", errors="ignore")

    # only replace the frontmatter version key; keep other content intact.
    replaced, n = re.subn(
        r"(?m)^version:\s*([^\n]+)\s*$",
        f"version: {new_version}",
        content,
        count=1,
    )
    if n != 1:
        raise RuntimeError(f"Unable to update version field in SKILL.md: {skill_md}")

    skill_md.write_text(replaced, encoding="utf-8")


def build_ssot_spreadsheet_url(spreadsheet_token: str) -> str:
    token = (spreadsheet_token or "").strip()
    if token.startswith("http://") or token.startswith("https://"):
        return token
    return f"https://bytedance.larkoffice.com/sheets/{token}"


def mcp_lark_download(document_url: str) -> list[Path]:
    workspace_root = get_workspace_root()
    download_script = workspace_root / "inner_skills/lark/mcp_lark_lark_download.py"
    if not download_script.exists():
        raise FileNotFoundError(f"Lark MCP download script not found: {download_script}")

    output = run_subprocess(
        [
            "python3",
            str(download_script),
            json.dumps({"document_url": document_url}, ensure_ascii=False),
        ],
        "lark download",
    )

    # Typical output contains repeated: file_path: "..."
    paths = [Path(p).resolve() for p in re.findall(r'file_path:\s*"([^"]+)"', output)]
    if not paths:
        # fallback: any xlsx path in output
        paths = [Path(p).resolve() for p in re.findall(r'(/[^\s\"]+\.xlsx)', output)]

    if not paths:
        raise RuntimeError(f"Unable to parse downloaded file paths from output: {output}")

    return paths


def _pick_first_xlsx(paths: list[Path]) -> Path:
    for p in paths:
        if p.suffix.lower() in {".xlsx", ".xls"}:
            return p
    raise RuntimeError(f"No xlsx file found in downloaded paths: {paths}")


def _normalize_header_value(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _normalize_skill_name_cell(v: Any) -> str:
    """Normalize skill name cell.

    In the inventory sheet, "技能名称" is often a HYPERLINK formula like:
    =HYPERLINK("url", "name")
    We extract the visible name part for matching.
    """

    raw = _normalize_header_value(v)
    if not raw:
        return ""

    if raw.lstrip().upper().startswith("=HYPERLINK"):
        parts = re.findall(r'"([^"]+)"', raw)
        if len(parts) >= 2:
            return parts[-1].strip()
    return raw


def _find_header_col_index(headers: list[str], candidates: list[str]) -> Optional[int]:
    lowered = [h.lower() for h in headers]
    for c in candidates:
        if c.lower() in lowered:
            return lowered.index(c.lower())
    return None


def _choose_sheet_name(workbook_sheetnames: list[str], preferred: str) -> str:
    if preferred in workbook_sheetnames:
        return preferred
    for alt in DEFAULT_SSOT_SHEET_NAME_FALLBACKS:
        if alt in workbook_sheetnames:
            return alt
    raise RuntimeError(
        "SSOT sheet not found. "
        f"preferred={preferred!r}, available={workbook_sheetnames!r}, fallbacks={DEFAULT_SSOT_SHEET_NAME_FALLBACKS!r}"
    )


def update_xlsx_version_cell(
    *,
    source_xlsx: Path,
    sheet_name: str,
    skill_id: str,
    skill_name: str,
    new_version: str,
) -> Tuple[Path, str]:
    """Update the Version cell in a local xlsx copy.

    Returns: (updated_xlsx_path, debug_location)
    """

    try:
        from openpyxl import load_workbook  # type: ignore
    except Exception as exc:  # noqa: PERF203
        raise RuntimeError(
            "Missing dependency openpyxl. Please install it (pip install openpyxl) before running this script."
        ) from exc

    wb = load_workbook(source_xlsx)
    real_sheet_name = _choose_sheet_name(wb.sheetnames, sheet_name)
    ws = wb[real_sheet_name]

    # assume the first row is header
    header_row = [
        _normalize_header_value(ws.cell(row=1, column=c).value) for c in range(1, ws.max_column + 1)
    ]

    id_col = _find_header_col_index(header_row, DEFAULT_SSOT_ID_HEADERS)
    name_col = _find_header_col_index(header_row, DEFAULT_SSOT_NAME_HEADERS)
    version_col = _find_header_col_index(header_row, DEFAULT_SSOT_VERSION_HEADERS)

    if version_col is None:
        raise RuntimeError(
            f"Unable to locate version column by headers {DEFAULT_SSOT_VERSION_HEADERS!r}. "
            f"sheet={real_sheet_name!r}, header_row={header_row!r}"
        )

    # openpyxl column index is 1-based
    version_col_1b = version_col + 1
    id_col_1b = id_col + 1 if id_col is not None else None
    name_col_1b = name_col + 1 if name_col is not None else None

    matched_row: Optional[int] = None
    matched_by = ""
    for r in range(2, ws.max_row + 1):
        rid = _normalize_header_value(ws.cell(row=r, column=id_col_1b).value) if id_col_1b else ""
        rname = _normalize_skill_name_cell(ws.cell(row=r, column=name_col_1b).value) if name_col_1b else ""

        if skill_id and rid and rid.strip() == skill_id.strip():
            matched_row = r
            matched_by = "skill_id"
            break
        if skill_name and rname and rname.strip() == skill_name.strip():
            matched_row = r
            matched_by = "skill_name"
            break

    if not matched_row:
        raise RuntimeError(
            "Unable to locate target skill row in SSOT sheet. "
            f"skill_id={skill_id!r}, skill_name={skill_name!r}, sheet={real_sheet_name!r}"
        )

    ws.cell(row=matched_row, column=version_col_1b).value = new_version

    updated_path = source_xlsx.parent / f"ssot_updated_{uuid.uuid4().hex}.xlsx"
    wb.save(updated_path)

    debug_loc = f"{real_sheet_name}!R{matched_row}C{version_col_1b} (matched_by={matched_by})"
    return updated_path, debug_loc


def sync_version_to_lark_sheet(
    *,
    spreadsheet_url: str,
    sheet_name: str,
    skill_id: str,
    skill_name: str,
    new_version: str,
) -> None:
    """Sync point #2: update the Version column in Feishu inventory sheet via MCP."""

    workspace_root = get_workspace_root()
    update_script = workspace_root / "inner_skills/lark_sheets_update/mcp_lark_sheets_update_lark_update_sheet.py"
    if not update_script.exists():
        raise FileNotFoundError(f"Lark Sheets Update MCP script not found: {update_script}")

    print("📥 Downloading SSOT spreadsheet xlsx...")
    downloaded = _pick_first_xlsx(mcp_lark_download(spreadsheet_url))

    with tempfile.TemporaryDirectory(prefix="ssot_sheet_", dir=workspace_root) as temp_dir:
        temp_dir_path = Path(temp_dir)
        local_xlsx = temp_dir_path / downloaded.name
        shutil.copy2(downloaded, local_xlsx)

        updated_xlsx, debug_loc = update_xlsx_version_cell(
            source_xlsx=local_xlsx,
            sheet_name=sheet_name,
            skill_id=skill_id,
            skill_name=skill_name,
            new_version=new_version,
        )
        print(f"🚌 SSOT sheet version cell updated locally: {debug_loc}")

        print("📤 Syncing updated xlsx back to Feishu via lark_sheets_update...")
        run_subprocess(
            [
                "python3",
                str(update_script),
                json.dumps(
                    {
                        "document_url": spreadsheet_url,
                        "sheet_name": sheet_name,
                        "source_file_path": str(updated_xlsx.resolve()),
                    },
                    ensure_ascii=False,
                ),
            ],
            "lark_sheets_update",
        )

        # RAW-ish post-check: wait a bit then download and verify.
        time.sleep(2)
        re_downloaded = _pick_first_xlsx(mcp_lark_download(spreadsheet_url))
        verify_path = temp_dir_path / f"verify_{re_downloaded.name}"
        shutil.copy2(re_downloaded, verify_path)

        try:
            from openpyxl import load_workbook  # type: ignore
        except Exception:
            print("⚠️ openpyxl missing, skip post-read verification.")
            return

        wb = load_workbook(verify_path, data_only=False)
        real_sheet_name = _choose_sheet_name(wb.sheetnames, sheet_name)
        ws = wb[real_sheet_name]

        header_row = [
            _normalize_header_value(ws.cell(row=1, column=c).value) for c in range(1, ws.max_column + 1)
        ]
        id_col = _find_header_col_index(header_row, DEFAULT_SSOT_ID_HEADERS)
        name_col = _find_header_col_index(header_row, DEFAULT_SSOT_NAME_HEADERS)
        version_col = _find_header_col_index(header_row, DEFAULT_SSOT_VERSION_HEADERS)
        if version_col is None:
            print("⚠️ Unable to re-locate version column during verification, skip.")
            return

        id_col_1b = id_col + 1 if id_col is not None else None
        name_col_1b = name_col + 1 if name_col is not None else None
        version_col_1b = version_col + 1

        current = None
        for r in range(2, ws.max_row + 1):
            rid = _normalize_header_value(ws.cell(row=r, column=id_col_1b).value) if id_col_1b else ""
            rname = _normalize_skill_name_cell(ws.cell(row=r, column=name_col_1b).value) if name_col_1b else ""
            if skill_id and rid and rid.strip() == skill_id.strip():
                current = _normalize_header_value(ws.cell(row=r, column=version_col_1b).value)
                break
            if skill_name and rname and rname.strip() == skill_name.strip():
                current = _normalize_header_value(ws.cell(row=r, column=version_col_1b).value)
                break

        if current != new_version:
            raise RuntimeError(
                "SSOT sheet post-read verification FAILED. "
                f"expected={new_version!r}, got={current!r}, spreadsheet_url={spreadsheet_url}"
            )
        print("✅ SSOT sheet post-read verification PASSED.")


def attach_zip_to_doc_via_mcp(doc_url: str, zip_path: Path) -> str:
    workspace_root = get_workspace_root()
    update_script = workspace_root / "inner_skills/lark/mcp_lark_update_lark_doc.py"
    if not update_script.exists():
        raise FileNotFoundError(f"Lark MCP update script not found: {update_script}")

    with tempfile.TemporaryDirectory(prefix="skill_zip_attach_", dir=workspace_root) as temp_dir:
        temp_path = Path(temp_dir)
        temp_zip = temp_path / zip_path.name
        shutil.copy2(zip_path, temp_zip)
        markdown_path = temp_path / "attachment.lark.md"
        markdown_path.write_text(f"![{temp_zip.name}]({temp_zip.name})\n", encoding="utf-8")

        payload = {
            "document_url": doc_url,
            "markdown_file_path": str(markdown_path.resolve()),
            "modifications": [
                {
                    "block_number": "BLOCK_BEGIN",
                    "block_id": "",
                    "content": f"![{temp_zip.name}]({temp_zip.name})\n",
                    "modification_type": "insert",
                }
            ],
        }
        return run_subprocess(
            ["python3", str(update_script), json.dumps(payload, ensure_ascii=False)],
            "insert native file block via lark MCP",
        )


def download_doc_markdown(doc_url: str) -> Path:
    workspace_root = get_workspace_root()
    download_script = workspace_root / "inner_skills/lark/mcp_lark_lark_download.py"
    if not download_script.exists():
        raise FileNotFoundError(f"Lark MCP download script not found: {download_script}")

    output = run_subprocess(
        ["python3", str(download_script), json.dumps({"document_url": doc_url}, ensure_ascii=False)],
        "download latest skill doc",
    )
    match = re.search(r'file_path: "([^"]+)"', output)
    if not match:
        raise RuntimeError(f"Unable to parse downloaded markdown path from output: {output}")
    return Path(match.group(1)).resolve()


def sync_version_to_skill_doc_via_mcp(doc_url: str, new_version: str) -> None:
    """Sync point #3: replace version marker inside the Feishu skill doc.

    This is a best-effort update:
    - We download the doc as .lark.md with block markers
    - Find the first block that contains an explicit version marker
    - Update that block via lark MCP

    If no marker is found, we will log a warning and skip.
    """

    workspace_root = get_workspace_root()
    update_script = workspace_root / "inner_skills/lark/mcp_lark_update_lark_doc.py"
    if not update_script.exists():
        raise FileNotFoundError(f"Lark MCP update script not found: {update_script}")

    md_path = download_doc_markdown(doc_url)
    text = md_path.read_text(encoding="utf-8", errors="ignore")

    block_re = re.compile(r"^<!--\s*(BLOCK_\d+)\s*\|\s*([^\s]+)\s*-->\s*$")
    end_re = re.compile(r"^<!--\s*END_BLOCK_\d+\s*-->\s*$")
    version_re = re.compile(r"(?i)((?:version|版本号|版本)\s*[:：]\s*)([vV]?\d+(?:\.\d+){1,2})")

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = block_re.match(lines[i])
        if not m:
            i += 1
            continue

        block_number = m.group(1)
        block_id = m.group(2)
        i += 1

        content_lines: list[str] = []
        while i < len(lines) and not end_re.match(lines[i]):
            content_lines.append(lines[i])
            i += 1

        content = "\n".join(content_lines).strip("\n")
        if version_re.search(content):
            updated_content = version_re.sub(r"\\1" + new_version, content)
            payload = {
                "document_url": doc_url,
                "markdown_file_path": str(md_path.resolve()),
                "modifications": [
                    {
                        "block_number": block_number,
                        "block_id": block_id,
                        "content": updated_content + "\n",
                        "modification_type": "update",
                    }
                ],
            }

            print(f"📝 Syncing doc version marker via MCP: {block_number} | {block_id}")
            run_subprocess(
                ["python3", str(update_script), json.dumps(payload, ensure_ascii=False)],
                "sync doc version marker",
            )
            return

        # skip end marker
        i += 1

    print("⚠️ No explicit version marker found in doc; skip SSOT doc sync.")


def verify_file_block_attached(doc_url: str, zip_name: str) -> bool:
    markdown_path = download_doc_markdown(doc_url)
    content = markdown_path.read_text(encoding="utf-8")
    zip_stem = Path(zip_name).stem
    return f"file_{zip_stem}" in content or zip_name in content or zip_stem in content


def parse_doc_token(doc_url: str) -> str:
    path = urlparse(doc_url).path or ""
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"docx", "docs", "doc"}:
        return parts[1]
    raise ValueError(f"Unsupported doc url: {doc_url}")


def call_lark_proxy(method_name: str, *, path: Optional[Dict[str, Any]] = None, query: Optional[Dict[str, Any]] = None, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    api_host = (os.environ.get("IRIS_RUNTIME_AIME_API_HOST") or "aime.bytedance.net").strip()
    if api_host.startswith("http://") or api_host.startswith("https://"):
        proxy_url = f"{api_host.rstrip('/')}/api/agents/v2/internal/proxy/lark_api"
    else:
        proxy_url = f"https://{api_host}/api/agents/v2/internal/proxy/lark_api"

    response = requests.post(
        proxy_url,
        headers={"Authorization": f"Byte-Cloud-JWT {get_raw_cloud_jwt()}"},
        json={
            "method_name": method_name,
            "path": path or {},
            "query": query or {},
            "body": body or {},
            "use_user_token": True,
        },
        timeout=60,
    )
    data = response.json()
    if response.status_code != 200:
        raise RuntimeError(f"lark proxy failed: http={response.status_code}, resp={data}")
    return data


def list_doc_file_blocks(doc_url: str) -> list[Dict[str, str]]:
    document_id = parse_doc_token(doc_url)
    response = call_lark_proxy(
        "docx.v1.document_block.list",
        path={"document_id": document_id},
        query={"page_size": "500"},
    )

    items = response.get("data", {}).get("items") or response.get("items") or []
    file_blocks: list[Dict[str, str]] = []
    for item in items:
        file_info = item.get("file") or {}
        file_token = file_info.get("file_token") or file_info.get("token") or ""
        file_name = file_info.get("name") or file_info.get("file_name") or ""
        if file_token:
            file_blocks.append(
                {
                    "block_id": item.get("block_id", ""),
                    "file_token": file_token,
                    "file_name": file_name,
                }
            )
    return file_blocks


def find_new_file_token(before_blocks: list[Dict[str, str]], after_blocks: list[Dict[str, str]], file_name: str) -> str:
    before_tokens = {item.get("file_token", "") for item in before_blocks}
    named_candidates = [
        item for item in after_blocks if item.get("file_name") == file_name and item.get("file_token") not in before_tokens
    ]
    if named_candidates:
        return named_candidates[0]["file_token"]

    new_candidates = [item for item in after_blocks if item.get("file_token") not in before_tokens]
    if new_candidates:
        return new_candidates[0]["file_token"]

    raise RuntimeError(f"Unable to locate the newly inserted File Block token for {file_name}")


def extract_metadata(
    name: str,
    desc: str,
    doc_link: str,
    version: str = "",
    skill_id: Optional[str] = None,
    skill_dir: Optional[Path] = None,
    zip_path: Optional[Path] = None,
    drive_file_token: Optional[str] = None,
    drive_file_url: Optional[str] = None,
) -> Dict[str, Any]:
    now = datetime.datetime.now()
    return {
        "skill_id": skill_id or f"SKILL-{now.strftime('%m%d%H%M')}",
        "name": name,
        "description": desc,
        "version": version,
        "doc_link": doc_link,
        "date": now.strftime("%Y-%m-%d"),
        "updated_at": now.strftime("%Y-%m-%d %H:%M"),
        "skill_dir": str(skill_dir.resolve()) if skill_dir else "",
        "zip_path": str(zip_path.resolve()) if zip_path else "",
        "zip_name": zip_path.name if zip_path else "",
        "drive_file_token": drive_file_token or "",
        "drive_file_url": drive_file_url or "",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="目标技能名称")
    parser.add_argument("--desc", required=True, help="目标技能功能描述")
    parser.add_argument("--path", required=True, help="目标技能说明飞书文档 URL")
    parser.add_argument("--skill-dir", help="目标技能目录，例如 user_skills/xxx")
    parser.add_argument("--id", required=False, help="技能编号或包 ID")
    parser.add_argument("--user-email", default=DEFAULT_EMAIL, help="默认授予 Full Access 的邮箱")
    parser.add_argument("--output-zip", help="可选，自定义 zip 输出路径")

    # SSOT version sync bus
    parser.add_argument(
        "--bump",
        choices=["major", "minor"],
        help="SSOT 版本升迁：major(+1.0) / minor(+0.1)。若未提供且为交互式终端，会提示选择；非交互式将直接报错。",
    )
    parser.add_argument(
        "--new-version",
        help="直接指定新版本号（标准 X.Y 两段式，如 5.2）。优先级高于 --bump。",
    )
    parser.add_argument(
        "--skip-ssot",
        action="store_true",
        help="调试用：跳过 SSOT 版本同步（不会改动目标技能的 SKILL.md，也不会同步台账/文档版本标识）。",
    )
    parser.add_argument(
        "--ssot-spreadsheet-token",
        default=DEFAULT_SSOT_SPREADSHEET_TOKEN,
        help="飞书技能台账 Spreadsheet Token 或完整 URL（默认使用主台账）。",
    )
    parser.add_argument(
        "--ssot-sheet-name",
        default=DEFAULT_SSOT_SHEET_NAME,
        help="飞书技能台账工作表名称（默认：专属技能清单）。",
    )
    parser.add_argument(
        "--skip-ssot-sheet-sync",
        action="store_true",
        help="调试用：跳过台账版本号覆写。",
    )
    parser.add_argument(
        "--skip-ssot-doc-sync",
        action="store_true",
        help="调试用：跳过说明文档版本标识同步。",
    )

    parser.add_argument(
        "--skip-remote",
        action="store_true",
        help="仅执行本地打包与 metadata 生成，跳过飞书云盘上传、权限赋予、文档挂载与 SSOT 远端同步",
    )
    args = parser.parse_args()

    workspace_root = get_workspace_root()
    skill_dir = (workspace_root / args.skill_dir).resolve() if args.skill_dir else None
    zip_path: Optional[Path] = None
    drive_file_token = ""
    drive_file_url = ""

    # SSOT version (X.Y)
    ssot_version = ""
    if skill_dir:
        if args.skip_ssot:
            ssot_version = read_skill_version_from_skill_md(skill_dir)
            print(f"🚌 SSOT disabled (--skip-ssot). Keep current version: {ssot_version}")
        else:
            current_version = read_skill_version_from_skill_md(skill_dir)
            new_version = ""

            if args.new_version:
                major, minor = _normalize_version_to_int_pair(args.new_version)
                new_version = _format_version_pair(major, minor)
            else:
                bump_type = args.bump
                if not bump_type:
                    if sys.stdin.isatty():
                        print("\n=== SSOT Version Bump ===")
                        print(f"current: {current_version}")
                        print("choose bump type:")
                        print("  1) minor (+0.1)")
                        print("  2) major (+1.0)")
                        choice = (input("Select (default=1): ") or "1").strip()
                        bump_type = "major" if choice == "2" else "minor"
                    else:
                        raise RuntimeError(
                            "SSOT version sync requires --bump {major|minor} or --new-version X.Y in non-interactive mode."
                        )
                new_version = bump_version(current_version, bump_type)

            ssot_version = new_version
            if ssot_version != current_version:
                print(f"🚌 SSOT bump: {current_version} -> {ssot_version}")
                write_skill_md_version(skill_dir, ssot_version)
            else:
                print(f"🚌 SSOT version unchanged: {ssot_version}")

        # --- CDA Guardrails Checkpoint (fail fast) ---
        print("🚧 Running CDA-Guardrails-Selfcheck before packaging...")
        print(run_cda_guardrails_selfcheck(skill_dir))

        output_zip = Path(args.output_zip).resolve() if args.output_zip else skill_dir.parent / f"{skill_dir.name}.zip"
        print(f"🚀 Packaging skill directory: {skill_dir}")
        zip_path = create_skill_zip(skill_dir, output_zip)
        print(f"✅ Skill package created: {zip_path}")

        if not args.skip_remote:
            # Per system guardrails: authenticate bytedcli before any Feishu MCP operations.
            ensure_bytedcli_auth()
            bearer_token = ensure_bearer_token()

            print("🚧 Validating skill doc template markers...")
            call_with_retry(
                "validate skill doc template markers",
                lambda: validate_doc_template_markers(args.path),
            )

            before_blocks: list[Dict[str, str]] = []
            try:
                before_blocks = list_doc_file_blocks(args.path)
            except Exception as exc:
                print(f"⚠️ Unable to list doc blocks before attachment: {exc}")

            print("🚀 Inserting native File Block into skill doc via Lark MCP...")
            attach_output = call_with_retry(
                "insert file block into skill doc",
                lambda: attach_zip_to_doc_via_mcp(args.path, zip_path),
            )
            verified = call_with_retry(
                "verify attached file block via lark MCP download",
                lambda: verify_file_block_attached(args.path, zip_path.name),
            )
            if not verified:
                raise RuntimeError(f"File Block verification failed for {zip_path.name}")

            print("✅ Skill doc attachment sync finished and verified.")
            if attach_output:
                print(attach_output)

            if ssot_version and (not args.skip_ssot) and (not args.skip_ssot_doc_sync):
                print("🚌 Syncing SSOT version marker to skill doc...")
                call_with_retry(
                    "sync ssot version marker",
                    lambda: sync_version_to_skill_doc_via_mcp(args.path, ssot_version),
                )

            try:
                after_blocks = list_doc_file_blocks(args.path)
                drive_file_token = find_new_file_token(before_blocks, after_blocks, zip_path.name)
            except Exception as exc:
                print(f"⚠️ Unable to resolve remote file token automatically: {exc}")
                drive_file_token = ""

            if drive_file_token:
                drive_file_url = build_drive_file_url(args.path, drive_file_token)
                print(f"🚀 Granting full_access to {args.user_email}...")
                call_with_retry(
                    "grant drive full_access",
                    lambda: ensure_drive_permission(
                        bearer_token,
                        DEFAULT_OPEN_API_BASE,
                        drive_file_token,
                        args.user_email,
                    ),
                )
                print("✅ Drive permission granted.")
            else:
                drive_file_url = args.path

    metadata = extract_metadata(
        args.name,
        args.desc,
        args.path,
        ssot_version,
        args.id,
        skill_dir,
        zip_path,
        drive_file_token,
        drive_file_url,
    )

    if (
        skill_dir
        and ssot_version
        and (not args.skip_ssot)
        and (not args.skip_remote)
        and (not args.skip_ssot_sheet_sync)
    ):
        ssot_sheet_url = build_ssot_spreadsheet_url(args.ssot_spreadsheet_token)
        print("🚌 Syncing SSOT version to Feishu inventory sheet...")
        call_with_retry(
            "sync ssot version to sheet",
            lambda: sync_version_to_lark_sheet(
                spreadsheet_url=ssot_sheet_url,
                sheet_name=args.ssot_sheet_name,
                skill_id=metadata.get("skill_id", ""),
                skill_name=metadata.get("name", ""),
                new_version=ssot_version,
            ),
        )

    metadata_path = Path.cwd() / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=4), encoding="utf-8")

    print("🚀 Metadata packaged for omni-asset-archiver:")
    print(json.dumps(metadata, indent=4, ensure_ascii=False))
    print(f"\n✅ Metadata written to {metadata_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
