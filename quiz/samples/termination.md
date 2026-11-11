# The termination rule

*P7 agent_loop · memo Q3*

> What does your loop do when the model says it will call a tool ("I'll look that up") but writes no call? Show me the branch and the limits on it, and tell me about a case where this rule backfired.

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

In `AgentSession.send`, a reply with no tool call does not end the turn straight away. An empty reply is retried with the same messages, up to `MAX_EMPTY` = 4 per send, and kept out of the context: I used to add an "(empty reply)" placeholder, and the model copied it as its final answer.

A reply that announces a step is caught by `announces_call`, which checks the first sentence and the last two against `_ANNOUNCES_CALL`; that regex leaves out phrases like "let me know" and "I'll be". The loop then sends `NUDGE`, which restates the call format. Two related nudges share the same budget: one when the first reply says nothing was found, or asks the user a question, before any tool ran, and the memory nudge. There are at most `MAX_NUDGES` = 3 per send; after that the text is accepted as the answer with status done. The outer limits still hold: `max_turns` and `token_budget` are checked before every model call, and three malformed replies in a row stop the run.

Why: in live runs the model often said "I'll look that up" and stopped. Only about 60% of first replies were tool calls, and the nudge fixed the most common P15 failure.

Where it backfired, from my field notes: in conversation 5 the model refused and added "I'll check the policy"; it was nudged, and when the nudges ran out that unfinished promise was returned as the answer. In conversation 4 the search-before-asking nudge rejected a correct plain question, asking for the manager's name. And it is a regex, so new phrasings slip past it.

## Code to point to

- cs329z_hw1/agent/session.py:79-118 limits, regexes and nudges
- cs329z_hw1/agent/session.py:221-245 the no-call branch
- cs329z_hw1/agent/session.py:172-183 max_turns and token_budget
- cs329z_hw1/agent/session.py:357-363 _add_assistant, empty replies left out
- cs329z_hw1/agent/session.py:380-385 announces_call
