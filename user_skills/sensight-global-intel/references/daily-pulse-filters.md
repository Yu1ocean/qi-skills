# Filter and Response Structure Reference

This document records available filters, enum values, and response JSON structures for each interface. It is intended for display logic and debugging.

## Table of Contents

- [Daily Social Pulse (`GetResults`) Filters](#daily-social-pulse-getresults-filters)
- [Response Data Structures by Interface](#response-data-structures-by-interface)
- [`GetEventBoard`](#geteventboard)
- [`SearchEvents`](#searchevents)
- [`GetResults`](#getresults)
- [`ListPapers`](#listpapers)
- [`ListBlogs`](#listblogs)
- [`GetWeeklyFeatured`](#getweeklyfeatured)
- [`GetModelSentiment`](#getmodelsentiment)
- [`SocialSearch`](#socialsearch)
- [`SearchAuthorPosts`](#searchauthorposts)

---

## Daily Social Pulse (`GetResults`) Filters

`source_types`, `institutions`, and `authors` are all arrays. Passing `[]` means no filtering.

### `source_types` Options

| Value | Meaning |
| --- | --- |
| `"Industry Figure"` | Post from an industry leader or researcher |
| `"Model Company"` | Post from an official model-company account |

### `institutions` Options

| Value |
| --- |
| `"Google"` |
| `"OpenAI"` |
| `"Runway"` |
| `"minimax"` |
| `"xAI"` |
| `"Tencent"` |
| `"Alibaba"` |
| `"Other"` |

> Note: the `institutions` list is dynamic in practice. The values above are representative examples that have been observed. The `authors` field is also dynamic because it comes from `source.name`.

### Filter Example

```bash
# Only posts from Google and OpenAI industry figures
python3 scripts/sensight.py daily_social \
  --date 2026-03-05 \
  --source_types "Industry Figure" \
  --institutions "Google" "OpenAI"
```

---

## Response Data Structures by Interface

### `GetEventBoard`

**Data path**: `response.data[]`

```json
{
  "TopRank": 1,
  "Title": "The U.S. and China reached preliminary consensus on several issues",
  "Heat": 12096044,
  "HeatRise": 0,
  "Sentiment": "NEUTRAL",
  "Tag": "owls_others",
  "TagName": "Other",
  "ExternalLink": "https://www.douyin.com/search/...",
  "Id": "16241400976813747175",
  "TimeInBoard": 49579,
  "Extra": "{}"
}
```

> Sort by `TopRank` when displaying. Recommended format: `{TopRank}. {Title} (heat {Heat})`. `Sentiment` enum values are `POSITIVE`, `NEUTRAL`, and `NEGATIVE`.

---

### `SearchEvents`

**Data path**: `response.data[]`

```json
{
  "event_id": "1010155534361856360",
  "title": "Xiaomi launches its latest MiMo large model",
  "start_time": "2025-12-17 16:00:00",
  "end_time": "2025-12-18 10:00:00",
  "score": 7780973,
  "summary": "",
  "url": "https://www.douyin.com/search/...",
  "ranking_name": "Douyin",
  "ranking_id": "4081",
  "index": 17
}
```

> `summary` may be an empty string. In that case, display `title + source + time`. Results are already sorted by `score` descending.

---

### `GetResults`

**Data path**: `response.data.posts[]`

```json
{
  "id": 6279014,
  "source": {
    "id": 1490,
    "name": "Natasha Jaques",
    "avatar": "https://...",
    "institution": "Google",
    "source_type": "Industry Figure",
    "job_title": ""
  },
  "content": "Original post content",
  "translate_content": "Translated content",
  "created_at": 1772664976,
  "category": "Technology trends and frontier research",
  "url": "https://x.com/...",
  "like_count": 0,
  "repost_count": 10,
  "view_count": 0
}
```

**The response also includes**:

- `data.topics[]`: hot-topic list. Each topic includes `title` and related `post_ids`.

---

### `ListPapers`

**Data path**: `response.data.data[]` (note the double `data`)

```json
{
  "title": "Paper title in English",
  "translated_title": "Translated paper title",
  "authors": ["Author 1", "Author 2"],
  "abstract": "Paper abstract in English",
  "translated_abstract": "Translated abstract",
  "url": "https://arxiv.org/...",
  "publish_time": 1741132800
}
```

---

### `ListBlogs`

**Data path**: `response.data.data[]` (note the double `data`)

```json
{
  "post_id": 2574120,
  "source": {
    "name": "OpenAI",
    "institution": "OpenAI",
    "source_type": "rss"
  },
  "title": "Blog title in English",
  "translated_title": "Translated blog title",
  "summary": "Summary in English",
  "translated_summary": "Translated summary",
  "url": "https://openai.com/...",
  "publish_time": 1741222800
}
```

---

### `GetWeeklyFeatured`

**Data path**: `response.data.featured_events[]`

```json
{
  "id": 47,
  "model_series": "Gemini 3",
  "model_version_name": "Gemini 3.1 Flash-Lite",
  "organization": "Google",
  "logo_url": "https://...",
  "summary": "Chinese or translated launch summary",
  "publish_time": 1772555640000,
  "tags": ["fastest", "most cost efficient", "scalable intelligence"],
  "url": "https://blog.google/..."
}
```

> `publish_time` is a millisecond timestamp.

---

### `GetModelSentiment`

**Data paths**:

- `response.data.ai_summary`: overall AI-generated sentiment summary
- `response.data.comments[]`: selected community comments

```json
{
  "id": 144346,
  "content": "Original comment text",
  "summary": "Comment summary",
  "platform": "WeChat Official Account",
  "author_name": "Author Name",
  "author_avatar": "https://...",
  "publish_time": 1772383149000,
  "mentioned_models": ["Claude Code", "Gemini 3"],
  "original_url": "https://..."
}
```

**Common `platform` values** include `"WeChat Official Account"`, `"Twitter"`, and `"Weibo"`.

---

### `SocialSearch`

**Top-level structure**: `{ "BaseResp": { "StatusCode": 0 }, "items": [...] }`

**Data path**: `response.items[]`

```json
{
  "content": "Why does DeepSeek feel less capable than before?",
  "title": "DeepSeek",
  "url": "https://www.xiaohongshu.com/discovery/item/...",
  "user_name": "63393abb0000000018029351",
  "publish_time": "2026-03-15T10:45:31Z",
  "score": 0.8378
}
```

> `publish_time` is an ISO 8601 UTC string and should be converted to local time for display. `user_name` may be a numeric UID. There is no explicit `platform` or `like_count` field here.

---

### `SearchAuthorPosts`

See [author-posts-guide.md](author-posts-guide.md) for the detailed response and presentation rules.
