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
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote, urlparse

import requests

DEFAULT_EMAIL = "yuqinan@bytedance.com"
DEFAULT_OPEN_API_BASE = "https://fsopen.bytedance.net"
DEFAULT_UPLOAD_API_BASE = "https://open.feishu.cn"


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
    parser.add_argument(
        "--skip-remote",
        action="store_true",
        help="仅执行本地打包与 metadata 生成，跳过飞书云盘上传、权限赋予与文档挂载",
    )
    args = parser.parse_args()

    workspace_root = get_workspace_root()
    skill_dir = (workspace_root / args.skill_dir).resolve() if args.skill_dir else None
    zip_path: Optional[Path] = None
    drive_file_token = ""
    drive_file_url = ""

    if skill_dir:
        output_zip = Path(args.output_zip).resolve() if args.output_zip else skill_dir.parent / f"{skill_dir.name}.zip"
        print(f"🚀 Packaging skill directory: {skill_dir}")
        zip_path = create_skill_zip(skill_dir, output_zip)
        print(f"✅ Skill package created: {zip_path}")

        if not args.skip_remote:
            bearer_token = ensure_bearer_token()
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

            try:
                before_blocks = list_doc_file_blocks(args.path)
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
        args.id,
        skill_dir,
        zip_path,
        drive_file_token,
        drive_file_url,
    )

    metadata_path = Path.cwd() / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=4), encoding="utf-8")

    print("🚀 Metadata packaged for omni-asset-archiver:")
    print(json.dumps(metadata, indent=4, ensure_ascii=False))
    print(f"\n✅ Metadata written to {metadata_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
