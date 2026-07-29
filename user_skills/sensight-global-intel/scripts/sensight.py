#!/usr/bin/env python3
# Sensight Skill — single-entry script
#
# Usage:
#   python3 scripts/sensight.py <action> [options]
#   python3 scripts/sensight.py --help
#
# Notes:
#   This script only exposes native Sensight actions.
#   The global-layer extensions global_social_search / developer_signal_search /
#   global_media_search / global_signal_brief are skill-layer mixed-routing
#   concepts defined in SKILL.md and references/global-routing.md. They are not
#   native commands in this script.
#
# Examples:
#   python3 scripts/sensight.py get_event_board --ranking_id 4081
#   python3 scripts/sensight.py search_events --query "AI trends"
#   python3 scripts/sensight.py daily_paper --date 2026-03-17
#   python3 scripts/sensight.py social_search --query "Spring Festival movie reviews" --platforms 3 2
#   python3 scripts/sensight.py retrieve_summarize --query "AI agent progress" --size 20
#   python3 scripts/sensight.py search_author_posts --platform 3 --author_name "CCTV News"

import argparse
import json
import sys
import uuid
import http.client
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SKILL_VERSION = "0.4.0"
CLIENT_ID_FILE = Path.home() / ".sensight" / ".sensight_client_id"

BASE_LLMLINK = "https://llmlink.bytedance.net"
BASE_POSTLINK = "https://sensight.bytedance.net"
BASE_SENSIGHT = "https://sensight.bytedance.net/api/dashboard/api/v1"


# ---------------------------------------------------------------------------
# Client ID
# ---------------------------------------------------------------------------

