# The sandbox and its limits

*sandbox.py · memo Q9, Q10*

> On your machine, what does sandbox.py stop a command from doing, and what could a command still do? Then step back: what is the biggest limitation of your harness as a whole?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

`sandbox.py` has four layers. One, an allowlist on the program name of each simple command, which also rejects paths, assignments, `$(...)`, backticks and here-documents. Two, a scrubbed environment, so no API key, and a PATH made of links to the allowed programs. Three, a timeout that kills the whole process group, and an output cap. Four, on macOS, `sandbox-exec`: no network, no writes outside the workspace, and no reads of my home directory or the repository, so not `.env`.

What a command can still do: anything python3 can do within the timeout; use CPU, memory and disk; read files outside the home directory and the repository; change anything in the workspace copy; use allowlisted programs that start others, such as awk's system(), find -exec or xargs; and leave the process group with os.setsid(). The allowlist never checks arguments. That is acceptable here because the coding tasks need python3, and with no network and no writes outside a temporary workspace, nothing a jailed process reads can leave the machine. The harness never starts a process itself: every command goes through `sandbox.run_terminal`.

The biggest limitation of the harness as a whole: its behaviour fixes are regexes and prompts. The announcement nudges and the injection detector match phrasings, so new wording gets past them, and what the agent does depends on prompt wording. From my own runs: it sometimes searches the wrong corpus first; it gives the generic PTO accrual table instead of saying it cannot see the user's balance; and approvals are not logged or remembered, which I noticed in conversation 3 of my field notes.

## Code to point to

- cs329z_hw1/sandbox.py:1-46 the four layers
- cs329z_hw1/agent/terminal.py:150 every command goes through the sandbox
- cs329z_hw1/agent/session.py:87-118 regex nudges
- cs329z_hw1/agent/guardrails.py:60-69 regex injection detector
- cs329z_hw1/agent/guardrails.py:24-27 deny rules are a blocklist
- cs329z_hw1/agent/toolset.py:43-45 read_email stops at 8,000 characters
