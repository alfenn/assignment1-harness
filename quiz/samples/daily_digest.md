# The daily digest

*P2 daily_digest*

> What does your digest pipeline do in code before the final LLM call, and what does that call see? How do you make sure the digest stays under 300 words and names every urgent item, without cutting the model's text?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

**Short answer:** everything before the final call is code: classify every email in parallel, drop ignore, group by thread, urgent first. One LM call writes the digest, with one shorter rewrite if it runs long.

#### Classify · `daily_digest.py:47-60`
- `classify_all` runs P1's `classify_priority` on every email at once, **16 workers**, results kept in input order
- `unknown` counts as normal

#### Aggregate · `daily_digest.py:66-89`
- Ignore emails dropped **before** grouping: nothing from the ignore pile reaches the final prompt; I never ask the model to skip it
- Grouped by `thread_id` (the email id when there is none)
- A thread is urgent if any of its emails is; urgent threads first

#### What the final call sees · `daily_digest.py:97-117`
- `format_items`: each thread's first email and its last two
- Bodies cut to **800 chars** for urgent, **300** for normal
- The classifier's reason, as "Why it was flagged"
- System prompt fixes the layout (Urgent:, Also today:) and makes every urgent line name the company, project or site exactly as the email spells it: that is what the test looks for

#### Length · `daily_digest.py:141-168`
- Ask for **250 words**: the 300 limit minus a 50 margin, since the model's own count is approximate
- Still over 300 → one retry where the model rewrites its own digest shorter, kept only if it is shorter
- Never truncate: the test checks the text the model wrote, and a cut could drop an urgent name

#### Edge cases
- No email → "No email today."
- Only ignore mail → "Nothing needs your attention today."
- Empty reply → a digest built in code from the urgent subjects
- Part 2: the same pipeline is the `daily_digest` tool, on `aux_lm` (`toolset.py:219-223`)

## Code to point to

- cs329z_hw1/pipelines/daily_digest.py:47-60 classify_all, 16 workers
- cs329z_hw1/pipelines/daily_digest.py:66-89 aggregate, ignore dropped first
- cs329z_hw1/pipelines/daily_digest.py:97-117 format_items
- cs329z_hw1/pipelines/daily_digest.py:11-44 limits, SYSTEM_PROMPT, SHORTEN_PROMPT
- cs329z_hw1/pipelines/daily_digest.py:141-168 write_digest, one shorter rewrite
- cs329z_hw1/agent/toolset.py:219-223 daily_digest tool on aux_lm
