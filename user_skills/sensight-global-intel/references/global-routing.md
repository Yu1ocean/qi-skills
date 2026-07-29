# Global Mixed-Source Routing Reference

This document defines the V1 mixed-source routing strategy for `sensight`. The goal is not to replace native Sensight capabilities, but to use Sensight as the core entry point for global AI / tech intelligence while filling coverage gaps for `Reddit`, `GitHub`, and western tech media.

## Routing Principles

1. **Prefer native Sensight first**
   For trend lists, Chinese social platforms, `X/Twitter`, AI blogs, papers, and model launches, start with `python3 scripts/sensight.py`.
2. **Only add external sources when there is a coverage gap**
   Add `web` or `GitHub` when the user explicitly asks for `Reddit`, `GitHub`, western tech media, or asks a broad question like `How is the global / western tech community reacting?`
3. **Choose sources based on the question**
   Do not query every source every time. Only comprehensive requests such as `global_signal_brief` should combine social, developer, and media sources in parallel.
4. **Never fake a unified result surface**
   If one source category has no signal, explicitly say `No meaningful signal was found in this source category.`

## Compliance Boundaries

- Only handle public web pages. Do not fetch pages that require login, invitation, or privileged access.
- Output summaries and synthesis only. Do not reproduce full article or post bodies.
- De-identify Reddit / GitHub user handles by default, except for official organization or project accounts.
- `paywalls`, `Discord`, `Slack`, and other closed communities are excluded.
- The repository currently documents cross-border data transfer status only as `not yet explicitly confirmed as compliance-approved in the skill document`. Add a formal conclusion before launch.

## Four Global Capabilities

### `global_social_search`

- Best for: how overseas users feel, how Reddit is discussing something, how X is reacting
- Typical sources: Sensight `social_search` / `daily_social` for X, plus Reddit search results
- Recommended output: attitude overview, support points, skepticism points, representative posts

### `developer_signal_search`

- Best for: GitHub community feedback, arguments in issues after a release, what developers are worried about
- Typical sources: GitHub `issues`, `discussions`, `PR comments`, `releases`
- Recommended output: primary issues, blast radius, breaking-change status, key threads

### `global_media_search`

- Best for: how overseas tech media is covering a story, what companies and labs are saying, whether reporting angles align
- Typical sources: tech media, company blogs, lab blogs; use Sensight `daily_blog` first when it covers the source
- Recommended output: media framing, official statement, disagreements, key reports

### `global_signal_brief`

- Best for: how the global tech community is reacting to a technology, how a model is being received internationally
- Typical sources: combined `global_social_search`, `developer_signal_search`, and `global_media_search`
- Recommended output: summary first, source-specific sections second

## Special Rules for Product-Research Queries

If a query explicitly asks for a product's positioning, pricing, quality perception, competitors, risks, or opportunities, do not run a single Sensight search and stop. Execute it as `global_signal_brief` and supplement these public sources:

- official page / official docs / pricing page
- tech media, company blogs, and lab blogs
- GitHub, Reddit, X, and developer forums
- third-party API aggregator blogs

If native Sensight results are empty, do not conclude `insufficient data` immediately. Only conclude that after the public-source supplement step is also exhausted.

## Output Template

When global mixed-source routing is triggered, use this default structure:

1. Start with 3-5 cross-source conclusions
2. `Social Signals`
3. `Developer / Open-Source Signals`
4. `Media and Official Releases`
5. `Key Sources`
6. `Source Attribution`: `AI industry highlights and social daily briefs are provided by Sensight; Reddit / GitHub / overseas media are supplemented from public web sources.`

## Routing Evaluation

In addition to the documentation mapping table in `SKILL.md`, the repository provides a routing evaluation layer aimed at the model itself:

- golden set: `tests/routing-eval-golden.json`
- evaluation script: `python3 scripts/routing_eval.py`

Recommended evaluation modes:

1. Replay evaluation: feed recorded model outputs via `--responses-file` to validate parsing and comparison logic quickly
2. Live evaluation: in CI or on a recurring schedule, call the same model with the same prompt and golden set, then verify whether `predicted_action` matches `expected_action`

Examples:

```bash
# Replay evaluation
python3 scripts/routing_eval.py --responses-file /tmp/routing_outputs.json

# Live evaluation (requires OPENAI_API_KEY)
python3 scripts/routing_eval.py --provider openai --model gpt-5.4-mini
```

## Example Queries

- `How does Reddit feel about Claude Code?`
- `How is GitHub reacting to a new release in a project?`
- `How is western tech media covering OpenAI's new model?`
- `How is the global tech community reacting to MCP lately?`
