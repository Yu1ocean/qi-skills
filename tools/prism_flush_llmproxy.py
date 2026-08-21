#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""A fallback implementation of `aime prism flush` that avoids the /trace/* permission wall.

Why this exists
- `aime prism flush` in this environment sends LLM requests to:
    https://aime.bytedance.net/api/agents/v2/trace/<model>/chat/completions
  which currently returns: 403 code 4011 (no permission).
- The OpenAI-compatible LLM proxy endpoint works:
    https://aime.bytedance.net/api/agents/v2/llmproxy/user/chat/completions

This script:
1) Fetches the user's sessions via the same AIME API used by `aime prism flush`.
2) Calls llmproxy/user to generate USER.md and/or MEMORY.md.
3) Outputs plain text or JSON in the same shape described in `aime prism flush -o json`.

NOTE
- This script does NOT write to USER.md / MEMORY.md on disk by default. It prints to stdout.
  (So your existing downstream merge/sync logic can stay in control.)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import textwrap
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_AIME_BASE_URL = "https://aime.bytedance.net"
DEFAULT_LLM_PROXY_BASE_URL = "https://aime.bytedance.net/api/agents/v2/llmproxy/user"

# Keep consistent with the documented implementation notes.
# Keep the LLM input bounded. Feeding every historical session can exceed the
# effective context window of llmproxy/user models and make the model ignore the
# authoritative MEMORY.md/USER.md baseline. Recent sessions are sorted first, so
# this acts as a delta-oriented memory update window.
DEFAULT_CHAR_LIMIT = 120_000
DEFAULT_SESSION_TRIM = 4_000
DEFAULT_PAGE_SIZE = 100


@dataclass
class Session:
    session_id: str
    title: str
    messages_summary: str
    conclusion: str
    created_at_ms: int
    last_message_at_ms: int
    status: str
    artifact_links: List[str]


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def _env(name: str, required: bool = False) -> str:
    v = os.environ.get(name, "")
    if required and not v:
        raise SystemExit(f"Missing required env var: {name}")
    return v


def http_json(
    method: str,
    url: str,
    headers: Dict[str, str],
    body_obj: Optional[Dict[str, Any]] = None,
    timeout_sec: int = 60,
) -> Dict[str, Any]:
    data: Optional[bytes] = None
    if body_obj is not None:
        data = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url=url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read()
            # Most AIME APIs return JSON without compression; llmproxy may.
            # urllib handles gzip automatically only when using http.client, so keep simple here.
            # If gzip ever appears, users can switch to requests.
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                # best-effort
                return json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        msg = raw.decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {method} {url}: {msg}") from None


def fetch_sessions_with_summaries(
    aime_base_url: str,
    space_id: str,
    jwt: str,
) -> Tuple[List[Session], int]:
    sessions: List[Session] = []

    offset = 0
    total: Optional[int] = None

    while True:
        qs = urllib.parse.urlencode(
            {
                "limit": str(DEFAULT_PAGE_SIZE),
                "offset": str(offset),
                "space_id": space_id,
            }
        )
        url = f"{aime_base_url}/api/agents/v2/sessions_with_summaries?{qs}"

        payload = http_json(
            "GET",
            url,
            headers={
                "Authorization": f"Byte-Cloud-JWT {jwt}",
                "Content-Type": "application/json",
            },
            body_obj=None,
            timeout_sec=60,
        )

        if total is None:
            total = int(payload.get("total", 0) or 0)

        page = payload.get("sessions") or []
        if not page:
            break

        for s in page:
            sessions.append(
                Session(
                    session_id=str(s.get("session_id", "")),
                    title=str(s.get("title", "")),
                    messages_summary=str(s.get("messages_summary", "")),
                    conclusion=str(s.get("conclusion", "")),
                    created_at_ms=int(s.get("created_at", 0) or 0),
                    last_message_at_ms=int(s.get("last_message_at", 0) or 0),
                    status=str(s.get("status", "")),
                    artifact_links=list(s.get("artifact_links") or []),
                )
            )

        offset += len(page)
        eprint(f"ℹ️  Fetched {min(offset, total)}/{total} sessions...")

        if len(page) < DEFAULT_PAGE_SIZE:
            break
        if total is not None and offset >= total:
            break

    return sessions, int(total or len(sessions))


def ms_to_local_time_str(ms: int) -> str:
    if not ms:
        return ""
    # Keep local timezone formatting simple.
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ms / 1000))


