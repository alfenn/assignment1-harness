# Memory across sessions

*P12 memory · memo Q7*

> What does a new session start with, and what does your agent store? Show me the prompt block and any place where the harness writes to memory itself. What was in the memory stores after your final evaluation run, and what was missing?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

Memory is one JSON file, `memory.json` in the memory_dir, holding a list of facts, each with an id, the fact and the date saved. Writes are atomic, a temp file and `os.replace`, under a lock, and an unreadable file is moved aside, not overwritten.

A new session starts with the prompt block in its system prompt: guidance on what is worth saving, then the newest facts that fit in context_budget // 16 tokens, listed oldest first with their ids and dates, and a line saying how many older facts `recall` can find. So a small store is loaded whole; recall is not the only way a fact reaches a new session.

The agent stores facts with `remember`, which ignores exact duplicates, never overwrites, and lists related facts so the model sees conflicts; the newer fact, the higher m- number, wins. `recall` ranks facts with my P3 BM25 over normalized words and lists the newest when nothing matches.

The harness also writes on its own: if a message asks to keep something and the model makes no `remember` call, it is nudged; if it still saves nothing, the harness saves the user's own words, and after that a correction is saved the same way. Facts addressed to AI agents are refused, because a planted instruction in memory would reach every later session's system prompt.

After my final run, 17 of 20 stores were empty, which is right for ordinary questions. Saved: the user is on the Platform team and "the spec" means the GridLens API spec; the user is on Customer Success in Rotterdam; and employee number 30918, then the corrected 31908. Missing: doc-office-days, where the user said they are a new hybrid employee in the Oakland office. Saving that was left to the model's judgment, and it did not save it.

## Code to point to

- cs329z_hw1/agent/memory.py:57-91 store format and guidance
- cs329z_hw1/agent/memory.py:273-295 prompt_block
- cs329z_hw1/agent/memory.py:221-269 remember and recall
- cs329z_hw1/agent/memory.py:95-143 nudge, fallback_fact, CORRECTION
- cs329z_hw1/agent/session.py:149-150 memory block in the system prompt
- cs329z_hw1/agent/session.py:293-321 the harness-side save
- cs329z_hw1/agent/guardrails.py:220-227 check_fact
- runs/sim-20261024-203750/ the final run and its stores
