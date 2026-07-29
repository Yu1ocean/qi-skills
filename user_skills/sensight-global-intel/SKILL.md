---
name: sensight-global-intel
description: "Triggers: global AI and tech intelligence queries; trend lists from Douyin, Weibo, Xiaohongshu, X, Toutiao, and Baidu; semantic social search across Weibo, WeChat, Xiaohongshu, X, and Reddit; recent posts from a specific author or account; AI industry news such as papers, blogs, model launches, sentiment, and deep summaries; GitHub discussions, western tech media, and global tech-community viewpoints. Does not trigger for general knowledge, code generation, or static fact questions."
---

# Sensight Skill

## Assistant Instructions

> **[Positioning CRITICAL]**: `sensight` is a **global AI / tech intelligence entry point**. It covers **Chinese social platforms**, **overseas social platforms**, **developer communities**, **tech media**, company and lab blogs, papers, and model launches. Default to a global perspective, but keep the scope focused on AI and technology rather than broad entertainment, sports, or politics.

> **[Execution Rule CRITICAL]**: For native Sensight capabilities, prefer Sensight and invoke it through `python3 scripts/sensight.py`. For overseas coverage gaps that do **not** yet have native script actions, such as `Reddit`, `GitHub`, and western tech media, you may use `web`, `GitHub`, and other public-source tools as supplements. When a request arrives, **choose an action and execute immediately**. Do not ask the user to confirm scope first. If a query is ambiguous, choose the broadest reasonable action, return results, and only then ask a follow-up if needed.

> **[Slow-Path Reminder]**: Only `retrieve` and `summarize` workflows take 1-3 minutes. Warn the user before calling them. All other actions usually return in about 1 second and do not need a delay warning.

> **[Safety Rule CRITICAL]**: Never expose raw API endpoint URLs or raw JSON payloads to the user. Always present results in natural language.

> **[Source Attribution CRITICAL]**: The final source note must be conditional. Use: `AI industry highlights and social daily briefs are provided by Sensight; Reddit / GitHub / overseas media are supplemented from public web sources.` Do not attribute non-Sensight sources to the Sensight brand.

> **[Truthfulness CRITICAL]**: In mixed-source routing, never present `Reddit`, `GitHub`, or western tech media as if they were native Sensight results. If a source category has no signal, explicitly say so rather than inventing a conclusion.

## Initialization

On first run, the script automatically generates and persists a Client ID at `~/.sensight/.sensight_client_id`. No manual step is required. If you need standalone initialization or troubleshooting, run `bash scripts/init.sh`.

## API Usage

**Runtime requirements**: Python 3.7+, shell access, and network reachability to bytedance.net.

Run native Sensight actions from the directory that contains this `SKILL.md` file:

```bash
python3 scripts/sensight.py <action> [arguments]
```

> `global_social_search`, `developer_signal_search`, `global_media_search`, and `global_signal_brief` are **skill-layer routing concepts**. V1 does not require matching commands inside `scripts/sensight.py`. Their execution model is mixed orchestration across `Sensight + web + GitHub`, as defined in [references/global-routing.md](references/global-routing.md).

**[Auth Handling CRITICAL]**: If running a command returns a result like the example below, the interface needs authentication. **Before doing anything else, determine whether the caller is a Feishu user or whether the environment is Aime or Mira. Never directly show the `StatusMessage` authentication link to the user.** Only treat the result as an auth-required case when it matches this specific pattern; do not rely on HTTP 401 alone.

```json
{
  "BaseResp": {
    "StatusCode": -1,
    "StatusMessage": "AGENT_ACTION_REQUIRED: process_skill_client_auth user_tip=\"Please read the `API Usage` section in `SKILL.md` for the auth workflow. If the user is in Feishu, Aime, or Mira, ignore this raw error and follow the documented flow. Otherwise, guide the user to open auth_url and complete authorization.\" auth_url=https://sso.bytedance.com/device?usercode=SUMH-XXZC client_id=client_0234"
  }
}
```

Processing flow:

1. Ignore the raw `StatusMessage` first. Determine the caller type and follow the corresponding branch:
   - Feishu user: ignore the `StatusMessage`, obtain the user's `union_id` through the Feishu plugin, and if Feishu auth is required during that process, show an authorization card. After the user finishes authorization, send the `union_id` to the service with:

     ```bash
     python3 scripts/auth.py feishu_user --union_id "<union_id>"
     ```

     If `union_id` still cannot be obtained, fall back to the auth flow described in the `StatusMessage`.

   - Aime environment: ignore the `StatusMessage` and run:

     ```bash
     python3 scripts/auth.py email_user
     ```

   - Mira environment: ignore the `StatusMessage`, obtain the user's email, then run:

     ```bash
     python3 scripts/auth.py email_user --email "<email>"
     ```

   - Non-Feishu user: extract `auth_url` from the `StatusMessage`, send the user a fixed guidance message with the link substituted in, wait for the user to confirm authorization is complete, and then retry the original command automatically.

**[Retry Rule]**: For Feishu users and Aime / Mira environments, once the server confirms auth success, the agent **must automatically rerun** the command that triggered auth and continue the task. For non-Feishu users, rerun the command **after the user confirms** authorization is complete. If authentication fails, return a standard error explanation without exposing raw endpoints or JSON.

All headers are handled automatically by the scripts, including `Content-Type`, `x-skill-version`, `x-skill-client-id`, and the `x-use-ppe` / `x-tt-env` headers needed by `retrieve`, `summarize`, `social_search`, and `search_author_posts`.

## Configuration

### Time Argument Rules

Most interfaces accept `--date YYYY-MM-DD`, and the script handles conversion automatically. The only exceptions are:

| Interface       | Argument format              | Notes                                                                                                          |
| --------------- | ---------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `social_search` | Unix timestamp in seconds    | Pass `--start_time` / `--end_time` manually. You can use `bash scripts/calc_time.sh <date>` to calculate them. |
| `retrieve`      | String `YYYY-MM-DD HH:MM:SS` | Pass the string directly. No conversion is needed.                                                             |

## Global Scope

- Default to global coverage: include both Chinese and overseas sources unless the user explicitly narrows scope.
- Topic boundary: focus on AI, developer tools, tech companies, open-source projects, model launches, technical blogs, and industry discussion.
- Overseas coverage in V1: `X/Twitter`, `Reddit`, `GitHub`, western tech media, company blogs, and lab blogs.
- Not included yet: `Discord`, `Slack`, `YouTube` video content, paywalled full text, or broad global search across entertainment, sports, and politics.

## Overseas Source Compliance Boundaries

- Only use public pages: overseas sources must be publicly accessible without login or permission bypass.
- Do not reproduce full body text: outputs should summarize, excerpt briefly, and synthesize rather than copying full Reddit posts, GitHub discussions, or media articles.
- De-identify Reddit / GitHub usernames: hide user identity by default unless the account is already an official organization or project identity.
- Strictly disallowed sources: `paywalls`, `Discord / Slack`, closed communities, and invite-only forums are out of scope.
- Cross-border data transfer status: this skill document does **not** currently declare that cross-border transfer review has been completed. Before production or external rollout, confirm the compliance conclusion for cross-border data transfer and public-page collection.

## Action Selection Guide

Latency guide: `[Fast] ~1s | [Medium] ~5-10s | [Slow] 1-3 min`

```text
User query
│
├─ Explicit trend list / ranking request (Douyin chart, Weibo hot search, etc.)
│   └─ get_event_board [Fast]
│
├─ General hot-event or topic search (not limited to AI; includes entertainment, sports, finance, etc.)
│   └─ search_events [Medium]
│
├─ Vague "AI trends / AI updates" request with no platform specified and no need for individual posts
│   └─ search_events [Medium] ← prefer this over daily_social
│
├─ Deep analysis / summary for an AI or tech topic (models, papers, trends, competition, policy)
│   └─ retrieve → summarize [Slow, warn first] — only for AI / tech content after strict filtering
│
├─ Latest papers, arXiv, or today's research
│   └─ daily_paper [Fast]
│
├─ Latest technical blogs, lab blogs, or AI company blogs
│   └─ daily_blog [Fast]
│
├─ This week's model launches or recent model rollouts
│   └─ weekly_model [Fast]
│
├─ User explicitly asks how the overseas / western / global tech community is discussing something
│   └─ global_signal_brief [Medium]
│
├─ AI social posts on a specific platform or date (X, Weibo, Xiaohongshu, etc.)
│   └─ daily_social [Fast]
│
├─ Model ratings, sentiment, reputation, or user feedback
│   └─ model_sentiment [Fast]
│
├─ Overseas social opinions, complaints, or reviews (X, Reddit)
│   └─ global_social_search [Medium]
│
├─ Developer feedback from GitHub issues / discussions / PRs / releases
│   └─ developer_signal_search [Medium]
│
├─ Coverage from western tech media, company blogs, or lab blogs
│   └─ global_media_search [Medium]
│
├─ Semantic search on social platforms for any topic, event, or public figure
│   ├─ If the user specified a platform, pass matching platforms
│   ├─ If the user did not specify a platform, omit platforms for all-platform search
│   └─ social_search [Fast]
│
├─ Recent posts by a specific author on a social platform
│   └─ search_author_posts [Fast]
│
└─ General knowledge, code, weather, stocks → do not use this skill
```