def format_sessions_for_llm(sessions: List[Session]) -> Tuple[str, int, int]:
    # Follow the same idea as AIME CLI:
    # - sort by time desc
    # - each session keeps up to 4000 chars
    # - total within 800k chars
    sessions_sorted = sorted(sessions, key=lambda s: s.last_message_at_ms, reverse=True)

    blocks: List[str] = []
    included = 0
    total_chars = 0

    for s in sessions_sorted:
        block = textwrap.dedent(
            f"""
            ---
            session_id: {s.session_id}
            title: {s.title}
            status: {s.status}
            created_at: {ms_to_local_time_str(s.created_at_ms)}
            last_message_at: {ms_to_local_time_str(s.last_message_at_ms)}
            artifact_links: {', '.join(s.artifact_links) if s.artifact_links else ''}

            messages_summary:
            {s.messages_summary.strip()}

            conclusion:
            {s.conclusion.strip()}
            """
        ).strip()

        if len(block) > DEFAULT_SESSION_TRIM:
            block = block[: DEFAULT_SESSION_TRIM] + "\n…(truncated)"

        if total_chars + len(block) > DEFAULT_CHAR_LIMIT:
            break

        blocks.append(block)
        total_chars += len(block)
        included += 1

    content = "\n\n".join(blocks)
    return content, included, total_chars


def llm_chat_completion(
    llm_base_url: str,
    jwt: str,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: int,
    timeout_sec: int = 300,
) -> str:
    url = llm_base_url.rstrip("/") + "/chat/completions"

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        # IMPORTANT: llmproxy expects max_tokens (not max_output_tokens)
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }

    resp = http_json(
        "POST",
        url,
        headers={
            "Authorization": f"Bearer {jwt}",
            "Content-Type": "application/json",
        },
        body_obj=payload,
        timeout_sec=timeout_sec,
    )

    # llmproxy may return either OpenAI-ish chat.completion or response object.
    # Both have `choices[0].message.content` in this environment.
    try:
        choices = resp.get("choices") or []
        if not choices:
            raise KeyError("choices")
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if not isinstance(content, str) or not content.strip():
            raise KeyError("choices[0].message.content")
        return content
    except Exception:
        raise RuntimeError(f"Unexpected llm response shape: {json.dumps(resp, ensure_ascii=False)[:2000]}")


def read_existing_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def write_generated_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.rstrip() + "\n")


BACKUP_DIR = os.path.join("tools", "backups")


def snapshot_before_write(path: str) -> str:
    """Pre-write snapshot: copy the current file to tools/backups/<name>.bak.<ts>.

    Must be called BEFORE any merge/write logic so a rollback source always exists,
    even if the merge or regression guard misbehaves.
    """
    if not os.path.exists(path):
        eprint(f"⚠️  Skip backup, file not found: {path}")
        return ""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"{os.path.basename(path)}.bak.{ts}")
    shutil.copy2(path, dest)
    eprint(f"🛡️  Pre-write snapshot: {dest}")
    return dest


def git_pre_flush_commit() -> bool:
    """Commit a pre-flush snapshot of MEMORY.md / USER.md into git.

    Best-effort only: any failure (no repo, nothing to commit, git missing) is
    logged as a warning and MUST NOT block the flush pipeline.
    """
    import subprocess

    targets = [p for p in ("MEMORY.md", "USER.md") if os.path.exists(p)]
    if not targets:
        eprint("⚠️  git pre-flush snapshot skipped: no MEMORY.md/USER.md found")
        return False
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        add = subprocess.run(["git", "add", *targets], capture_output=True, text=True)
        if add.returncode != 0:
            eprint(f"⚠️  git add failed (non-blocking): {add.stderr.strip()}")
            return False
        commit = subprocess.run(
            ["git", "commit", "-m", f"chore(memory): pre-flush snapshot {ts}"],
            capture_output=True,
            text=True,
        )
        if commit.returncode != 0:
            eprint(
                "⚠️  git commit skipped/failed (non-blocking): "
                + (commit.stdout.strip() or commit.stderr.strip())
            )
            return False
        eprint(f"🔒 git pre-flush snapshot committed: {ts}")
        return True
    except Exception as exc:  # noqa: BLE001 - never block flush
        eprint(f"⚠️  git pre-flush snapshot error (non-blocking): {exc}")
        return False


def append_only_merge(existing: str, generated: str) -> str:
    """Preserve the existing file verbatim and append only genuinely new generated lines.

    The LLM is still asked to emit a full Markdown file for compatibility with
    `aime prism flush`, but disk writes must be append-only. If the model returns
    a faithful full-file merge, we keep it; otherwise we treat it as an increment
    candidate and append only lines that are not already present in the baseline.
    """
    if not existing.strip():
        return generated.rstrip() + "\n"
    if not generated.strip():
        return existing.rstrip() + "\n"

    existing_normalized = existing.rstrip()
    generated_normalized = generated.rstrip()
    if generated_normalized.startswith(existing_normalized):
        return generated_normalized + "\n"

    existing_lines = set(existing.splitlines())
    appended_lines = [line for line in generated.splitlines() if line.strip() and line not in existing_lines]
    if not appended_lines:
        return existing_normalized + "\n"

    return existing_normalized + "\n\n# Prism Flush 增量候选\n" + "\n".join(appended_lines).rstrip() + "\n"


