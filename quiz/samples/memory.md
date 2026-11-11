# Memory across sessions

*P12 memory · memo Q7*

> What does a new session start with, and what does your agent store? Show me the prompt block and any place where the harness writes to memory itself. What was in the memory stores after your final evaluation run, and what was missing?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

**Short answer:** one JSON file of dated facts. The newest facts that fit go straight into a new session's system prompt, the rest through BM25 `recall`, and the harness saves on its own when the model does not.

#### Store · `memory.py:57-91`
- One JSON file, `memory.json` in the memory_dir: a list of facts, each with an id, the fact and the date saved
- Atomic writes (a temp file and `os.replace`) under a lock
- An unreadable file is moved aside, not overwritten

#### A new session · `memory.py:273-295`, `session.py:149-150`
- A prompt block in its system prompt: guidance on what is worth saving
- Then the newest facts that fit in `context_budget // 16` tokens, listed oldest first with their ids and dates
- A line saying how many older facts `recall` can find
- So a small store is loaded whole; recall is not the only way a fact reaches a new session

#### Tools · `memory.py:221-269`
- `remember` ignores exact duplicates, never overwrites, and lists related facts so the model sees conflicts
- The newer fact, the higher m- number, wins
- `recall` ranks facts with my P3 BM25 over normalized words; lists the newest when nothing matches

#### The harness saves too · `memory.py:95-143`, `session.py:293-321`
- A message asks to keep something and the model makes no `remember` call → nudged
- Still nothing saved → the harness saves the user's own words; after that, a correction is saved the same way
- Facts addressed to AI agents are refused (`guardrails.py:220-227`): a planted instruction in memory would reach every later session's system prompt

#### Final run · `runs/sim-20261024-203750/`
- **17 of 20** stores empty: right for ordinary questions
- Saved: the user is on the Platform team and "the spec" means the GridLens API spec; the user is on Customer Success in Rotterdam; employee number 30918, then the corrected 31908
- Missing: doc-office-days, where the user said they are a new hybrid employee in the Oakland office; saving that was left to the model's judgment, and it did not save it

## Code to point to

- cs329z_hw1/agent/memory.py:57-91 store format and guidance
- cs329z_hw1/agent/memory.py:273-295 prompt_block
- cs329z_hw1/agent/memory.py:221-269 remember and recall
- cs329z_hw1/agent/memory.py:95-143 nudge, fallback_fact, CORRECTION
- cs329z_hw1/agent/session.py:149-150 memory block in the system prompt
- cs329z_hw1/agent/session.py:293-321 the harness-side save
- cs329z_hw1/agent/guardrails.py:220-227 check_fact
- runs/sim-20261024-203750/ the final run and its stores