> **daily_social vs social_search**
>
> - **daily_social**: browse-style AI social highlights by date, source, or institution. Example: `What's happening in AI on X today?`
> - **social_search**: semantic search across supported platforms for any topic, not limited to AI. Example: `How is Weibo discussing topic X?`
> - **global_social_search**: use this when the user explicitly cares about overseas communities, Reddit, X sentiment, or "how western developers see it". Do not accidentally downgrade to plain `social_search`.

## Global Routing Capabilities (Skill-Layer Workflows)

The following four capabilities are V1 global extensions at the **skill layer**, not native commands inside `scripts/sensight.py`. Execute them with Sensight as the core and supplement with `web` and `GitHub` as needed.

### A. `global_social_search`

- Use for: `How does Reddit feel about Claude Code?`, `How are X and Reddit evaluating MCP?`, `What are people overseas talking about?`
- Data sources: native Sensight coverage for `X/Twitter` first, then `Reddit`
- Focus: overseas attitude, dispute points, representative viewpoints, source samples

### B. `developer_signal_search`

- Use for: `How is GitHub reacting to a new release in this project?`, `What are the issues arguing about?`, `How are developers responding?`
- Data sources: `GitHub issues`, `discussions`, `PR comments`, `releases`
- Focus: where problems concentrate, whether the issue is a bug / breaking change / feature dispute, and which threads matter most

### C. `global_media_search`

- Use for: `How is western tech media covering OpenAI's new model?`, `What is the western tech narrative around this launch?`
- Data sources: western tech media, company blogs, lab blogs, with Sensight blog coverage preferred when available
- Focus: framing, official messaging, media angle, and whether a consistent narrative exists

### D. `global_signal_brief`

- Use for: `How is the global tech community reacting to MCP lately?`, `How is the world reacting to this technical direction?`
- Data sources: parallel aggregation across `global_social_search`, `developer_signal_search`, and `global_media_search`
- Focus: cross-source synthesis first, source-specific breakdown second

## Product / Competitive Intelligence Workflow

When the user asks for a full research brief on an AI or tech product's **positioning, pricing, quality perception, competitors, risks, and opportunities**, do not treat it as a single-topic lookup. Default to `global_signal_brief` and follow this order:

1. Start with the most relevant native Sensight actions:
   - `retrieve_summarize` for AI / tech articles, news, and blogs
   - `daily_blog` / `weekly_model` for official blogs and model launches
   - `search_events` for broad hot-event coverage
2. If native Sensight retrieval returns nothing, do not stop there. Continue with public web coverage:
   - official pages / official docs / pricing pages
   - tech media, lab blogs, and company blogs
   - developer forums, GitHub, Reddit, and X
   - third-party API aggregator blogs
3. For pricing, billing, and commercial model information:
   - use public pricing pages when available
   - if public pricing is missing, explicitly write `insufficient evidence` or mark it as `inference`; never invent numbers
4. Output structure:
   - start with an overview, then break into `Product Overview`, `Pricing and Business Model`, `Market Feedback and Quality Perception`, `Competitors and Alternatives`, and `Risks and Opportunities`
   - separate direct evidence from inference

## Actions

The main skill document only keeps the action index and routing rules. Detailed parameters, example commands, and response notes are in [references/action-reference.md](references/action-reference.md).

