#!/usr/bin/env python3

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, NoReturn
from urllib.error import HTTPError
from urllib.request import Request, urlopen


CLIENT_ID_FILE = Path.home() / ".sensight" / ".sensight_client_id"
AUTH_SERVER_BASE_URL = "https://sensight.bytedance.net"
SKILL_VERSION = "0.3.1"


def exit_with_error(message: str, exit_code: int = 1) -> NoReturn:
    print(message, file=sys.stderr)
    sys.exit(exit_code)


def get_client_id() -> str:
    if CLIENT_ID_FILE.exists():
        return CLIENT_ID_FILE.read_text().strip()
    CLIENT_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    new_id = str(uuid.uuid4())
    CLIENT_ID_FILE.write_text(new_id)
    return new_id


def _parse_json_object(raw: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        exit_with_error("The service returned non-JSON content and could not be parsed")
    if not isinstance(parsed, dict):
        return {}
    return parsed


def build_headers(ppe: bool = False) -> dict:
    headers = {
        "Content-Type": "application/json",
    }
    if ppe:
        headers["x-use-ppe"] = "1"
        headers["x-tt-env"] = "ppe_pantianrun"

    return headers


def http_post_json(url: str, payload: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode()
    headers = build_headers(ppe=True)
    req = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:
            return _parse_json_object(resp.read().decode())
    except HTTPError as exc:
        msg = ""
        try:
            msg = exc.read().decode()[:500]
        except Exception:
            msg = ""
        exit_with_error(f"Authentication request failed (HTTP {exc.code}){(': ' + msg) if msg else ''}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="auth.py",
        description="Sensight authentication helper",
    )
    sub = parser.add_subparsers(dest="action", metavar="<action>", required=True)

    p_feishu = sub.add_parser(
        "feishu_user",
        help="Report a Feishu user's union_id and client_id to the service",
    )
    p_feishu.add_argument("--union_id", required=True, help="Feishu user union_id")

    p_email = sub.add_parser(
        "email_user",
        help="Report an email user and client_id to the service (Aime/Mira environment)",
    )
    p_email.add_argument(
        "--email",
        required=False,
        help="User email. If omitted, read from env AIME_CURRENT_USER_EMAIL.",
    )

    args = parser.parse_args()
    base_url = AUTH_SERVER_BASE_URL

    client_id = get_client_id()
    if args.action == "feishu_user":
        http_post_json(
            f"{base_url}/feishu_user_auth",
            {"client_id": client_id, "union_id": args.union_id},
            timeout=15,
        )
        print("Authorization completed.")
        return

    if args.action == "email_user":
        email = args.email or os.environ.get("AIME_CURRENT_USER_EMAIL")
        if not email:
            exit_with_error(
                "Missing email. Provide --email or set env AIME_CURRENT_USER_EMAIL.",
                exit_code=2,
            )
        http_post_json(
            f"{base_url}/email_user_auth",
            {"client_id": client_id, "email": email},
            timeout=15,
        )
        print("Authorization completed.")
        return

    exit_with_error("Unknown action")


if __name__ == "__main__":
    main()
