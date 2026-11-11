# The termination rule

*P7 agent_loop · memo Q3*

> What does your loop do when the model says it will call a tool ("I'll look that up") but writes no call? Show me the branch and the limits on it, and tell me about a case where this rule backfired.

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

**Short answer:** a reply without a tool call does not end the turn straight away: empty replies are retried, a reply that announces a step gets a nudge, both capped per send, and the outer limits still hold.

#### Empty replies · `session.py:221-245`, `session.py:357-363`
- Retried with the same messages, up to `MAX_EMPTY` = **4** per send
- Kept out of the context: an "(empty reply)" placeholder I used to add got copied as the final answer

#### Announced, no call · `session.py:79-118`, `session.py:380-385`
- `announces_call` checks the first sentence and the last two against `_ANNOUNCES_CALL`
- The regex leaves out phrases like "let me know" and "I'll be"
- The loop sends `NUDGE`, which restates the call format
- Two related nudges share the budget: a first reply that says nothing was found or asks the user a question before any tool ran, and the memory nudge
- At most `MAX_NUDGES` = **3** per send, then the text is accepted as the answer, status done

#### Outer limits · `session.py:172-183`
- `max_turns` and `token_budget` checked before every model call
- **3** malformed replies in a row stop the run

#### Why
- In live runs the model often said "I'll look that up" and stopped
- Only about **60%** of first replies were tool calls
- The nudge fixed the most common P15 failure

#### Where it backfired (field notes)
- Conversation 5: the model refused and added "I'll check the policy" → nudged; when the nudges ran out, that unfinished promise was returned as the answer
- Conversation 4: the search-before-asking nudge rejected a correct plain question, asking for the manager's name
- It is a regex, so new phrasings slip past it

## Code to point to

- cs329z_hw1/agent/session.py:79-118 limits, regexes and nudges
- cs329z_hw1/agent/session.py:221-245 the no-call branch
- cs329z_hw1/agent/session.py:172-183 max_turns and token_budget
- cs329z_hw1/agent/session.py:357-363 _add_assistant, empty replies left out
- cs329z_hw1/agent/session.py:380-385 announces_call
