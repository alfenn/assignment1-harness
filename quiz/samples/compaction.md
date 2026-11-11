# Compaction policy

*P11 compaction · memo Q6*

> How does your compaction work? When does it trigger, what goes first, and what do you never let go of? How do constraints the user stated survive after the messages that carried them have left the context?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

**Short answer:** compaction only changes what is sent. It is lazy, drops old tool results first, then folds old messages into a running summary, and the user's constraints go first in that summary, word for word.

#### An overlay, not edits
- The transcript and the session's messages are never edited
- The `Compactor` keeps an overlay: which messages are folded into the summary, which tool results are stubbed, and the running summary

#### When · `compaction.py:137-148`
- Lazy: `build` compacts only when the next call would exceed `context_budget`
- Then shrinks to **60%** of it, so the next calls have headroom and `aux_lm` is not called every turn

#### What goes first · `compaction.py:107-120`, `compaction.py:172-202`
- Old tool results, oldest first → a stub keeping tool name, status, size, the first **160 chars** and any `.outputs/` path
- Not enough → the oldest messages folded into a summary written by `aux_lm` (`compaction.py:204-226`)
- An assistant call stays together with its result
- The previous summary is passed back in, so it accumulates
- The summary is appended to the system message, so the first message still names every tool

#### Never compacted · `session.py:333-338`
- The system prompt, the user message being worked on, this send's steering messages, and the newest message, which must appear verbatim
- If even those do not fit, `_squeeze` cuts the summary, then the longest protected message, in the copy that is sent, so the budget always holds (`compaction.py:236-252`)

#### Constraints survive · `compaction.py:49-76`
- The summary instructions put "User requirements and constraints" first, copied word for word and never dropped unless the user withdraws them, before "Progress"
- If `aux_lm` fails, the fallback summary keeps the previous summary and the user's own words
- Tool results are the bulk of the context and the cheapest to lose; constraints carried word for word survive any number of compactions

## Code to point to

- cs329z_hw1/agent/compaction.py:49-76 TARGET_FRACTION and the summary prompt
- cs329z_hw1/agent/compaction.py:107-120 _stub
- cs329z_hw1/agent/compaction.py:137-148 build, the lazy trigger
- cs329z_hw1/agent/compaction.py:172-202 _compact
- cs329z_hw1/agent/compaction.py:204-226 _summarize
- cs329z_hw1/agent/compaction.py:236-252 _squeeze
- cs329z_hw1/agent/session.py:333-338 protected messages
