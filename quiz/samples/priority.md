# Email priority in one call

*P1 priority*

> Walk me through run_priority. How does your prompt ask for the label and the reason, and how does your parser read the reply? What do you return when the reply names no label, and what happens when the reply is cut off?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

**Short answer:** one LM call per email with the rubric word for word in the prompt, a strict two-line reply, a lenient parser, and `unknown` when there is no label.

#### Prompt · `priority.py:12-42`
- One call per email, in `classify_priority`
- System prompt embeds all of `data/priority_rubric.md`, read once at import
- Asks for exactly two lines: `LABEL:` urgent / normal / ignore, and `REASON:` one sentence
- Email shown with From, To, Date, Subject and body
- Date rewritten with its weekday, so the model can count working days; my code never computes deadlines

#### Parsing · `priority.py:45-57`
- Strict `LABEL:` line first
- Fallback: the last label word anywhere, case-insensitive (a model that ignores the format reasons first and concludes last)
- No label word at all → `unknown`, as the tests require; never guess
- Reason from the `REASON:` line, else a fixed placeholder, so never empty

#### Errors · `priority.py:60-72`
- `OutputTruncated` caught → parse its partial text, so a label already given still counts
- `BudgetExceeded`, a missing key, network errors propagate on purpose: setup problems, not model output

#### Why, and the weakness
- Rubric word for word: grading uses **60 held-out emails** labelled under the same rubric, so a prompt tuned to the public labels would not carry over
- Known weakness: through the fallback, a free-form reply ending in "not urgent" parses as urgent; the strict `LABEL:` line prevents that in practice

## Code to point to

- cs329z_hw1/pipelines/priority.py:12-20 rubric and SYSTEM_PROMPT
- cs329z_hw1/pipelines/priority.py:23-27 reply patterns and placeholder reason
- cs329z_hw1/pipelines/priority.py:30-42 _format_email, date with weekday
- cs329z_hw1/pipelines/priority.py:45-57 parse_priority
- cs329z_hw1/pipelines/priority.py:60-72 classify_priority, OutputTruncated
