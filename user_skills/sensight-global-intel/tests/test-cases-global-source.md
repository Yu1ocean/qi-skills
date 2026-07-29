# Sensight Skill Global-Source Test Cases

Test dimensions: routing triggers, source mixing, fallback behavior, and backward compatibility.

Test date: 2026-04-23

## Test Matrix

| ID | Theme | Query | Expected route | Result | Notes |
| --- | --- | --- | --- | --- | --- |
| G01 | Overseas social opinion | How does Reddit feel about Claude Code? | `global_social_search` | ⬜ | |
| G02 | GitHub release feedback | How is GitHub reacting to a new release in a project? | `developer_signal_search` | ⬜ | |
| G03 | Western tech-media coverage | How is western tech media covering OpenAI's new model? | `global_media_search` | ⬜ | |
| G04 | Global tech-community synthesis | How is the global tech community reacting to MCP lately? | `global_signal_brief` | ⬜ | |
| G05 | Mixed sources, not flat concatenation | How are overseas developers and media reacting to the new Claude Code feature? | `global_signal_brief` | ⬜ | |
| G06 | Source-gap fallback | Reddit has no useful result, but GitHub and media do | explicit gap handling | ⬜ | |
| G07 | Backward compatibility with Chinese-platform capability | What's trending on Weibo today? | `get_event_board` | ⬜ | |
| G08 | Backward compatibility with existing social search | How is Xiaohongshu reviewing this product? | `social_search` | ⬜ | |

> Status legend: ⬜ pending | ✅ pass | ❌ fail | ⚠️ partial

## Detailed Cases

### G01 — Reddit / X Overseas Social Opinion

**Query**

```text
How does Reddit feel about Claude Code?
```

**Expected behavior**

- Trigger globalized `sensight`
- Interpret the request as overseas community sentiment rather than falling back to Weibo or Xiaohongshu
- Route to `global_social_search`
- Include at least a `Social Signals` section

**Acceptance criteria**

- Start with 3-5 cross-source conclusions
- Explicitly mention Reddit; if X is also used, label it clearly
- Do not present overseas posts as native Sensight JSON

### G02 — GitHub Release Feedback

**Query**

```text
How is GitHub reacting to a new release in a project?
```

**Expected behavior**

- Route to `developer_signal_search`
- Focus on `releases`, `issues`, `discussions`, and `PR comments`

**Acceptance criteria**

- Output must include `Developer / Open-Source Signals`
- Distinguish bug reports, breaking changes, and product disagreements
- State explicitly when there is no useful result

### G03 — Western Tech-Media Coverage

**Query**

```text
How is western tech media covering OpenAI's new model?
```

**Expected behavior**

- Route to `global_media_search`
- Prefer media reports, company blogs, and lab blogs

**Acceptance criteria**

- Output must include `Media and Official Releases`
- Summarize the reporting angles first, then list key sources

### G04 — Global Tech-Community Synthesis

**Query**

```text
How is the global tech community reacting to MCP lately?
```

**Expected behavior**

- Route to `global_signal_brief`
- Aggregate social, developer, and media sources

**Acceptance criteria**

- Start with 3-5 cross-source conclusions
- Then break into `Social Signals`, `Developer / Open-Source Signals`, and `Media and Official Releases`
- End with `Key Sources`

### G05 — Mixed Sources Without Flat Concatenation

**Query**

```text
How are overseas developers and media reacting to the new Claude Code feature?
```

**Acceptance criteria**

- Do not simply paste X, Reddit, GitHub, and media snippets one after another
- Include one synthetic judgment paragraph
- Keep source-grouped structure clear

### G06 — Gap Fallback

**Scenario**

```text
Reddit has no useful result, but GitHub and media do.
```

**Acceptance criteria**

- Explicitly state that `Reddit` has no meaningful signal
- Keep the GitHub and media sections
- Do not invent Reddit opinions just to fill the structure

### G07 — Compatibility With Existing Chinese-Platform Capability

**Query**

```text
What's trending on Weibo today?
```

**Acceptance criteria**

- Still routes to `get_event_board`
- Does not switch to overseas sources just because global mode is the default

### G08 — Compatibility With Existing Social Search

**Query**

```text
How is Xiaohongshu reviewing this product?
```

**Acceptance criteria**

- Still routes to `social_search`
- Does not incorrectly upgrade to `global_social_search` just because the query asks for reviews
