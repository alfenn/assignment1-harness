# What the evaluation taught you

*P15 sim_eval · P16 field_notes*

> Reflect on the evaluation. What was the most common way your agent failed the simulated users, how did you find it, and what did you change? Did using the agent yourself for the field notes teach you anything the tests did not?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

**Short answer:** the most common failure was announcing a step and stopping, or replying empty. I found it in failed transcripts, salted reruns and first-reply probes, and fixed it with a tool-first prompt, empty-reply retries and a nudge. Using the agent myself turned up problems the tests never did.

#### How I found it
- Read the failed transcripts under `runs/`
- Reran with a salt (`CS329Z_EVAL_SALT`) to see past the cache and measure the variance
- Probed first replies: of **96** first-turn calls, only about **60%** were tool calls and about **11%** were empty

#### What I changed · `session.py:120`, `session.py:221-245`
- A tool-first `SYSTEM_INTRO`: first-turn tool calls up from about **61% to 73%**
- Empty replies retried unchanged and kept out of the context
- A broader announcement check, with a nudge that shows the call format
- Smaller fixes from specific personas: ask with `ask_user`, then give the one answer that applies (`interactive.py:45-56`); "starting with" a year applies to later years; corrections reach memory; clearer injection wording; never write to /tmp

#### Results
- Final run in my notes, `runs/sim-20261024-203750/`: **20 of 20**
- **78 of 80** over four runs on the final code: about one miss per run, three or four above the 16 needed
- Latest run, `runs/sim-20261026-185420/`: **20 of 20** again

#### What using it myself taught me
- The model wrote three identical calls in one reply: that is why `repeated_call` exists (`protocol.py:188-204`)
- It searched the docs first for a question only the email archive could answer
- The transcript does not record that I approved a command
- The nudges rejected a correct plain question and accepted an unfinished promise

#### Still brittle, and the next step
- The regex nudges, prompt sensitivity, and about one conversation per run of variance
- Next: stop matching phrasings, and instead check whether a reply without a call actually answers the question

## Code to point to

- cs329z_hw1/agent/session.py:120 SYSTEM_INTRO
- cs329z_hw1/agent/session.py:221-245 nudges and empty retries
- cs329z_hw1/agent/protocol.py:188-204 repeated_call
- cs329z_hw1/agent/interactive.py:45-56 ask_user guidance
- runs/sim-20261024-203750/ the final run in NOTES.md
- runs/sim-20261026-185420/ the latest run
- field_notes.pdf the field notes
