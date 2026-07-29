# Sensight Skill Complex Test Cases v0.2.2

Test dimensions: repeated calls, parallel calls, chained workflows, multi-turn follow-ups, and graceful degradation.

Test date: 2026-03-17

## Test Matrix

| ID | Mode | Query | Expected call chain | Result | Notes |
| --- | --- | --- | --- | --- | --- |
| C01 | Parallel | Compare Douyin, Weibo, and Xiaohongshu trend boards | `get_event_board` x3 in parallel | ⬜ | |
| C02 | Parallel | Build today's panoramic AI daily brief | `daily_paper + daily_blog + weekly_model + daily_social` in parallel | ⬜ | |
| C03 | Parallel | Compare recent posts from two named authors | `search_author_posts` x2 in parallel | ⬜ | |
| C04 | Parallel | Compare DeepSeek sentiment across platforms | `social_search` x3 or one all-platform call | ⬜ | |
| C05 | Chained | Trend-board topic -> Weibo discussion | `get_event_board -> social_search` | ⬜ | |
| C06 | Chained | Weekly models -> model sentiment | `weekly_model -> model_sentiment` | ⬜ | |
| C07 | Chained | Hot-topic discovery -> deep report | `search_events -> retrieve_summarize` | ⬜ | |
| C08 | Chained | Model launch -> sentiment -> deep report | `weekly_model -> model_sentiment -> retrieve_summarize` | ⬜ | |
| C09 | Multi-turn | Trend list -> ask about the third-ranked topic | use prior result context | ⬜ | |
| C10 | Multi-turn | Paper list -> ask for a deep summary of one paper | use prior result context | ⬜ | |
| C11 | Repeated | Compare Monday vs Friday paper trends | `daily_paper` x2 with different dates | ⬜ | |
| C12 | Fallback | `retrieve_summarize` times out, then degrades | `retrieve_summarize -> retry -> search_events` | ⬜ | |

> Status legend: ⬜ pending | ✅ pass | ❌ fail | ⚠️ partial

## Detailed Cases

### C01 — Multi-Platform Trend Comparison in Parallel

**Query**

```text
Compare the current trend boards on Douyin, Weibo, and Xiaohongshu, and tell me which platform feels the most interesting right now.
```

**Acceptance criteria**

- Three calls are executed in parallel
- Output is split into three clearly labeled platform sections
- Show the top 10 items per platform
- Include a short cross-platform comparison

### C02 — Panoramic AI Daily Brief

**Query**

```text
Create today's AI panorama: latest papers, technical blogs, weekly model launches, and social highlights.
```

**Acceptance criteria**

- Four interfaces run in parallel
- Output is divided into four sections
- Each section includes a source label
- End with a one-sentence daily summary

### C03 — Two Author Streams in Parallel

**Query**

```text
Compare what Yann LeCun and Sam Altman have posted recently, and summarize how their focus differs.
```

**Acceptance criteria**

- Fetch both author streams in parallel
- Present the two result sets separately
- Never show `uid`
- If `selected_author_name` differs from the query, warn separately for each stream

### C04 — Cross-Platform Sentiment Comparison

**Query**

```text
Compare how Weibo, Xiaohongshu, and X are reacting to DeepSeek. Are the tones different?
```

**Acceptable call plans**

- Three parallel calls, one per platform
- Or one all-platform `social_search` call with grouped presentation

**Acceptance criteria**

- Group by platform
- Include a cross-platform tone comparison
- Explicitly say when one platform has no result

### C05 — Trend Topic -> Weibo Discussion

**Query**

```text
What's ranked #1 on Weibo hot search right now, and how is Weibo discussing that topic?
```

**Acceptance criteria**

- Automatically move from step 1 to step 2 without waiting for user confirmation
- Use the actual trend-board title extracted from step 1 as the `social_search` query
- Show the trend title first, then the Weibo discussion

### C06 — Weekly Models -> Sentiment

**Query**

```text
Which new models launched this week, and how are users reacting to them?
```

**Acceptance criteria**

- Execute both steps in sequence
- Integrate the weekly model results with sentiment results
- Say so explicitly if sentiment data is missing for newly launched models

### C07 — Hot Topic Discovery -> Deep Report

**Query**

```text
Find the hottest topic in large-model news lately, then write a deep analysis of that topic.
```

**Acceptance criteria**

- Identify the hottest topic from the `search_events` result
- Warn the user that the deep analysis will take 1-3 minutes
- Generate a materially expanded `enhance_query`
- Use `article_summary`

### C08 — Three-Step Chain: Launch -> Sentiment -> Deep Report

**Query**

```text
Which newly launched model got the most attention this week? How are users reacting to it? Then give me a deep report on that model.
```

**Acceptance criteria**

- Complete all three steps without pausing for clarification
- Use transition language between steps
- Integrate the three stages into one coherent report

### C09 — Multi-Turn Follow-Up: Trend List -> Third Item

**Turn 1**

```text
What's on Weibo hot search right now?
```

**Turn 2**

```text
What is the third-ranked topic about? Search how Weibo is discussing it.
```

**Acceptance criteria**

- Correctly resolve `the third-ranked topic` from turn 1
- Do not call `get_event_board` again
- Use the actual title from the earlier result as the `social_search` query

### C10 — Multi-Turn Follow-Up: Paper List -> One Paper

**Turn 1**

```text
What AI papers came out today?
```

**Turn 2**

```text
Give me a deep summary of the second paper.
```

**Acceptance criteria**

- Correctly resolve the paper from turn 1
- Build the retrieval query from the paper title rather than a generic phrase
- Use `category=academic_paper`
- Warn the user about the 1-3 minute delay

### C11 — Repeated Calls: Two-Day Paper Trend Comparison

**Query**

```text
Compare Monday's AI papers with today's AI papers and summarize how the research directions changed.
```

**Acceptance criteria**

- Two calls with different date parameters
- Output separated into two date buckets
- Include a trend comparison summary
- If one date is empty, say so clearly instead of filling in content

### C12 — Graceful Degradation After Timeout

**Query**

```text
Give me a deep analysis of today's latest AI progress.
```

**Scenario**

`retrieve_summarize` times out because the service is busy.

**Expected behavior**

1. Retry `retrieve_summarize` once
2. If it still times out, degrade to `search_events`
3. Tell the user that the deep retrieval service is busy and the fallback result is broader but less complete

## Notes

- Parallel cases should be judged partly on total latency
- Chained cases should be judged on whether intermediate outputs are passed forward automatically
- Multi-turn cases should be judged on context tracking, not just raw action choice
- Fallback cases should never fail silently
