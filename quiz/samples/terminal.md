# Terminal observation policy

*P10 terminal · memo Q5*

> A command prints 600,000 characters. Tell me exactly what the model sees, and point to the code. Why did you choose this observation policy over keeping only the head and tail, or summarizing?

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

**Short answer:** one observation gets a fixed share of the budget: head and tail cut at line boundaries with a marker, the full output saved to a file the model can grep, and only exit 0 counts as ok.

#### Budget · `terminal.py:44-50`, `terminal.py:79-82`
- `context_budget // 8` tokens per observation, clamped to **300–2,000**
- At the evaluation's 16,000 budget: **2,000 tokens, 8,000 chars**, so the model sees under 2% of the 600,000

#### Shape · `terminal.py:104-142`
- Starts with a status line: the exit code, or timed out with the sandbox's reason
- Each stream labelled with its size in lines and characters
- A stream that fits is shown whole; otherwise head (**60%** of the allowance) + tail, both cut at line boundaries, with a marker saying how many characters and lines were left out
- stderr keeps at least **a third** of the allowance when both streams are long
- Full stream saved to `.outputs/cmd-N.stdout.txt` in the workspace; the observation names that file with ready-made `grep -n` and `sed -n` commands

#### Status · `terminal.py:145-175`
- Only exit code 0 is `ok`
- Non-zero exit, timeout or rejected command → raises `CommandFailed` → the registry makes it `tool_error` with the whole observation

#### Backstop · `session.py:267`
- The session caps every tool result at **a quarter of the budget** with `fit_result` before logging it, so the log holds exactly what the model saw
- Compaction stubs keep the `.outputs/` path

#### Why not just head and tail, or a summary
- Both can lose the exact line a later question needs; the live test asks about one line of a **218,000-char** listing
- The saved file makes the cut recoverable, and lets compaction drop old observations safely
- The tool description tells the model all of this

## Code to point to

- cs329z_hw1/agent/terminal.py:44-50 budget constants
- cs329z_hw1/agent/terminal.py:79-82 observation_chars
- cs329z_hw1/agent/terminal.py:104-142 _save and _stream
- cs329z_hw1/agent/terminal.py:145-175 make_run_terminal, CommandFailed
- cs329z_hw1/agent/session.py:267 fit_result backstop
