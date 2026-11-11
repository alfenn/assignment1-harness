# Email priority in one call

*P1 priority*

> Walk me through run_priority. How does your prompt ask for the label and the reason, and how does your parser read the reply? What do you return when the reply names no label, and what happens when the reply is cut off?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

`run_priority` makes one LM call per email, in `classify_priority`. The system prompt embeds the whole `data/priority_rubric.md`, read once at import, and asks for exactly two lines: `LABEL:` urgent, normal or ignore, and `REASON:` one sentence. I show the email with From, To, Date, Subject and body, and I rewrite the date with its weekday, so the model can count working days the way the rubric asks. My code never computes deadlines.

`parse_priority` reads the strict `LABEL:` line first. If it is missing, it takes the last label word anywhere in the reply, case-insensitive, because a model that ignores the format usually reasons first and states its conclusion last. If no label word appears at all, I return `unknown`, as the tests require, rather than guess. The reason comes from the `REASON:` line, otherwise a fixed placeholder, so it is never empty.

If the reply is cut off, I catch `OutputTruncated` and parse its partial text, so a reply that already gave its label still counts. `BudgetExceeded`, a missing key or a network error propagate on purpose: those are setup problems, not model output.

Why the rubric word for word: grading uses 60 held-out emails labelled under the same rubric, so a prompt tuned to the public labels would not carry over. The weakness I know about: with the fallback, a free-form reply ending in "not urgent" parses as urgent. The strict `LABEL:` line is what prevents that in practice.

## Code to point to

- cs329z_hw1/pipelines/priority.py:12-20 rubric and SYSTEM_PROMPT
- cs329z_hw1/pipelines/priority.py:23-27 reply patterns and placeholder reason
- cs329z_hw1/pipelines/priority.py:30-42 _format_email, date with weekday
- cs329z_hw1/pipelines/priority.py:45-57 parse_priority
- cs329z_hw1/pipelines/priority.py:60-72 classify_priority, OutputTruncated
