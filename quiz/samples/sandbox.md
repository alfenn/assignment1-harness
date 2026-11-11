# The sandbox and its limits

*sandbox.py · memo Q9, Q10*

> On your machine, what does sandbox.py stop a command from doing, and what could a command still do? Then step back: what is the biggest limitation of your harness as a whole?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

**Short answer:** four layers: an allowlist, a scrubbed environment, a timeout with an output cap, and `sandbox-exec` with no network and no writes outside the workspace. python3 can still do a lot, which is acceptable because nothing it reads can leave the machine.

#### Four layers · `sandbox.py:1-46`
1. An allowlist on the program name of each simple command; also rejects paths, assignments, `$(...)`, backticks and here-documents
2. A scrubbed environment, so no API key, and a PATH made of links to the allowed programs
3. A timeout that kills the whole process group, and an output cap
4. On macOS, `sandbox-exec`: no network, no writes outside the workspace, no reads of my home directory or the repository, so not `.env`

#### What a command can still do
- Anything python3 can do within the timeout
- Use CPU, memory and disk
- Read files outside the home directory and the repository
- Change anything in the workspace copy
- Use allowlisted programs that start others: awk's system(), find -exec, xargs
- Leave the process group with os.setsid()
- The allowlist never checks arguments

#### Why that is acceptable
- The coding tasks need python3
- No network and no writes outside a temporary workspace, so nothing a jailed process reads can leave the machine
- The harness never starts a process itself: every command goes through `sandbox.run_terminal` (`terminal.py:150`)

#### Biggest limitation of the harness · `session.py:87-118`, `guardrails.py:60-69`
- Its behaviour fixes are regexes and prompts
- The announcement nudges and the injection detector match phrasings, so new wording gets past them
- What the agent does depends on prompt wording

#### From my own runs
- It sometimes searches the wrong corpus first
- It gives the generic PTO accrual table instead of saying it cannot see the user's balance
- Approvals are not logged or remembered (conversation 3 of my field notes)

## Code to point to

- cs329z_hw1/sandbox.py:1-46 the four layers
- cs329z_hw1/agent/terminal.py:150 every command goes through the sandbox
- cs329z_hw1/agent/session.py:87-118 regex nudges
- cs329z_hw1/agent/guardrails.py:60-69 regex injection detector
- cs329z_hw1/agent/guardrails.py:24-27 deny rules are a blocklist
- cs329z_hw1/agent/toolset.py:43-45 read_email stops at 8,000 characters
