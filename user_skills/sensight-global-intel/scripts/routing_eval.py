#!/usr/bin/env python3
"""LLM routing evaluation script.

Examples:
  python3 scripts/routing_eval.py --responses-file /tmp/routing_outputs.json
  OPENAI_API_KEY=... python3 scripts/routing_eval.py --provider openai --model gpt-5.4-mini

Notes:
  - This script evaluates whether a model routes a query to the correct action under a fixed prompt.
  - By default it uses tests/routing-eval-golden.json as the golden set.
  - You can replay recorded outputs with --responses-file or run live evaluation through the OpenAI API.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "tests" / "routing-eval-golden.json"
ALLOWED_ACTIONS = [
    "get_event_board",
    "search_events",
    "retrieve_summarize",
    "daily_social",
    "daily_paper",
    "daily_blog",
    "weekly_model",
    "model_sentiment",
    "social_search",
    "search_author_posts",
    "global_social_search",
    "developer_signal_search",
    "global_media_search",
    "global_signal_brief",
]

SYSTEM_PROMPT = """You are the Sensight routing evaluator.
Your task is not to answer the user's question. Your task is only to choose the single best action.

Constraints:
1. Choose exactly one action from the allowed list
2. Do not output explanatory natural language
3. Output strict JSON only: {"action":"<action_name>"}

Allowed actions:
{allowed_actions}
"""


def build_prompt(query: str) -> str:
    allowed_actions = ", ".join(ALLOWED_ACTIONS)
    return SYSTEM_PROMPT.format(allowed_actions=allowed_actions) + "\nQuery to route:\n" + query


def strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return text


def extract_action(raw_text: str) -> str | None:
    text = strip_code_fence(raw_text)

    try:
        payload = json.loads(text)
        action = payload.get("action")
        if action in ALLOWED_ACTIONS:
            return action
    except json.JSONDecodeError:
        pass

    match = re.search(r'"action"\s*:\s*"([^"]+)"', text)
    if match and match.group(1) in ALLOWED_ACTIONS:
        return match.group(1)

    bare = text.strip().strip("`")
    if bare in ALLOWED_ACTIONS:
        return bare
    return None


def evaluate_cases(cases: list[dict], infer_fn: Callable[[str], str]) -> list[dict]:
    results = []
    for case in cases:
        query = case["query"]
        expected_action = case["expected_action"]
        raw_output = infer_fn(query)
        predicted_action = extract_action(raw_output)
        results.append(
            {
                "query": query,
                "expected_action": expected_action,
                "predicted_action": predicted_action,
                "raw_output": raw_output,
                "passed": predicted_action == expected_action,
            }
        )
    return results


def load_cases(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_replay_outputs(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return {str(k): str(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return {str(row["query"]): str(row["output"]) for row in payload}
    raise ValueError("responses-file must be a dict or list structure")


def make_replay_infer(outputs: dict[str, str]) -> Callable[[str], str]:
    def infer(query: str) -> str:
        if query not in outputs:
            raise KeyError(f"responses-file is missing query: {query}")
        return outputs[query]

    return infer


def call_openai_chat_completions(api_key: str, model: str, query: str) -> str:
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": build_prompt("")},
            {"role": "user", "content": query},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "routing_decision",
                "schema": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ALLOWED_ACTIONS,
                        }
                    },
                    "required": ["action"],
                    "additionalProperties": False,
                },
            },
        },
    }
    req = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"OpenAI API network error: {exc.reason}") from exc

    return payload["choices"][0]["message"]["content"]


def print_summary(results: list[dict]) -> int:
    passed = 0
    for row in results:
        status = "PASS" if row["passed"] else "FAIL"
        predicted = row["predicted_action"] or "unparseable"
        print(f"[{status}] {row['query']}")
        print(f"  expected: {row['expected_action']}")
        print(f"  predicted: {predicted}")
        if not row["passed"]:
            print(f"  raw: {row['raw_output']}")
        if row["passed"]:
            passed += 1
    total = len(results)
    print(f"\nSummary: {passed}/{total} passed")
    return 0 if passed == total else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Sensight LLM routing evaluation")
    parser.add_argument(
        "--cases",
        default=str(DEFAULT_CASES),
        help="Path to the golden-set JSON file",
    )
    parser.add_argument(
        "--responses-file",
        help="Recorded model outputs in JSON for offline replay evaluation",
    )
    parser.add_argument(
        "--provider",
        choices=["openai"],
        help="Live-evaluation provider; currently supports openai",
    )
    parser.add_argument(
        "--model",
        help="Model name for live evaluation",
    )
    args = parser.parse_args()

    cases = load_cases(Path(args.cases))

    if args.responses_file:
        outputs = load_replay_outputs(Path(args.responses_file))
        infer_fn = make_replay_infer(outputs)
    elif args.provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise SystemExit("OPENAI_API_KEY must be set when using the openai provider")
        if not args.model:
            raise SystemExit("--model is required when using the openai provider")

        def infer_fn(query: str) -> str:
            return call_openai_chat_completions(api_key, args.model, query)

    else:
        raise SystemExit("Provide --responses-file, or use --provider openai --model ...")

    results = evaluate_cases(cases, infer_fn)
    return print_summary(results)


if __name__ == "__main__":
    sys.exit(main())