def count_nonempty_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def assert_not_regressed(kind: str, generated: str, existing: str) -> None:
    """Refuse obviously regressed LLM output before it reaches downstream writers."""
    if not existing.strip() or not generated.strip():
        return

    existing_lines = count_nonempty_lines(existing)
    generated_lines = count_nonempty_lines(generated)
    threshold = 1.0 if kind in ("user", "memory") else 0.9
    if existing_lines and generated_lines < existing_lines * threshold:
        raise SystemExit(
            f"Regression guard triggered: generated {kind.upper()}.md has only "
            f"{generated_lines} non-empty lines; existing has {existing_lines}. "
            f"Refusing output because it is below the {threshold:.0%} append-only safety threshold."
        )

    marker_map = {
        "memory": [
            "skill-forge-pipeline-v4",
            "feishu-doc-writing-guide",
            "zero-trust",
            "ECQ0sDwmbhDex9tcUSjlkU7Bgdh",
            "decision-registry",
        ],
        "user": [
            "# 角色与背景",
            "# 偏好",
            "Global E‑Commerce",
            "POP-Fashion",
            "feishu-doc-writing-guide",
            "零信任质检",
            "skill-forge-pipeline-v4",
            "decision-registry",
            "SKM > HIPO",
            "手绘卡通风",
            "EP-CARD",
            "seller-focused L5",
            "代码层+指令层",
            "脱敏",
        ],
    }
    missing = [m for m in marker_map.get(kind, []) if m in existing and m not in generated]
    if missing:
        raise SystemExit(
            f"Regression guard triggered: generated {kind.upper()}.md lost existing markers: {missing}. "
            "Refusing output."
        )


def build_user_prompt(locale: str, sessions_text: str, existing_user: str = "") -> List[Dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是一个用户画像整理助手。请以现有 USER.md 为权威基准，只做增量合并与必要修订，禁止压缩。"
                f"Write in {locale}.\n\n"
                "硬规则：现有 USER.md 是当前权威版本；历史会话只作为增量候选。"
                "必须优先逐段保留现有 USER.md 的有效内容，在其基础上插入或更新新增事实；"
                "不得删除现有 USER.md 中仍然有效的角色背景、长期偏好、工具偏好、数据安全偏好和交互约定；"
                "如果历史会话与现有 USER.md 冲突，以现有 USER.md 为准；"
                "输出长度不得显著短于现有 USER.md，除非明确发现某条已失效且给不出保留价值。"
                "逐行检查现有 USER.md，默认保留原有行、原有标题结构和项目符号层级；"
                "只允许在确认有更准确新事实时更新对应行，或追加新增稳定偏好；"
                "禁止把完整 USER.md 重写成短摘要，禁止因为格式偏好而删除既有内容。"
                "输出必须是完整 Markdown 文件内容；不确定的内容不要臆测，宁可保持原文。"
            ),
        },
        {
            "role": "user",
            "content": (
                "以下是当前现有 USER.md（权威基准，必须保留仍然有效的信息）：\n\n"
                + existing_user
                + "\n\n以下是用户历史会话（已截断去重，仅作为增量候选）：\n\n"
                + sessions_text
                + "\n\n请输出增量合并后的 USER.md，不要全量重写成短版。"
            ),
        },
    ]


