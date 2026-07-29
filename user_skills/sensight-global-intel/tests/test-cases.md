# Sensight Skill Test Cases v0.2.2

Test dimensions: trigger accuracy, action selection, parameter filling, output formatting, and error recovery.

Test date: 2026-03-17
Test environment: OpenClaw / personal-assistant-style agent

## Test Matrix

| ID | Category | Query | Expected action | Result | Notes |
| --- | --- | --- | --- | --- | --- |
| T01 | Trigger | What's on the Douyin hot list right now? | `get_event_board` | ⬜ | |
| T02 | Trigger | Show me Weibo hot search | `get_event_board` | ⬜ | |
| T03 | Trigger | How is Weibo discussing DeepSeek lately? | `social_search` | ⬜ | |
| T04 | Trigger | What has CCTV News posted on Weibo recently? | `search_author_posts` | ⬜ | |
| T05 | Trigger | What are today's biggest stories? | `search_events` | ⬜ | |
| T06 | No trigger | Write a Python bubble sort | — | ⬜ | |
| T07 | No trigger | What kind of model is GPT-4? | — | ⬜ | |
| T08 | No trigger | What's the weather in Beijing today? | — | ⬜ | |
| T09 | Action split | What are today's AI hot topics? | `search_events` | ⬜ | |
| T10 | Action split | What's happening in AI on X today? | `daily_social` | ⬜ | |
| T11 | Action split | How is Xiaohongshu reviewing the iPhone 16? | `social_search` | ⬜ | |
| T12 | Action split | What are the latest AI papers today? | `daily_paper` | ⬜ | |
| T13 | Parameter fill | Search X and Xiaohongshu for reviews of Claude 3.7 | `social_search(platforms=1,2)` | ⬜ | |
| T14 | Parameter fill | What has Yann LeCun posted recently? | `search_author_posts(platform=1)` | ⬜ | |
| T15 | Parameter fill | Give me a deep analysis of the latest AI agent progress | `retrieve_summarize` | ⬜ | |
| T16 | Time inference | What was trending on Weibo yesterday? | `get_event_board(end_time=yesterday)` | ⬜ | |
| T17 | Time inference | How did Weibo discuss the Spring Festival Gala in the last two days? | `social_search(no time args)` | ⬜ | |
| T18 | Output format | Top 10 Douyin hot-list items | `get_event_board -> ordered list` | ⬜ | |
| T19 | Output format | Milk-tea discussion on Xiaohongshu and Weibo | `social_search -> [platform] tags` | ⬜ | |
| T20 | Output format | CCTV News activity on Weibo | `search_author_posts -> no uid exposure` | ⬜ | |
| T21 | Error recovery | Force `social_search` to use a time range older than 2 days | retry without time filter | ⬜ | |
| T22 | Error recovery | Analyze AI agent content from last month | explain time-range limits and suggest adjustment | ⬜ | |

> Status legend: ⬜ pending | ✅ pass | ❌ fail | ⚠️ partial

## Detailed Cases

### Group 1: Trigger Accuracy

#### T01 — Douyin Hot List

**Query**

```text
What's on the Douyin hot list right now?
```

**Expected behavior**

- Trigger the `sensight` skill
- Call `get_event_board --ranking_id 4081`
- Execute immediately without asking the user to confirm

**Acceptance criteria**

- Ordered list output
- Each item includes title and heat
- Show at most the top 20 items
- Mention Sensight in the source note

#### T02 — Weibo Hot Search

**Query**

```text
Show me Weibo hot search.
```

**Expected behavior**

- Trigger `sensight`
- Call `get_event_board --ranking_id 12549` rather than the Weibo rising board `2392`

#### T03 — Social Search Trigger

**Query**

```text
How is Weibo discussing DeepSeek lately?
```

**Expected behavior**

- Trigger `sensight`
- Call `social_search --query "DeepSeek" --platforms 3`
- Omit explicit time parameters so the search uses the default two-day window

#### T04 — Author Posts Trigger

**Query**

```text
What has CCTV News posted on Weibo recently?
```

**Expected behavior**

- Trigger `sensight`
- Call `search_author_posts --platform 3 --author_name "CCTV News"`
- Omit time arguments so the default seven-day window applies

#### T05 — General Hot Events

**Query**

```text
What are today's biggest stories?
```

