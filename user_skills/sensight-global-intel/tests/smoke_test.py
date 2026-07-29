#!/usr/bin/env python3
"""
Sensight smoke-test script
Usage: python3 scripts/smoke_test.py [--verbose]

This script tests all fast interfaces (~1s) and skips slow ones
(`retrieve` / `summarize`, which usually take 1-3 minutes).
It prints each interface's status, item count, and a sample field, then
prints a pass / fail summary.
"""

import json
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SKILL_VERSION = "0.4.0"
CLIENT_ID_FILE = Path.home() / ".sensight" / ".sensight_client_id"
BASE_LLMLINK = "https://llmlink.bytedance.net"
BASE_SENSIGHT = "https://sensight.bytedance.net/api/dashboard/api/v1"

VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv

# ---------- Helpers ----------


def get_client_id() -> str:
    if CLIENT_ID_FILE.exists():
        return CLIENT_ID_FILE.read_text().strip()
    CLIENT_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    new_id = str(uuid.uuid4())
    CLIENT_ID_FILE.write_text(new_id)
    return new_id


def build_headers(action: str, ppe: bool = False) -> dict:
    headers = {
        "Content-Type": "application/json",
        "x-skill-version": SKILL_VERSION,
        "x-skill-action": action,
        "x-skill-client-id": get_client_id(),
    }
    if ppe:
        headers["x-use-ppe"] = "1"
        headers["x-tt-env"] = "ppe_sensight"
    return headers


def post(url: str, payload: dict, action: str, ppe: bool = False, timeout: int = 30):
    body = json.dumps(payload, ensure_ascii=False).encode()
    req = Request(url, data=body, headers=build_headers(action, ppe), method="POST")
    t0 = time.time()
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            elapsed = time.time() - t0
            return json.loads(raw), elapsed
    except (HTTPError, TimeoutError, URLError) as exc:
        return {"_error": str(exc)}, time.time() - t0


def ms_range(date_str: str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    start = int(dt.replace(hour=0, minute=0, second=0).timestamp()) * 1000
    end = start + 86399_000
    return start, end


def recent_date(days_ago: int = 1) -> str:
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


# ---------- Test cases ----------


def get_status(data: dict) -> tuple[bool, str]:
    """Support three response formats and return (is_ok, label)."""
    if "status" in data:
        ok = data["status"] == 0
        return ok, f"status={data['status']}"
    if "code" in data:
        ok = data["code"] == 0
        return ok, f"code={data['code']}"
    if "BaseResp" in data:
        code = data["BaseResp"].get("StatusCode", -1)
        ok = code == 0
        return ok, f"BaseResp.StatusCode={code}"
    return False, "unknown_format"


def extract_count(data: dict) -> str:
    """Extract item counts from different response layouts."""
    if "items" in data and isinstance(data["items"], list):
        return str(len(data["items"]))
    inner = data.get("data")
    if isinstance(inner, list):
        return str(len(inner))
    if isinstance(inner, dict):
        for key in ("data", "items", "posts", "topics", "featured_events", "comments", "results"):
            value = inner.get(key)
            if isinstance(value, list):
                return str(len(value))
        return f"(dict keys: {list(inner.keys())[:4]})"
    return "?"


def check(data: dict) -> tuple[bool, str]:
    """Return (passed, summary)."""
    if "_error" in data:
        return False, f"ERROR: {data['_error']}"
    ok, label = get_status(data)
    if not ok:
        return False, f"{label} msg={data.get('msg', data.get('BaseResp', {}).get('StatusMessage', '?'))}"
    return True, f"{label} count={extract_count(data)}"


CASES = []


def case(name, url, payload, action, ppe=False, sample_fn=None):
    CASES.append((name, url, payload, action, ppe, sample_fn))


case(
    "get_event_board [Douyin]",
    f"{BASE_LLMLINK}/trendflow/tool/get_event_board",
    {"ranking_id": 4081},
    "get_event_board",
    sample_fn=lambda data: data.get("data", [{}])[0].get("Title", "")[:20] if data.get("data") else "",
)

case(
    "get_event_board [Weibo]",
    f"{BASE_LLMLINK}/trendflow/tool/get_event_board",
    {"ranking_id": 12549},
    "get_event_board",
    sample_fn=lambda data: data.get("data", [{}])[0].get("Title", "")[:20] if data.get("data") else "",
)

case(
    "search_events",
    f"{BASE_LLMLINK}/trendflow/tool/search_event",
    {"query": "AI large models"},
    "search_events",
    sample_fn=lambda data: data.get("data", [{}])[0].get("title", "")[:20] if data.get("data") else "",
)

case(
    "daily_social",
    f"{BASE_SENSIGHT}/GetResults",
    {"task_id": 1, "date": recent_date(1), "source_types": [], "authors": [], "institutions": []},
    "daily_social",
)

_start_ms, _end_ms = ms_range(recent_date(1))
case(
    "daily_paper",
    f"{BASE_SENSIGHT}/ListPapers",
    {"task_id": 1, "start_time": _start_ms, "end_time": _end_ms},
    "daily_paper",
)

case(
    "daily_blog",
    f"{BASE_SENSIGHT}/ListBlogs",
    {"task_id": 1, "start_time": _start_ms, "end_time": _end_ms},
    "daily_blog",
)

case(
    "weekly_model",
    f"{BASE_SENSIGHT}/GetWeeklyFeatured",
    {},
    "weekly_model",
)

case(
    "model_sentiment",
    f"{BASE_SENSIGHT}/GetModelSentiment",
    {"limit": 5},
    "model_sentiment",
)

_now = int(datetime.now().timestamp())
_2d_ago = _now - 2 * 86400
case(
    "social_search",
    f"{BASE_LLMLINK}/info_engine/sensight_social_search",
    {"query": "DeepSeek", "size": 3, "start_time": _2d_ago, "end_time": _now},
    "social_search",
    ppe=True,
    sample_fn=lambda data: data["items"][0].get("content", "")[:20] if data.get("items") else "",
)

case(
    "search_author_posts [X]",
    f"{BASE_LLMLINK}/info_engine/sensight_search_author_posts",
    {"platform": 1, "author_name": "Yann LeCun", "size": 3},
    "search_author_posts",
    ppe=True,
    sample_fn=lambda data: data.get("selected_author_name", "")
    or (data.get("authors", [{}])[0].get("name", "") if data.get("authors") else ""),
)


# ---------- Execution ----------


def main():
    print(f"Sensight smoke test  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Client ID: {get_client_id()}")
    print("=" * 60)

    results = []
    for name, url, payload, action, ppe, sample_fn in CASES:
        print(f"  {name} ... ", end="", flush=True)
        data, elapsed = post(url, payload, action, ppe=ppe)
        ok, summary = check(data)
        sample = ""
        if ok and sample_fn:
            try:
                sample = sample_fn(data)
            except Exception:
                pass
        icon = "✅" if ok else "❌"
        detail = f"{summary}  [{elapsed:.1f}s]"
        if sample:
            detail += f'  eg. "{sample}"'
        print(f"{icon} {detail}")
        if VERBOSE and not ok:
            print(f"     response: {json.dumps(data, ensure_ascii=False)[:300]}")
        results.append((name, ok, elapsed))

    print("=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    avg_t = sum(t for _, _, t in results) / total if total else 0
    print(f"Result: {passed}/{total} passed  average latency {avg_t:.1f}s")
    if passed < total:
        print("Failed interfaces:")
        for name, ok, _ in results:
            if not ok:
                print(f"  - {name}")
        sys.exit(1)


if __name__ == "__main__":
    main()
