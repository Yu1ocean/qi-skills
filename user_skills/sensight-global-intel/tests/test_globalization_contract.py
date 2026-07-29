import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_MD = (ROOT / "SKILL.md").read_text(encoding="utf-8")
ROUTING_GOLDEN = json.loads((ROOT / "tests" / "global-routing-golden.json").read_text(encoding="utf-8"))


def extract_query_action_map(markdown: str) -> dict[str, str]:
    mapping = {}
    in_table = False
    saw_rows = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line == "### Typical Query -> Action Mapping":
            in_table = True
            continue
        if not in_table:
            continue
        if not line:
            if saw_rows:
                break
            continue
        if not line.startswith("|"):
            continue
        if set(line.replace("|", "").strip()) <= {"-", " "}:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 2 or cells[0] == "Example query":
            continue
        mapping[cells[0].strip('"')] = cells[1].strip("`")
        saw_rows = True
    return mapping


class GlobalizationContractTest(unittest.TestCase):
    def test_skill_markdown_stays_within_recommended_length(self):
        self.assertLessEqual(len(SKILL_MD.splitlines()), 500)

    def test_skill_repositions_sensight_as_global_ai_tech_entry(self):
        self.assertIn("global AI / tech", SKILL_MD)
        self.assertIn("Chinese social platforms", SKILL_MD)
        self.assertIn("overseas social platforms", SKILL_MD)
        self.assertIn("developer communities", SKILL_MD)
        self.assertIn("tech media", SKILL_MD)

    def test_skill_declares_global_routing_actions(self):
        for action in (
            "global_social_search",
            "developer_signal_search",
            "global_media_search",
            "global_signal_brief",
        ):
            self.assertIn(action, SKILL_MD)

    def test_skill_allows_mixed_source_routing_beyond_sensight_script(self):
        self.assertIn("prefer Sensight", SKILL_MD)
        self.assertIn("web", SKILL_MD)
        self.assertIn("GitHub", SKILL_MD)
        self.assertIn("Reddit", SKILL_MD)

    def test_skill_defines_summary_then_grouped_output(self):
        self.assertIn("3-5 cross-source conclusions", SKILL_MD)
        self.assertIn("Social Signals", SKILL_MD)
        self.assertIn("Developer / Open-Source Signals", SKILL_MD)
        self.assertIn("Media and Official Releases", SKILL_MD)

    def test_skill_uses_conditional_source_attribution(self):
        self.assertIn(
            "AI industry highlights and social daily briefs are provided by Sensight; Reddit / GitHub / overseas media are supplemented from public web sources.",
            SKILL_MD,
        )
        self.assertNotIn(
            "All outputs should naturally end with 'The above data is provided by Sensight.'",
            SKILL_MD,
        )

    def test_skill_documents_overseas_compliance_boundary(self):
        self.assertIn("## Overseas Source Compliance Boundaries", SKILL_MD)
        self.assertIn("Only use public pages", SKILL_MD)
        self.assertIn("Do not reproduce full body text", SKILL_MD)
        self.assertIn("De-identify Reddit / GitHub usernames", SKILL_MD)
        self.assertIn("paywalls", SKILL_MD)
        self.assertIn("Discord / Slack", SKILL_MD)
        self.assertIn("Cross-border data transfer status", SKILL_MD)
        self.assertIn("currently declare that cross-border transfer review has been completed", SKILL_MD)

    def test_global_source_cases_exist(self):
        cases = (ROOT / "tests" / "test-cases-global-source.md").read_text(encoding="utf-8")
        self.assertIn("How does Reddit feel about Claude Code?", cases)
        self.assertIn("How is GitHub reacting to a new release in a project?", cases)
        self.assertIn("How is western tech media covering OpenAI's new model?", cases)
        self.assertIn("How is the global tech community reacting to MCP lately?", cases)

    def test_routing_golden_set_matches_query_action_table(self):
        documented_map = extract_query_action_map(SKILL_MD)
        self.assertGreaterEqual(len(ROUTING_GOLDEN), 8)
        for sample in ROUTING_GOLDEN:
            query = sample["query"]
            expected_action = sample["expected_action"]
            self.assertIn(query, documented_map)
            self.assertEqual(documented_map[query], expected_action, msg=query)

    def test_skill_defines_product_intel_fallback_workflow(self):
        self.assertIn("## Product / Competitive Intelligence Workflow", SKILL_MD)
        self.assertIn("If native Sensight retrieval returns nothing, do not stop there", SKILL_MD)
        self.assertIn("official pages / official docs / pricing pages", SKILL_MD)
        self.assertIn("developer forums", SKILL_MD)
        self.assertIn("third-party API aggregator blogs", SKILL_MD)


if __name__ == "__main__":
    unittest.main()