**Expected behavior**

- Trigger `sensight`
- Call `search_events` with a broad news-oriented query

### Group 2: Should Not Trigger

#### T06 — Coding Task

```text
Write a Python bubble sort.
```

Expected behavior: do not trigger `sensight`; answer directly.

#### T07 — General Knowledge

```text
What kind of model is GPT-4?
```

Expected behavior: do not trigger `sensight`; answer from general model knowledge.

#### T08 — Weather

```text
What's the weather in Beijing today?
```

Expected behavior: do not trigger `sensight`; weather is out of scope.

### Group 3: Similar Action Boundaries

#### T09 — Semantic Hot Topics vs Daily Social Brief

```text
What are today's AI hot topics?
```

Expected behavior: use `search_events`, not `daily_social`.

#### T10 — Platform-Specified Browsing Request

```text
What's happening in AI on X today?
```

Expected behavior: use `daily_social`. This differs from T09 because the platform is explicitly specified.

#### T11 — Non-AI Social Search

```text
How is Xiaohongshu reviewing the iPhone 16?
```

Expected behavior: use `social_search`, not `daily_social`.

#### T12 — Daily Papers

```text
What are the latest AI papers today?
```

Expected behavior: use `daily_paper`, not `retrieve`.

### Group 4: Parameter Filling

#### T13 — Multi-Platform Search

```text
Search X and Xiaohongshu for reviews of Claude 3.7.
```

Expected behavior: call `social_search --query "Claude 3.7 reviews" --platforms 1 2`.

#### T14 — Specific Person's Posts

```text
What has Yann LeCun posted recently?
```

Expected behavior: call `search_author_posts --platform 1 --author_name "Yann LeCun"`.

#### T15 — Deep Analysis

```text
Give me a deep analysis of the latest AI agent progress.
```

Expected behavior:

- Call `retrieve_summarize`
- Warn the user that it will take 1-3 minutes
- Use `article_summary` for the result form

### Group 5: Time Inference

#### T16 — Historical Trend Snapshot

```text
What was trending on Weibo yesterday?
```

Expected behavior: compute yesterday's Unix timestamp and pass it to `get_event_board --end_time`.

#### T17 — `social_search` Time Boundary

```text
How did Weibo discuss the Spring Festival Gala in the last two days?
```

Expected behavior: use `social_search --query "Spring Festival Gala" --platforms 3` with no explicit timestamps.

### Group 6: Output Format

#### T18 — Trend List Truncation

```text
Top 10 Douyin hot-list items.
```

Acceptance criteria:

- Only 10 items
- Format like `1. Title (heat 12096044)`
- Mention Sensight in the attribution note

#### T19 — Social Search Platform Tags

```text
Milk-tea discussion on Xiaohongshu and Weibo.
```

Acceptance criteria:

- Each item shows `[Xiaohongshu]` or `[Weibo]`
- Do not expose raw URL domains or numeric platform enums
- Do not expose raw JSON

#### T20 — Author-Post `uid` Rule

```text
CCTV News posts on Weibo.
```

Acceptance criteria:

- No `uid` string appears in output
- Warn the user if `selected_author_name` differs from `CCTV News`
- Do not auto-rewrite the author name

### Group 7: Error Recovery

#### T21 — `social_search` Out-of-Range Time

**Steps**

1. Send: `How did Weibo discuss DeepSeek three days ago?`
2. If the agent passes a timestamp older than the 2-day limit, the interface returns no result.

**Expected recovery**

- Retry without time parameters
- Tell the user that social search only covers the latest 2 days and the range was adjusted automatically
- If still empty, suggest switching to `search_events`

#### T22 — Old `retrieve` Time Range

```text
Analyze the market reaction when GPT-4 launched last year.
```

Expected behavior:

- Warn the user that the request may take 1-3 minutes
- If `posts` is empty, explain that no matching articles were found and suggest a broader time range or different keywords
- Do not silently fail or invent content

## Test Notes

1. Run each case independently so context from prior turns does not bias action selection.
2. Watch T06-T08 closely because false triggering is high severity.
3. T09 vs T10 is an especially important stability boundary.
4. T14 vs T03 tests the difference between `search for posts about someone` and `search the posts written by that person`.
5. For T18-T20, compare the output directly against the formatting rules in `SKILL.md`.
