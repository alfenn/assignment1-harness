# Approvals, steering and ask_user

*P13 interactive · memo Q8*

> In confirm mode, which calls run without approval, and why is that safe? How is a denial written back to the model, and what happens if approve() raises? Then show me where a message the user sends mid-run enters the loop.

<!-- source: Written by Claude from the rubric and your code at c425e97 -->

## Answer

**Short answer:** confirm mode asks only for tools that can change something, which in Cardinal is just `run_terminal`. Approval comes after validation and the guard, fails closed, and a denial lets the run continue.

#### What needs approval · `interactive.py:42`, `interactive.py:63-97`
- Only tools with read_only=False, and never `ask_user`, `remember` or `recall`
- In the Cardinal toolset: just `run_terminal`
- A read-only tool cannot change anything outside the agent's own state
- Its real risk is prompt injection in what it returns, and approving a search would not stop that
- Asking for every read would train the user to click yes without reading

#### Order, and failing closed · `session.py:251-260`
- Validated first, and the P14 guard runs before approval too, so the user is never asked about a call that could not run
- `check_approval` fails closed: no user connected, an exception from `approve()`, or anything not a clear yes is a denial
- The user gets a deep copy of the arguments, so nothing they do to it changes what runs

#### A denial
- Goes back as a `denied` result with the user's reason, or "The user gave no reason."
- Tells the model not to repeat the same call and to follow the reason
- The run continues, and denied does not count as malformed

#### Steering · `interactive.py:100-117`, `session.py:185-187`, `session.py:350-355`
- Before every model call the loop calls `pending_message()` exactly once, in `poll_steering`; a broken channel counts as no message
- `_add_steering` logs the words as a user event and shows them after a steering prefix; protected from compaction until the send ends
- The prompt note says such a message wins where it conflicts with the earlier request
- `ask_user` returns the user's answer as an ok result
- The mode only changes through `set_mode`

## Code to point to

- cs329z_hw1/agent/interactive.py:42 NEVER_ASK
- cs329z_hw1/agent/interactive.py:63-97 needs_approval, denial, check_approval
- cs329z_hw1/agent/interactive.py:100-117 steering
- cs329z_hw1/agent/session.py:185-187 poll before each model call
- cs329z_hw1/agent/session.py:251-260 validate, guard, approve, run
- cs329z_hw1/agent/session.py:350-355 _add_steering
