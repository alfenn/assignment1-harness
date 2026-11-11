# What the evaluation taught you

*P15 sim_eval · P16 field_notes*

> Reflect on the evaluation. What was the most common way your agent failed the simulated users, how did you find it, and what did you change? Did using the agent yourself for the field notes teach you anything the tests did not?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

The most common failure was the model announcing a step and stopping, or replying empty. I found it by reading the failed transcripts under `runs/`, by rerunning with a salt (`CS329Z_EVAL_SALT`) to see past the cache and measure the variance, and by probing first replies: of 96 first-turn calls only about 60% were tool calls, and about 11% were empty.

What I changed: a tool-first `SYSTEM_INTRO`, which raised first-turn tool calls from about 61% to 73%; empty replies retried unchanged and kept out of the context; and a broader announcement check with a nudge that shows the call format. Smaller fixes came from specific personas: ask with `ask_user`, then give the one answer that applies; "starting with" a year applies to later years; corrections reach memory; clearer injection wording; never write to /tmp. The final run in my notes, `runs/sim-20261024-203750`, scored 20 of 20, and 78 of 80 over four runs on the final code: about one miss per run, three or four above the 16 needed. My latest run, `runs/sim-20261026-185420`, was 20 of 20 again.

Using the agent myself taught me things the tests did not. The model wrote three identical calls in one reply, which is why `repeated_call` exists. It searched the docs first for a question only the email archive could answer. The transcript does not record that I approved a command. And the nudges rejected a correct plain question and accepted an unfinished promise.

What is still brittle: the regex nudges, prompt sensitivity, and about one conversation per run of variance. The next step I would take is to stop matching phrasings, and instead check whether a reply without a call actually answers the question.

## Code to point to

- cs329z_hw1/agent/session.py:120 SYSTEM_INTRO
- cs329z_hw1/agent/session.py:221-245 nudges and empty retries
- cs329z_hw1/agent/protocol.py:188-204 repeated_call
- cs329z_hw1/agent/interactive.py:45-56 ask_user guidance
- runs/sim-20261024-203750/ the final run in NOTES.md
- runs/sim-20261026-185420/ the latest run
- field_notes.pdf the field notes