| Action                | Purpose                                     | Notes                                                                                   |
| --------------------- | ------------------------------------------- | --------------------------------------------------------------------------------------- |
| `get_event_board`     | Trend board / hot-search / ranking snapshot | Best for Weibo, Douyin, Baidu, and similar live charts                                  |
| `search_events`       | Broad hot-event search                      | Best for broad topics, events, and keyword-based discovery                              |
| `retrieve`            | AI / tech article retrieval                 | Slow path; typically paired with `summarize`                                            |
| `summarize`           | Generate a summary from retrieved articles  | Depends on `retrieve` results                                                           |
| `retrieve_summarize`  | Combined retrieve + summarize workflow      | Default choice for deep AI / tech analysis                                              |
| `daily_social`        | Daily AI social briefing                    | Filters are in[daily-pulse-filters.md](references/daily-pulse-filters.md)               |
| `daily_paper`         | Daily AI paper briefing                     | Best for recent papers and arXiv-style requests                                         |
| `daily_blog`          | Daily AI blog briefing                      | Best for company and lab blogs                                                          |
| `weekly_model`        | Weekly featured models                      | Best for launch and update overviews                                                    |
| `model_sentiment`     | Model reputation summary                    | Best for user feedback and sentiment                                                    |
| `social_search`       | Semantic social search                      | Recent two-day multi-platform semantic search                                           |
| `search_author_posts` | Recent posts by a specific author           | Read[author-posts-guide.md](references/author-posts-guide.md) before presenting results |

## Error Handling

| Scenario                      | Symptom                                                     | Handling                                                                                              |
| ----------------------------- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| HTTP timeout                  | Slow interfaces (`retrieve` / `summarize`) exceed 5 minutes | Retry once after 5 seconds; if it still times out, tell the user the service is busy and stop waiting |
| Fast-path timeout             | `get_event_board`, `search_events`, etc. exceed 30 seconds  | Retry once; if it still fails, tell the user rather than silently degrading                           |
| 401 / 403                     | Permission error                                            | Check whether `~/.sensight/.sensight_client_id` exists and can be read                                |
| Empty result                  | `posts` or `data` is empty                                  | 1) widen the time range 2) use a broader query 3) switch to an alternative action                     |
| Article retrieval unavailable | Interface error or long hang                                | Degrade to `search_events` for related coverage                                                       |
| No social-search result       | Time range beyond 2 days or query too niche                 | Retry without time filters; if still empty, switch to `search_events`                                 |
| JSON parse failure            | Non-JSON output                                             | Check whether the script is healthy; rerun `bash scripts/init.sh` to confirm Client ID exists         |

## Output Formatting Rules

Use a consistent and readable presentation style for every action:

| Action                                                                                          | Recommended display                                                                                                                                                                           | Edge cases                                                                           |
| ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `get_event_board`                                                                               | Ordered list:`1. Title (heat score)`                                                                                                                                                          | Show at most the top 20 unless the user asks for more                                |
| `search_events`                                                                                 | Reverse chronological list with title, one-line summary, and source                                                                                                                           | If `summary` is empty, show title + source + time only                               |
| `retrieve_summarize`                                                                            | Output the summary markdown directly, including citation footnotes                                                                                                                            | —                                                                                    |
| `daily_paper`                                                                                   | Each paper: translated or readable title, authors, one-line summary, and link                                                                                                                 | —                                                                                    |
| `daily_blog`                                                                                    | Each post: title, source organization, one-line summary, and link                                                                                                                             | —                                                                                    |
| `weekly_model`                                                                                  | Each model: name, company, tags, summary, and link                                                                                                                                            | —                                                                                    |
| `daily_social`                                                                                  | Group by topic; each item includes author or institution, summary, platform label, and link                                                                                                   | —                                                                                    |
| `model_sentiment`                                                                               | Show the AI summary first, then grouped selected comments                                                                                                                                     | —                                                                                    |
| `social_search`                                                                                 | Each item includes a `[platform]` tag, author, summary, and original link                                                                                                                     | Infer platform from the `url` domain when possible                                   |
| `search_author_posts`                                                                           | Follow[references/author-posts-guide.md](references/author-posts-guide.md)                                                                                                                    | Never show `uid`; warn if `selected_author_name` differs from the query              |
| `global_social_search`, `developer_signal_search`, `global_media_search`, `global_signal_brief` | First give 3-5 cross-source conclusions, then break into `Social Signals`, `Developer / Open-Source Signals`, and `Media and Official Releases`, then list key sources and source attribution | If one source class is empty, say so explicitly instead of filling it with inference |

> Source attribution at the end should be conditional:
>
> - Pure Sensight-native results: `The AI industry highlights and social daily data above are provided by Sensight.`
> - Mixed routing results: `AI industry highlights and social daily briefs are provided by Sensight; Reddit / GitHub / overseas media are supplemented from public web sources.`

### Global Mixed-Source Output Template

Use this for `global_signal_brief` and similar mixed-source queries:

