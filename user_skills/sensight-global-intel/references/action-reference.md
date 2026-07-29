# Action Reference

This document contains detailed parameters, response notes, and example commands for native `sensight` actions. The main skill document keeps only routing and execution rules so that `SKILL.md` stays short and behavior-first.

## Table of Contents

- [Get Event Board](#1-get-event-board-fast-1s)
- [Search Events](#2-search-events-medium-5-10s)
- [Retrieve](#3-retrieve-slow-1-3-min)
- [Summarize](#4-summarize-slow-1-3-min)
- [Retrieve + Summarize Workflow](#34-retrieve--summarize-workflow-slow-1-3-min)
- [Daily Social Pulse](#5-daily-social-pulse-fast-1s)
- [Daily Paper Pulse](#6-daily-paper-pulse-fast-1s)
- [Daily Blog Pulse](#7-daily-blog-pulse-fast-1s)
- [Weekly Model Featured](#8-weekly-model-featured-fast-1s)
- [Model Sentiment Pulse](#9-model-sentiment-pulse-fast-1s)
- [Social Media Search](#10-social-media-search-fast-1s)
- [Author Posts](#11-author-posts-fast-1s)

### 1. Get Event Board [Fast ~1s]

Get ranked snapshots for a supported platform. Supports both real-time and historical snapshots. Not limited to AI topics.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `ranking_id` | string | Yes | `"12549"` Weibo Hot Search / `"2392"` Weibo Rising / `"4071"` Toutiao / `"4081"` Douyin / `"4658"` Twitter / `"182392"` Xiaohongshu / `"24847"` Baidu |
| `end_time` | integer | No | Unix timestamp; returns the latest snapshot before this time |

```bash
python3 scripts/sensight.py get_event_board --ranking_id 4081
python3 scripts/sensight.py get_event_board --ranking_id 12549 --end_time 1741651200
```

### 2. Search Events [Medium ~5-10s]

Broad hot-event search across the entire corpus. Not limited to AI. Supports keyword, semantic, time-based, and composite queries with internal LLM parsing.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `query` | string | Yes | Search text. Supports keywords, events, topics, time ranges, and composite requests. |

```bash
python3 scripts/sensight.py search_events --query "The latest hot topics in foundation models this week"
```

### 3. Retrieve [Slow 1-3 min]

**Only for AI / tech topics** such as model launches, papers, trends, competition, or policy. Non-AI requests should use `search_events` instead.

> Recommended combined workflow: `python3 scripts/sensight.py retrieve_summarize`

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `query` | string | Yes | Search keyword |
| `enhance_query` | string | No | Expanded intent for the query. This often improves quality. |
| `size` | integer | No | Recommended `10`-`30`; default `10` |
| `category` | string | No | Content category. See the main skill document for values. |
| `start_time` | string | No | Format `YYYY-MM-DD HH:MM:SS`; max span is one month when paired with `end_time` |
| `end_time` | string | No | Same as above |

```bash
python3 scripts/sensight.py retrieve --query "new model launches" --size 10
python3 scripts/sensight.py retrieve --query "new model launches" --size 20 \
  --start_time "2026-02-28 00:00:00" --end_time "2026-03-05 23:59:59"
```

Returns `{ "posts": [...] }`, where each item includes `content`, `publish_time`, `url`, and `media_info`.

### 4. Summarize [Slow 1-3 min]

Generate an AI summary from the posts returned by `retrieve`.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `posts_file` | path | Yes | Path to a JSON file containing retrieved posts, or `-` to read from stdin |
| `enhance_query` | string | Yes | The summary focus, expressed as an expanded intent |
| `intent` | string | No | User analysis intent. Defaults to automatic generation. |
| `result_form` | string | No | `news_brief` or `article_summary`; default `news_brief` |

```bash
python3 scripts/sensight.py summarize \
  --posts_file /tmp/posts.json --enhance_query "Latest progress in LLM agents"
python3 scripts/sensight.py summarize \
  --posts_file - --enhance_query "foundation model competition" --result_form article_summary
```

Returns `{ "content": "...", "is_finished": true }`.

### 3+4. Retrieve + Summarize Workflow [Slow 1-3 min]

One-step workflow that runs retrieval and summary generation together.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `query` | string | Yes | Search keyword |
| `enhance_query` | string | No | Expanded query; defaults to `query` |
| `size` | integer | No | Retrieval count; default `10` |
| `category` | string | No | Content category; default `comprehensive` |
| `start_time` | string | No | Format `YYYY-MM-DD HH:MM:SS` |
| `end_time` | string | No | Same as above |
| `result_form` | string | No | `news_brief` or `article_summary` |

```bash
python3 scripts/sensight.py retrieve_summarize --query "Latest progress in AI agents"
python3 scripts/sensight.py retrieve_summarize --query "foundation model launches" --size 20 \
  --start_time "2026-03-01 00:00:00" --end_time "2026-03-11 23:59:59" \
  --result_form article_summary
```

### 5. Daily Social Pulse [Fast ~1s]

Daily AI social highlights. Supports filtering by source type, author, and institution. See [daily-pulse-filters.md](./daily-pulse-filters.md) for filter details.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `date` | string | No | Format `YYYY-MM-DD`; defaults to today |
| `source_types` | array | No | Source-type filter |
| `authors` | array | No | Filter by author name |
| `institutions` | array | No | Filter by institution |

```bash
python3 scripts/sensight.py daily_social
python3 scripts/sensight.py daily_social --date 2026-03-06
python3 scripts/sensight.py daily_social --date 2026-03-06 --authors "Yann LeCun"
```

### 6. Daily Paper Pulse [Fast ~1s]

Latest AI academic papers, including title, authors, institutions, and translated abstracts when available.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `date` | string | No | Format `YYYY-MM-DD`; defaults to today and is converted to millisecond timestamps automatically |

```bash
python3 scripts/sensight.py daily_paper
python3 scripts/sensight.py daily_paper --date 2026-03-11
```

### 7. Daily Blog Pulse [Fast ~1s]

Latest technical blogs from major AI labs and companies.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `date` | string | No | Format `YYYY-MM-DD`; defaults to today and is converted to millisecond timestamps automatically |

```bash
python3 scripts/sensight.py daily_blog
python3 scripts/sensight.py daily_blog --date 2026-03-11
```

### 8. Weekly Model Featured [Fast ~1s]

Featured launches and updates for important AI models this week.

```bash
python3 scripts/sensight.py weekly_model
```

### 9. Model Sentiment Pulse [Fast ~1s]

Network-wide AI model sentiment summary with selected comments.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `limit` | integer | No | Number of records to return; default `20` |

```bash
python3 scripts/sensight.py model_sentiment
python3 scripts/sensight.py model_sentiment --limit 20
```

### 10. Social Media Search [Fast ~1s]

Semantic search across social platforms such as Weibo, WeChat Official Accounts, Xiaohongshu, and X / Twitter. **Not limited to AI topics.**

> Time limit: only the most recent **2 days** are supported.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `query` | string | Yes | Natural-language semantic query |
| `platforms` | array\<integer\> | No | Platform filter. Omit for all platforms. |
| `size` | integer | No | Number of items to return. Default `20`, max `20`. |
| `start_time` | integer | No | Start time as Unix seconds. Can only reach back two days. |
| `end_time` | integer | No | End time as Unix seconds. Defaults to now. |

```bash
python3 scripts/sensight.py social_search --query "audience reviews of the Spring Festival movie lineup"
python3 scripts/sensight.py social_search --query "audience reviews of the Spring Festival movie lineup" --platforms 3 2 --size 20
python3 scripts/sensight.py social_search --query "DeepSeek" --platforms 1 \
  --start_time 1772773200 --end_time 1772946000
```

### 11. Author Posts [Fast ~1s]

Retrieve recent posts from a specific user on a social platform. **Not limited to AI topics.**

> Time limit: only the most recent **7 days** are supported.

| Parameter | Type | Required | Notes |
| --- | --- | --- | --- |
| `platform` | integer | Yes | Platform ID: `1` = X / Twitter, `2` = Xiaohongshu, `3` = Weibo, `4` = WeChat Official Accounts |
| `author_name` | string | No | Author name. Either this or `mp_uid` must be provided. |
| `start_time` | integer | No | Start time in Unix seconds. Defaults to about one week back. |
| `end_time` | integer | No | End time in Unix seconds. Defaults to the current time. |
| `mp_uid` | string | No | Unique author identifier. If present, it takes precedence over `author_name`. |
| `page_number` | integer | No | Pagination. Starts at `1`; default `1`. |

```bash
python3 scripts/sensight.py search_author_posts --platform 3 --author_name "CCTV News"
python3 scripts/sensight.py search_author_posts --platform 3 --author_name "CCTV News" \
  --start_time 1773046137 --end_time 1773650937
python3 scripts/sensight.py search_author_posts --platform 3 \
  --mp_uid "abc123" --page_number 2
```

> **[CRITICAL]** Read [author-posts-guide.md](./author-posts-guide.md) before presenting author-post results.