def build_memory_prompt(locale: str, sessions_text: str, existing_memory: str = "") -> List[Dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是一个长期记忆整理助手。请以现有 MEMORY.md 全文为唯一权威基准，只做追加式增量合并。"
                f"Write in {locale}.\n\n"
                "硬规则：现有 MEMORY.md 是当前权威版本；历史会话只作为增量候选。"
                "必须逐行保留现有 MEMORY.md 的每一行、原有标题结构和项目符号层级；"
                "禁止删除、改写、压缩、重排现有 MEMORY.md 中的任何已有行；"
                "只能在文件末尾或现有明确区块末尾追加新增稳定记忆；"
                "不得删除现有 MEMORY.md 中仍然有效的近期锚点、系统规则、技能仓库信息、决策记录和项目状态；"
                "如果历史会话与现有 MEMORY.md 冲突，以现有 MEMORY.md 为准；"
                "只把新 session 中更晚、更稳定、可复用的信息作为增量追加进去；"
                "输出长度不得短于现有 MEMORY.md，除非仅删除完全重复的新增候选。"
                "尤其不得删除日期日志标题、近期 Aime-Dreaming 锚点、技能仓库信息、固定平替链路和历史决策锚点；"
                "禁止把完整 MEMORY.md 重写成短摘要，禁止为了满足格式而压缩掉既有历史锚点。"
                "输出必须是完整 Markdown 文件内容，且应以当前 MEMORY.md 原文开头；"
                "内容要偏“事实/约定/偏好/触发器”，不要输出具体执行过程或一次性临时细节。"
            ),
        },
        {
            "role": "user",
            "content": (
                "以下是当前现有 MEMORY.md（权威基准，必须保留仍然有效的信息）：\n\n"
                + existing_memory
                + "\n\n以下是用户历史会话（已截断去重，仅作为增量候选）：\n\n"
                + sessions_text
                + "\n\n请输出追加式增量合并后的 MEMORY.md：必须以当前 MEMORY.md 原文逐字开头，只允许追加新增量，不要全量重写成短版。"
            ),
        },
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", default="all", choices=["all", "memory", "user"], help="Type to generate")
    ap.add_argument("-o", "--output", default="table", choices=["table", "json"], help="Output format")
    ap.add_argument("--locale", default="Chinese (Simplified)", help="Output language")
    ap.add_argument("--model", default="doubao-seed-2.0-lite-user", help="LLM model to use (llmproxy/user)")
    ap.add_argument("--max-tokens", type=int, default=12000, help="max_tokens for the LLM output")
    ap.add_argument("--write-files", action="store_true", help="write guarded generated content back to USER.md/MEMORY.md")

    args = ap.parse_args()

    jwt = _env("AIME_USER_CLOUD_JWT", required=True)
    space_id = _env("AIME_SPACE_ID", required=True)

    aime_base_url = _env("AIME_BASE_URL") or DEFAULT_AIME_BASE_URL
    llm_base_url = _env("OPENAI_BASE_URL") or DEFAULT_LLM_PROXY_BASE_URL

    eprint("ℹ️  Fetching sessions...")
    sessions, sessions_total = fetch_sessions_with_summaries(aime_base_url, space_id, jwt)

    sessions_text, sessions_included, input_chars = format_sessions_for_llm(sessions)
    if not sessions_text.strip():
        raise SystemExit("No session content to process")

    existing_memory = read_existing_file("MEMORY.md")
    existing_user = read_existing_file("USER.md")

    out: Dict[str, Any] = {
        "username": _env("AIME_CURRENT_USER") or "",
        "sessions_total": sessions_total,
        "sessions_included": sessions_included,
        "input_chars": input_chars,
        "memory_md": "",
        "user_md": "",
    }

    if args.type in ("all", "user"):
        eprint("ℹ️  Generating USER.md via llmproxy/user...")
        user_md = llm_chat_completion(
            llm_base_url=llm_base_url,
            jwt=jwt,
            model=args.model,
            messages=build_user_prompt(args.locale, sessions_text, existing_user),
            max_tokens=args.max_tokens,
        )
        assert_not_regressed("user", user_md, existing_user)
        out["user_md"] = user_md

    if args.type in ("all", "memory"):
        eprint("ℹ️  Generating MEMORY.md via llmproxy/user...")
        memory_md = llm_chat_completion(
            llm_base_url=llm_base_url,
            jwt=jwt,
            model=args.model,
            messages=build_memory_prompt(args.locale, sessions_text, existing_memory),
            max_tokens=args.max_tokens,
        )
        assert_not_regressed("memory", memory_md, existing_memory)
        out["memory_md"] = memory_md

    if args.write_files:
        # Pre-flush git snapshot (best-effort, never blocks the flush).
        git_pre_flush_commit()
        if out.get("user_md"):
            snapshot_before_write("USER.md")
            user_to_write = append_only_merge(existing_user, out["user_md"])
            assert_not_regressed("user", user_to_write, existing_user)
            write_generated_file("USER.md", user_to_write)
            eprint("✅ Wrote USER.md with append-only merge")
        if out.get("memory_md"):
            snapshot_before_write("MEMORY.md")
            memory_to_write = append_only_merge(existing_memory, out["memory_md"])
            assert_not_regressed("memory", memory_to_write, existing_memory)
            write_generated_file("MEMORY.md", memory_to_write)
            eprint("✅ Wrote MEMORY.md with append-only merge")

    if args.output == "json":
        # Mimic `aime prism flush -o json`: JSON object is the last thing on stdout.
        # (progress logs are in stderr)
        print(json.dumps(out, ensure_ascii=False))
        return

    # table/plain mode: print the markdown sections.
    if out.get("memory_md"):
        print(out["memory_md"].rstrip())
        print()
    if out.get("user_md"):
        print(out["user_md"].rstrip())


if __name__ == "__main__":
    main()
