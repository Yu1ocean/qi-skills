#!/usr/bin/env python3
"""Grant Drive asset access via AIME lark-cli (v7.6).

History:
- v7.0: called Drive Permission API directly with `AIME_USER_CLOUD_JWT` (broken, 99991668).
- v7.3: delegated to `ensure_doc_in_personal.py` -> `inner_skills/lark/mcp_lark_move_lark_doc.py`.
        That MCP script has since been REMOVED from the runtime, so this path raised
        FileNotFoundError and callers silently degraded to a WARNING => fake success.
- v7.6: rewritten on top of the AIME-customised `lark-cli` (auth injected by runtime):
        * `lark-cli drive +member-add`  -> grant
        * `lark-cli drive +member-list` -> RAW read-after-write assertion
        * `lark-cli drive metas batch_query` -> owner short-circuit (owner already has
          implicit full_access; Feishu rejects re-adding the owner with code 1063003)

Contract (unchanged CLI signature, backwards compatible):
    python3 grant_doc_permissions.py <url> [--email <email>] [--perm full_access]

Guardrails:
- L3 runtime assertion: after granting, the target identity MUST appear as owner or as a
  collaborator whose perm == the requested perm. Otherwise -> raise (NO silent WARNING).
- Idempotent: pre-flight member-list / owner check; if already satisfied -> PASS without write.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_EMAIL = "yuqinan@bytedance.com"
DEFAULT_PERM = "full_access"
SUPPORTED_SEGMENTS = ("/docx/", "/docs/", "/doc/", "/sheets/", "/base/", "/wiki/", "/file/")
PERM_RANK = {"view": 1, "edit": 2, "full_access": 3}
READ_AFTER_WRITE_WAIT_SECONDS = 2

# Feishu error codes that mean "the grant is already effectively in place"
IDEMPOTENT_ERROR_CODES = {1063003}


# -----------------------------
# L3 validators
# -----------------------------

def validate_document_url(document_url: str) -> str:
    value = (document_url or "").strip()
    if not value:
        raise ValueError("document_url is required")
    if not value.startswith(("http://", "https://")):
        raise ValueError(f"document_url must be a full URL, got: {document_url!r}")
    if not any(segment in value for segment in SUPPORTED_SEGMENTS):
        raise ValueError(
            "Unsupported document_url. Expected one of /docx/, /docs/, /doc/, /sheets/, /base/, /wiki/, /file/."
        )
    return value


def validate_email(email: str) -> str:
    value = (email or "").strip()
    if "@" not in value:
        raise ValueError(f"--email must be a valid email address, got: {email!r}")
    return value


def validate_perm(perm: str) -> str:
    value = (perm or "").strip().lower()
    if value not in PERM_RANK:
        raise ValueError(f"--perm must be one of {sorted(PERM_RANK)}, got: {perm!r}")
    return value


# -----------------------------
# lark-cli plumbing
# -----------------------------

def run_lark_cli(args: List[str], action: str, allow_failure: bool = False) -> Dict[str, Any]:
    command = ["lark-cli", *args, "--format", "json"]
    result = subprocess.run(command, capture_output=True, text=True)
    payload = _extract_json(result.stdout) or _extract_json(result.stderr)
    if payload is None:
        if allow_failure:
            return {"ok": False, "error": {"message": (result.stderr or result.stdout).strip()}}
        raise RuntimeError(
            f"{action} failed: could not parse lark-cli JSON output\n"
            f"CMD: {' '.join(command)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    if not payload.get("ok") and not allow_failure:
        raise RuntimeError(f"{action} failed: {json.dumps(payload.get('error'), ensure_ascii=False)}")
    return payload


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
    return None


# -----------------------------
# Domain helpers
# -----------------------------

def resolve_open_id(email: str) -> Optional[str]:
    payload = run_lark_cli(
        ["contact", "+search-user", "--query", email, "--as", "user"],
        f"resolve open_id for {email}",
        allow_failure=True,
    )
    for user in (payload.get("data") or {}).get("users") or []:
        for key in ("email", "enterprise_email"):
            if (user.get(key) or "").strip().lower() == email.lower():
                return user.get("open_id")
    return None


def inspect_target(document_url: str) -> Tuple[str, str]:
    payload = run_lark_cli(["drive", "+inspect", "--url", document_url], "inspect drive target")
    data = payload.get("data") or {}
    token, doc_type = data.get("token"), data.get("type")
    if not token or not doc_type:
        raise RuntimeError(f"drive +inspect returned no token/type: {json.dumps(data, ensure_ascii=False)}")
    return token, doc_type


def get_owner_open_id(token: str, doc_type: str) -> Optional[str]:
    payload = run_lark_cli(
        [
            "drive", "metas", "batch_query",
            "--data", json.dumps({"request_docs": [{"doc_token": token, "doc_type": doc_type}]}),
            "--as", "user",
        ],
        "query drive meta (owner)",
        allow_failure=True,
    )
    metas = (payload.get("data") or {}).get("metas") or []
    return metas[0].get("owner_id") if metas else None


def list_members(document_url: str) -> List[Dict[str, Any]]:
    payload = run_lark_cli(
        ["drive", "+member-list", "--token", document_url, "--as", "user", "--fields", "*"],
        "list drive members",
    )
    return (payload.get("data") or {}).get("items") or []


def find_member(members: List[Dict[str, Any]], open_id: Optional[str], email: str) -> Optional[Dict[str, Any]]:
    needles = {n for n in (open_id, email) if n}
    for item in members:
        if str(item.get("member_id") or "") in needles:
            return item
    return None


def perm_satisfies(actual: str, expected: str) -> bool:
    return PERM_RANK.get((actual or "").lower(), 0) >= PERM_RANK[expected]


# -----------------------------
# Core flow
# -----------------------------

def assert_access(document_url: str, email: str, open_id: Optional[str], perm: str,
                  token: str, doc_type: str, phase: str) -> Optional[Dict[str, Any]]:
    """RAW read-after-write assertion. Returns evidence dict when satisfied, else None."""
    owner_id = get_owner_open_id(token, doc_type)
    if open_id and owner_id and owner_id == open_id:
        evidence = {"source": "owner", "member_id": owner_id, "perm": "full_access (implicit owner)"}
        print(f"[{phase}] RAW readback evidence: {json.dumps(evidence, ensure_ascii=False)}")
        return evidence if perm_satisfies("full_access", perm) else None

    members = list_members(document_url)
    print(f"[{phase}] RAW member-list ({len(members)} item(s)):")
    print(json.dumps(members, ensure_ascii=False, indent=2))
    hit = find_member(members, open_id, email)
    if hit and perm_satisfies(hit.get("perm", ""), perm):
        return {"source": "member-list", "member_id": hit.get("member_id"),
                "name": hit.get("name"), "perm": hit.get("perm")}
    return None


def grant(document_url: str, email: str, perm: str) -> int:
    token, doc_type = inspect_target(document_url)
    open_id = resolve_open_id(email)
    print(f"🎯 target={doc_type}:{token}  email={email}  open_id={open_id}  perm={perm}")

    pre = assert_access(document_url, email, open_id, perm, token, doc_type, "pre-flight")
    if pre:
        print(f"✅ PASS (idempotent, no write needed): {json.dumps(pre, ensure_ascii=False)}")
        return 0

    add = run_lark_cli(
        ["drive", "+member-add", "--token", document_url, "--member-type", "email",
         "--member-id", email, "--perm", perm, "--as", "user", "--yes"],
        "add drive member",
        allow_failure=True,
    )
    if not add.get("ok"):
        code = ((add.get("error") or {}).get("code"))
        if code not in IDEMPOTENT_ERROR_CODES:
            raise RuntimeError(f"drive +member-add failed: {json.dumps(add.get('error'), ensure_ascii=False)}")
        print(f"ℹ️  member-add returned idempotent code {code}; falling through to RAW verification.")

    time.sleep(READ_AFTER_WRITE_WAIT_SECONDS)
    post = assert_access(document_url, email, open_id, perm, token, doc_type, "post-write")
    if not post:
        raise RuntimeError(
            f"L3 ASSERTION FAILED: {email} does not hold perm>={perm} on {document_url} after member-add. "
            "Refusing to report success (anti-fake-success guardrail)."
        )
    print(f"✅ PASS: {json.dumps(post, ensure_ascii=False)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Grant Drive asset access via lark-cli drive +member-add, with member-list RAW assertion."
    )
    parser.add_argument("document_url", help="Doc/file URL, e.g. https://<host>/file/<token>")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help=f"Target user email. Default: {DEFAULT_EMAIL}")
    parser.add_argument("--perm", default=DEFAULT_PERM, choices=["view", "edit", "full_access"],
                        help="Permission role. Default: full_access")
    args = parser.parse_args()

    try:
        return grant(validate_document_url(args.document_url),
                     validate_email(args.email),
                     validate_perm(args.perm))
    except Exception as exc:
        print(f"❌ FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