def get_client_id() -> str:
    if CLIENT_ID_FILE.exists():
        return CLIENT_ID_FILE.read_text().strip()
    CLIENT_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    new_id = str(uuid.uuid4())
    CLIENT_ID_FILE.write_text(new_id)
    print(f"⚙️  Generated a new Client ID: {new_id}", file=sys.stderr)
    return new_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def calc_time(date_str: str) -> dict:
    """Convert YYYY-MM-DD into the time formats used by Sensight interfaces."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    start_unix = int(dt.replace(hour=0, minute=0, second=0).timestamp())
    end_unix = start_unix + 86399
    return {
        "start_ms": start_unix * 1000,
        "end_ms": end_unix * 1000,
        "start_unix": start_unix,
        "end_unix": end_unix,
        "start_fmt": f"{date_str} 00:00:00",
        "end_fmt": f"{date_str} 23:59:59",
    }


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def build_headers(action: str, ppe: bool = False) -> dict:
    client_id = get_client_id()
    headers = {
        "Content-Type": "application/json",
        "x-skill-version": SKILL_VERSION,
        "x-skill-action": action,
        "x-skill-client-id": client_id,
    }
    if ppe:
        headers["x-use-ppe"] = "1"
        headers["x-tt-env"] = "ppe_pantianrun"

    return headers


def post(url: str, payload: dict, action: str, ppe: bool = False, timeout: int = 30) -> dict:
    headers = build_headers(action, ppe=ppe)
    body = json.dumps(payload, ensure_ascii=False).encode()
    req = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                print(f"Failed to parse JSON. Raw response preview:\n{raw[:500]}", file=sys.stderr)
                print("Suggestion: rerun `bash scripts/init.sh` to confirm the Client ID is valid", file=sys.stderr)
                sys.exit(1)
    except HTTPError as exc:
        if exc.code == 401:
            try:
                print(exc.read().decode())
            except http.client.IncompleteRead as incomplete:
                print(incomplete.partial.decode())
            sys.exit(1)

        print(f"HTTP error {exc.code}: {exc.reason}", file=sys.stderr)
        if exc.code == 403:
            print(
                "Suggestion: check whether ~/.sensight/.sensight_client_id exists, or rerun `bash scripts/init.sh`.",
                file=sys.stderr,
            )
        elif exc.code >= 500:
            print(
                "Suggestion: the server appears busy. Retry later, or fall back to search_events for broader coverage.",
                file=sys.stderr,
            )
        sys.exit(1)
    except TimeoutError:
        print(f"Request timed out (>{timeout}s)", file=sys.stderr)
        if action in ("retrieve", "summarize"):
            print(
                "Suggestion: the service is busy. Retry later, or use search_events as a broader fallback.",
                file=sys.stderr,
            )
        sys.exit(1)
    except URLError as exc:
        print(f"Network error: {exc.reason}", file=sys.stderr)
        sys.exit(1)


def print_json(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------

def cmd_get_event_board(args):
    payload = {"ranking_id": args.ranking_id}
    if args.end_time:
        payload["end_time"] = args.end_time
    result = post(f"{BASE_LLMLINK}/trendflow/tool/get_event_board", payload, "get_event_board")
    print_json(result)


def cmd_search_events(args):
    payload = {"query": args.query}
    result = post(f"{BASE_LLMLINK}/trendflow/tool/search_event", payload, "search_events")
    print_json(result)


def cmd_retrieve(args):
    payload = {
        "query": args.query,
        "enhance_query": args.enhance_query or args.query,
        "size": args.size,
        "semantic_rule": {"content_categories": [args.category]},
        "biz_info": {"name": "owls", "type": 0},
    }
    if args.start_time:
        payload["start_time"] = args.start_time
    if args.end_time:
        payload["end_time"] = args.end_time
    print("📥 Retrieving articles (estimated 1-3 minutes)...", file=sys.stderr)
    result = post(
        f"{BASE_LLMLINK}/info_engine/retrieval_high_quality_posts",
        payload,
        "retrieve",
        ppe=True,
        timeout=300,
    )
    print_json(result)


def cmd_summarize(args):
    if args.posts_file == "-":
        posts = json.load(sys.stdin)
    else:
        with open(args.posts_file) as f:
            posts = json.load(f)
    payload = {
        "posts": posts,
        "enhance_query": args.enhance_query,
        "content_analysis": {"intent": args.intent or f"Understand recent developments related to {args.enhance_query}"},
        "result_form": args.result_form,
        "biz_info": {"name": "owls", "type": 0},
    }
    print("📝 Generating AI summary (estimated 1-3 minutes)...", file=sys.stderr)
    result = post(
        f"{BASE_LLMLINK}/info_engine/ai_guide_once",
        payload,
        "summarize",
        ppe=True,
        timeout=300,
    )
    print_json(result)


def cmd_retrieve_summarize(args):
    retrieve_payload = {
        "query": args.query,
        "enhance_query": args.enhance_query or args.query,
        "size": args.size,
        "semantic_rule": {"content_categories": [args.category]},
        "biz_info": {"name": "owls", "type": 0},
    }
    if args.start_time:
        retrieve_payload["start_time"] = args.start_time
    if args.end_time:
        retrieve_payload["end_time"] = args.end_time

    print(f"📥 Step 1: retrieving articles (query: {args.query})...", file=sys.stderr)
    retrieve_result = post(
        f"{BASE_LLMLINK}/info_engine/retrieval_high_quality_posts",
        retrieve_payload,
        "retrieve",
        ppe=True,
        timeout=300,
    )
    posts = retrieve_result.get("posts", [])
    if not posts:
        print("⚠️  Retrieval returned no articles. Try a broader time range or different keywords.", file=sys.stderr)
        sys.exit(1)
    print(f"✅ Retrieved {len(posts)} articles", file=sys.stderr)

    summarize_payload = {
        "posts": posts,
        "enhance_query": args.enhance_query or args.query,
        "content_analysis": {"intent": args.intent or f"Understand recent developments related to {args.query}"},
        "result_form": args.result_form,
        "biz_info": {"name": "owls", "type": 0},
    }
    print(f"📝 Step 2: generating AI summary (result_form: {args.result_form})...", file=sys.stderr)
    summarize_result = post(
        f"{BASE_LLMLINK}/info_engine/ai_guide_once",
        summarize_payload,
        "summarize",
        ppe=True,
        timeout=300,
    )
    print_json(summarize_result)
    print("\n✅ Done", file=sys.stderr)


def cmd_daily_social(args):
    payload = {
        "task_id": 1,
        "date": args.date or today_str(),
        "source_types": args.source_types or [],
        "authors": args.authors or [],
        "institutions": args.institutions or [],
    }
    result = post(f"{BASE_SENSIGHT}/GetResults", payload, "daily_social")
    print_json(result)


def cmd_daily_paper(args):
    date = args.date or today_str()
    t = calc_time(date)
    payload = {"task_id": 1, "start_time": t["start_ms"], "end_time": t["end_ms"]}
    result = post(f"{BASE_SENSIGHT}/ListPapers", payload, "daily_paper")
    print_json(result)


def cmd_daily_blog(args):
    date = args.date or today_str()
    t = calc_time(date)
    payload = {"task_id": 1, "start_time": t["start_ms"], "end_time": t["end_ms"]}
    result = post(f"{BASE_SENSIGHT}/ListBlogs", payload, "daily_blog")
    print_json(result)


def cmd_weekly_model(args):
    result = post(f"{BASE_SENSIGHT}/GetWeeklyFeatured", {}, "weekly_model")
    print_json(result)


def cmd_model_sentiment(args):
    payload = {}
    if args.limit:
        payload["limit"] = args.limit
    result = post(f"{BASE_SENSIGHT}/GetModelSentiment", payload, "model_sentiment")
    print_json(result)


def cmd_social_search(args):
    payload = {"query": args.query}
    if args.platforms:
        payload["platforms"] = args.platforms
    if args.size:
        payload["size"] = args.size
    if args.start_time:
        payload["start_time"] = args.start_time
    if args.end_time:
        payload["end_time"] = args.end_time
    result = post(
        f"{BASE_POSTLINK}/sensight/sensight_social_search",
        payload,
        "social_search",
        ppe=True,
    )
    print_json(result)


def cmd_search_author_posts(args):
    payload = {"platform": args.platform}
    if args.author_name:
        payload["author_name"] = args.author_name
    if args.mp_uid:
        payload["mp_uid"] = args.mp_uid
    if args.start_time:
        payload["start_time"] = args.start_time
    if args.end_time:
        payload["end_time"] = args.end_time
    if args.size:
        payload["size"] = args.size
    if args.page_number is not None:
        payload["page_number"] = args.page_number
    result = post(
        f"{BASE_POSTLINK}/sensight/sensight_search_author_posts",
        payload,
        "search_author_posts",
        ppe=True,
    )
    print_json(result)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="sensight.py",
        description="Sensight Skill — CLI entry point for native Sensight actions",
        epilog=(
            "Note: global_social_search, developer_signal_search, global_media_search, "
            "and global_signal_brief are skill-layer mixed-routing concepts, not CLI commands in this script."
        ),
    )
    sub = parser.add_subparsers(dest="action", metavar="<action>", required=True)

    p = sub.add_parser("get_event_board", help="Trend board snapshot [fast ~1s]")
    p.add_argument(
        "--ranking_id",
        required=True,
        help="Ranking ID: 12549=Weibo Hot Search 2392=Weibo Rising 4071=Toutiao 4081=Douyin 4658=Twitter 182392=Xiaohongshu 24847=Baidu",
    )
    p.add_argument("--end_time", type=int, help="Unix timestamp; returns the latest snapshot before this time")
    p.set_defaults(func=cmd_get_event_board)

    p = sub.add_parser("search_events", help="Hot-event search [medium ~5-10s]")
    p.add_argument("--query", required=True, help="Search text; supports keywords, events, topics, and composite conditions")
    p.set_defaults(func=cmd_search_events)

    p = sub.add_parser("retrieve", help="Article retrieval (AI / tech only) [slow 1-3 min]")
    p.add_argument("--query", required=True, help="Search query")
    p.add_argument("--enhance_query", help="Expanded query intent to improve retrieval quality")
    p.add_argument("--size", type=int, default=10, help="Number of results to return (recommended 10-30; default 10)")
    p.add_argument(
        "--category",
        default="comprehensive",
        choices=["comprehensive", "academic_paper", "personal_opinion", "daily_weekly_report"],
        help="Content category (default: comprehensive)",
    )
    p.add_argument("--start_time", help='Start time in the format "YYYY-MM-DD HH:MM:SS"')
    p.add_argument("--end_time", help='End time in the format "YYYY-MM-DD HH:MM:SS"')
    p.set_defaults(func=cmd_retrieve)

    p = sub.add_parser("summarize", help="AI summary from retrieved posts [slow 1-3 min]")
    p.add_argument("--posts_file", required=True, help="Path to the retrieved posts JSON file, or - to read from stdin")
    p.add_argument("--enhance_query", required=True, help="Summary focus")
    p.add_argument("--intent", help="User analysis intent (defaults to automatic generation)")
    p.add_argument(
        "--result_form",
        default="news_brief",
        choices=["news_brief", "article_summary"],
        help="Summary format (default: news_brief)",
    )
    p.set_defaults(func=cmd_summarize)

    p = sub.add_parser("retrieve_summarize", help="Retrieve + summarize workflow [slow 1-3 min]")
    p.add_argument("--query", required=True, help="Search query")
    p.add_argument("--enhance_query", help="Expanded query intent (defaults to the original query)")
    p.add_argument("--size", type=int, default=10, help="Retrieval size (default: 10)")
    p.add_argument(
        "--category",
        default="comprehensive",
        choices=["comprehensive", "academic_paper", "personal_opinion", "daily_weekly_report"],
        help="Content category (default: comprehensive)",
    )
    p.add_argument("--start_time", help='Start time in the format "YYYY-MM-DD HH:MM:SS"')
    p.add_argument("--end_time", help='End time in the format "YYYY-MM-DD HH:MM:SS"')
    p.add_argument("--intent", help="User analysis intent (defaults to automatic generation)")
    p.add_argument(
        "--result_form",
        default="news_brief",
        choices=["news_brief", "article_summary"],
        help="Summary format (default: news_brief)",
    )
    p.set_defaults(func=cmd_retrieve_summarize)

    p = sub.add_parser("daily_social", help="Daily AI social brief [fast ~1s]")
    p.add_argument("--date", help="Date in YYYY-MM-DD format (defaults to today)")
    p.add_argument("--source_types", nargs="*", help="Filter by source type")
    p.add_argument("--authors", nargs="*", help="Filter by author name")
    p.add_argument("--institutions", nargs="*", help="Filter by institution")
    p.set_defaults(func=cmd_daily_social)

    p = sub.add_parser("daily_paper", help="Daily AI paper brief [fast ~1s]")
    p.add_argument("--date", help="Date in YYYY-MM-DD format (defaults to today)")
    p.set_defaults(func=cmd_daily_paper)

    p = sub.add_parser("daily_blog", help="Daily AI blog brief [fast ~1s]")
    p.add_argument("--date", help="Date in YYYY-MM-DD format (defaults to today)")
    p.set_defaults(func=cmd_daily_blog)

    p = sub.add_parser("weekly_model", help="Weekly featured models [fast ~1s]")
    p.set_defaults(func=cmd_weekly_model)

    p = sub.add_parser("model_sentiment", help="Model sentiment summary [fast ~1s]")
    p.add_argument("--limit", type=int, default=20, help="Number of items to return (default: 20)")
    p.set_defaults(func=cmd_model_sentiment)

    p = sub.add_parser("social_search", help="Semantic social search (latest 2 days) [fast ~1s]")
    p.add_argument("--query", required=True, help="Natural-language semantic query")
    p.add_argument(
        "--platforms",
        nargs="*",
        type=int,
        help="Platform filter (multiple allowed): 1=X/Twitter 2=Xiaohongshu 3=Weibo 4=WeChat Official Accounts; omit for all platforms",
    )
    p.add_argument("--size", type=int, help="Number of items to return (default 20, max 20)")
    p.add_argument("--start_time", type=int, help="Start time as Unix seconds (cannot be older than 2 days)")
    p.add_argument("--end_time", type=int, help="End time as Unix seconds (defaults to now)")
    p.set_defaults(func=cmd_social_search)

    p = sub.add_parser("search_author_posts", help="Recent posts from a specific author [fast ~1s]")
    p.add_argument("--platform", required=True, type=int, help="Platform ID: 1=X/Twitter 2=Xiaohongshu 3=Weibo 4=WeChat Official Accounts")
    p.add_argument("--author_name", help="Author name (must provide this or --mp_uid)")
    p.add_argument("--mp_uid", help="Unique author identifier (takes precedence over author_name)")
    p.add_argument("--start_time", type=int, help="Start time as Unix seconds (defaults to about the last week)")
    p.add_argument("--end_time", type=int, help="End time as Unix seconds (defaults to now)")
    p.add_argument("--size", type=int, help="Number of items to return (omit unless the user asks for a limit)")
    p.add_argument("--page_number", type=int, default=1, help="Page number starting from 1 (default: 1)")
    p.set_defaults(func=cmd_search_author_posts)

    args = parser.parse_args()

    if args.action == "search_author_posts":
        if not args.author_name and not args.mp_uid:
            parser.error("search_author_posts requires at least one of --author_name or --mp_uid")

    args.func(args)


if __name__ == "__main__":
    main()
