import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "routing_eval.py"
GOLDEN_PATH = ROOT / "tests" / "routing-eval-golden.json"


def load_module():
    spec = importlib.util.spec_from_file_location("routing_eval", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RoutingEvalHarnessTest(unittest.TestCase):
    def test_eval_assets_exist(self):
        self.assertTrue(SCRIPT_PATH.exists())
        self.assertTrue(GOLDEN_PATH.exists())

    def test_golden_queries_cover_global_and_existing_routes(self):
        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        actions = {row["expected_action"] for row in golden}
        self.assertIn("global_social_search", actions)
        self.assertIn("developer_signal_search", actions)
        self.assertIn("global_media_search", actions)
        self.assertIn("global_signal_brief", actions)
        self.assertIn("get_event_board", actions)
        self.assertIn("social_search", actions)

    def test_extract_action_parses_json_output(self):
        module = load_module()
        self.assertEqual(
            module.extract_action('{"action":"global_social_search"}'),
            "global_social_search",
        )
        self.assertEqual(
            module.extract_action("```json\n{\"action\":\"social_search\"}\n```"),
            "social_search",
        )

    def test_evaluate_cases_reports_match_and_mismatch(self):
        module = load_module()
        cases = [
            {"query": "How does Reddit feel about Claude Code?", "expected_action": "global_social_search"},
            {"query": "What's trending on Weibo today?", "expected_action": "get_event_board"},
        ]

        outputs = {
            "How does Reddit feel about Claude Code?": '{"action":"global_social_search"}',
            "What's trending on Weibo today?": '{"action":"search_events"}',
        }

        def infer(query: str) -> str:
            return outputs[query]

        results = module.evaluate_cases(cases, infer)
        self.assertTrue(results[0]["passed"])
        self.assertFalse(results[1]["passed"])
        self.assertEqual(results[1]["predicted_action"], "search_events")


if __name__ == "__main__":
    unittest.main()
