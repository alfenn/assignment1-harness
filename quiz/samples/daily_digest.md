# The daily digest

*P2 daily_digest*

> What does your digest pipeline do in code before the final LLM call, and what does that call see? How do you make sure the digest stays under 300 words and names every urgent item, without cutting the model's text?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

Before the final call everything is code. `classify_all` runs P1's `classify_priority` on every email at once, with a thread pool of 16 workers, and keeps the results in input order; `unknown` counts as normal. `aggregate` drops the ignore emails before grouping, so nothing from the ignore pile reaches the final prompt; I never ask the model to skip it. The rest are grouped by `thread_id` (or the email id when there is none), a thread is urgent if any of its emails is, and urgent threads come first.

The final call sees `format_items`: each thread's first email and its last two, bodies cut to 800 characters for urgent and 300 for normal, and the classifier's reason as "Why it was flagged". The system prompt fixes the layout (Urgent:, Also today:) and makes every urgent line name the company, project or site exactly as the email spells it, because that is what the test looks for.

For length I ask for 250 words, 300 minus a margin of 50, since the model's own count is approximate. If the digest still comes back over 300, there is one retry in which the model rewrites its own digest shorter, and I keep the rewrite only if it is shorter. I never truncate: the test checks the text the model wrote, and a cut could drop an urgent name.

Edge cases: no email gives "No email today.", only ignore mail gives "Nothing needs your attention today.", and an empty reply falls back to a digest built in code from the urgent subjects. In Part 2 the same pipeline is the `daily_digest` tool, run on `aux_lm`.

## Code to point to

- cs329z_hw1/pipelines/daily_digest.py:47-60 classify_all, 16 workers
- cs329z_hw1/pipelines/daily_digest.py:66-89 aggregate, ignore dropped first
- cs329z_hw1/pipelines/daily_digest.py:97-117 format_items
- cs329z_hw1/pipelines/daily_digest.py:11-44 limits, SYSTEM_PROMPT, SHORTEN_PROMPT
- cs329z_hw1/pipelines/daily_digest.py:141-168 write_digest, one shorter rewrite
- cs329z_hw1/agent/toolset.py:219-223 daily_digest tool on aux_lm
