# Workflow Reference

## Article Insight Workflow (Retrieve + Summarize)

Article retrieval and AI summary generation are a two-step chain. Use `retrieve_summarize` when possible.

```bash
# Basic usage
python3 scripts/sensight.py retrieve_summarize --query "Latest progress in AI agents"

# Full example
python3 scripts/sensight.py retrieve_summarize \
  --query "foundation model launches" \
  --enhance_query "Foundation model launches and update dynamics in March 2026" \
  --start_time "2026-03-01 00:00:00" \
  --end_time "2026-03-11 23:59:59" \
  --size 20 \
  --result_form article_summary
```

The script automatically handles Client ID injection, in-memory passing of intermediate JSON, and empty-result messaging.

If you need to run the steps separately, for example to inspect retrieval results before summarizing:

```bash
# Step 1: retrieve and save to a file
python3 scripts/sensight.py retrieve --query "foundation model launches" --size 10 > /tmp/posts.json

# Step 2: summarize from the retrieval result
python3 scripts/sensight.py summarize \
  --posts_file /tmp/posts.json \
  --enhance_query "foundation model launch dynamics" \
  --result_form news_brief
```

---

## social_search Timestamp Quick Reference

`social_search` expects Unix timestamps in seconds for `--start_time` / `--end_time`. Use:

```bash
bash scripts/calc_time.sh 2026-03-11
# Output: START_UNIX / END_UNIX and other timestamp formats
```

See [daily-pulse-filters.md](daily-pulse-filters.md) for filter enums and response structures.

---

## Global Mixed-Source Routing

For sources that do not yet have native actions in `scripts/sensight.py`, such as `Reddit`, `GitHub`, and western tech media, follow the skill-layer routing described in `SKILL.md`:

- `global_social_search`
- `developer_signal_search`
- `global_media_search`
- `global_signal_brief`

See [global-routing.md](global-routing.md) for routing rules and output templates.
