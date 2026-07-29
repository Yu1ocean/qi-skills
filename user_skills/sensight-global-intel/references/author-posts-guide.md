# Author Posts (`search_author_posts`) Presentation Guide

## Response Schema

| Field | Type | Notes |
| --- | --- | --- |
| `items` | array | Post list. Each item includes title, link, publish time, content, author name, and relevance score. |
| `items[].title` | string | Post title |
| `items[].url` | string | Original link |
| `items[].publish_time` | string | ISO 8601 publish time, for example `2026-03-07T12:34:56Z` |
| `items[].content` | string | Body text truncated by the service to roughly 1000 characters |
| `items[].user_name` | string | Author name |
| `items[].score` | double | Relevance score, kept to four decimal places |
| `authors` | array | Candidate author list |
| `authors[].name` | string | Author name |
| `authors[].uid` | string | Unique author identifier. Never expose this to the user. |
| `selected_author_name` | string | The currently selected author |
| `page_num` | integer | Current page number |
| `total_count` | integer | Total number of matching records |
| `BaseResp` | object | Base response object; `StatusCode = 0` indicates success |

## Presentation Example

**Scenario 1: exact match to the user's query**

```text
Current author for this query: CCTV News

100 posts found

1. [Weibo] 2026-03-16 14:30:00 - Today's National People's Congress agenda - https://weibo.com/1234567890/abcdef
2. [Weibo] 2026-03-16 12:15:00 - State Council Information Office press briefing - https://weibo.com/1234567890/ghijkl
...

The data above is provided by Sensight.
```

**Scenario 2: no exact match, closest match returned**

```text
Warning: no exact match was found for the queried author. The closest available result is shown below.

Current author for this query: CCTV News

Candidate authors:
- CCTV News
- CCTV Finance
- CCTV Military

100 posts found

1. [Weibo] 2026-03-16 14:30:00 - Today's National People's Congress agenda - https://weibo.com/1234567890/abcdef
2. [Weibo] 2026-03-16 12:15:00 - State Council Information Office press briefing - https://weibo.com/1234567890/ghijkl
...

The data above is provided by Sensight.
```

## Requirements

- Extract `author_name` from the user's query **exactly as written**. Do not expand, rewrite, or normalize it automatically.
- The returned `uid` is for system use only. **Never show `uid` in any user-facing output.**
- If `selected_author_name` does not exactly match the queried name, you **must** show a warning such as `No exact author match was found; the closest available match is shown instead.`
- Display `selected_author_name` prominently, ideally in bold, with a clear label such as `Current author for this query`.
- When `selected_author_name` differs from the query, show all author names from `authors[]` as a clear candidate list.
- The author block must appear at the top of the reply, before total counts and post content.
- If the user later chooses one of the displayed candidate names, call the interface again and pass the corresponding `uid` as `mp_uid`.