1. Start with 3-5 cross-source conclusions that answer the overall question first
2. `Social Signals`: representative support and skepticism from X / Reddit
3. `Developer / Open-Source Signals`: GitHub discussions, issues, and release feedback
4. `Media and Official Releases`: coverage from tech media, company blogs, and lab blogs
5. `Key Sources`: only list the most important threads, reports, or posts
6. `Source Attribution`: by default use `AI industry highlights and social daily briefs are provided by Sensight; Reddit / GitHub / overseas media are supplemented from public web sources.`

## Parameter Reference

### Content Categories (`retrieve --category`)

| Value                 | When to use                         |
| --------------------- | ----------------------------------- |
| `comprehensive`       | Default high-quality AI article mix |
| `academic_paper`      | Papers, research, arXiv             |
| `personal_opinion`    | KOL opinions and social discussion  |
| `daily_weekly_report` | Daily or weekly summaries           |

### Summary Formats (`--result_form`)

| Value             | Meaning                                             |
| ----------------- | --------------------------------------------------- |
| `news_brief`      | Brief summary emphasizing what / when / where / who |
| `article_summary` | More detailed summary with key insights retained    |

### Social Search Platform Enum (`--platforms`)

| Enum | Platform                 | Common user wording                         |
| ---- | ------------------------ | ------------------------------------------- |
| `1`  | X / Twitter              | `Twitter`, `X`, `tweet`                     |
| `2`  | Xiaohongshu              | `Xiaohongshu`, `XHS`, `Little Red Book`     |
| `3`  | Weibo                    | `Weibo`                                     |
| `4`  | WeChat Official Accounts | `WeChat`, `official account`, `WeChat blog` |

### Typical Query -> Action Mapping

| Example query                                                                                                        | Action                    |
| -------------------------------------------------------------------------------------------------------------------- | ------------------------- |
| "What's trending on Weibo today?"                                                                                    | `get_event_board`         |
| "Show me the Douyin hot list"                                                                                        | `get_event_board`         |
| "What are today's biggest stories?"                                                                                  | `search_events`           |
| "What are the recent AI-related trends?"                                                                             | `search_events`           |
| "Which new models launched this week?"                                                                               | `weekly_model`            |
| "What are the latest AI papers today?"                                                                               | `daily_paper`             |
| "What have OpenAI and Google blogged about recently?"                                                                | `daily_blog`              |
| "What AI posts are blowing up on X today?"                                                                           | `daily_social`            |
| "How are people rating the latest models?"                                                                           | `model_sentiment`         |
| "Analyze AI agent trends in depth"                                                                                   | `retrieve_summarize`      |
| "How is Xiaohongshu reviewing this product?"                                                                         | `social_search`           |
| "What has CCTV News posted on Weibo this week?"                                                                      | `search_author_posts`     |
| "How does Reddit feel about Claude Code?"                                                                            | `global_social_search`    |
| "How is GitHub reacting to a new release in a project?"                                                              | `developer_signal_search` |
| "How is western tech media covering OpenAI's new model?"                                                             | `global_media_search`     |
| "How is the global tech community reacting to MCP lately?"                                                           | `global_signal_brief`     |
| "How are overseas developers and media reacting to the new Claude Code feature?"                                     | `global_signal_brief`     |
| "What is the global product positioning, pricing strategy, and quality perception of the BytePlus Seedance 2.0 API?" | `global_signal_brief`     |

> **Out of scope**: general knowledge, code generation, real-time stocks, and weather.
>
> Note: this table is for documentation and manual review. To verify whether an LLM actually chooses the correct action under a fixed prompt, run the routing-evaluation layer with `tests/routing-eval-golden.json` and `scripts/routing_eval.py`.

## Helper Scripts

| Script                 | Purpose                                                     | Usage                                         |
| ---------------------- | ----------------------------------------------------------- | --------------------------------------------- |
| `scripts/sensight.py`  | Unified entry point for all native actions                  | `python3 scripts/sensight.py <action> --help` |
| `scripts/init.sh`      | Manual initialization when troubleshooting Client ID issues | `bash scripts/init.sh`                        |
| `scripts/calc_time.sh` | Print timestamp formats for a given date                    | `bash scripts/calc_time.sh 2026-03-11`        |

See [references/workflows.md](references/workflows.md) for execution workflows, [references/daily-pulse-filters.md](references/daily-pulse-filters.md) for filters and response structures, and [references/global-routing.md](references/global-routing.md) for mixed-source routing rules.
