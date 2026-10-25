"""Problem 13 (interactive): approvals, steering, and the user in the loop.

The session talks to the human only through ``config.user`` (a ``UserIO``,
``cs329z_hw1/user.py``). This module holds the policy; ``session.py`` calls it
at two points of the loop:

* **Before every model call**, ``poll_steering`` calls
  ``user.pending_message()`` exactly once. A message the user sent while the
  agent was working becomes a "user" event and is in that model call.
* **Between validating a call and running it**, ``check_approval`` decides
  whether the call needs the user's approval and, if it does, asks for it.

The approval policy, in confirm mode:

* A tool with ``read_only=False`` (in the Cardinal toolset only
  ``run_terminal``; ``write_note`` among the fixture tools) asks
  ``user.approve(call)`` once per call, before it runs.
* Read-only tools never ask. They cannot change anything outside the
  agent's own state, so asking would only train the user to click "yes";
  the approvals that matter would drown in ones that don't.
* ``ask_user``, ``remember`` and ``recall`` never ask, whatever their flag
  says: ``ask_user`` already is a question to the user, and the memory tools
  touch only the agent's own store under ``config.memory_dir``.
* A call the registry rejects (unknown tool, invalid arguments) never gets
  here: it is a malformed reply, not something to ask the user about.
* Fail closed: if ``approve`` raises or returns something that is not a
  clear yes, the call is denied.

In auto mode ``approve`` is never called. The mode is only changed by
``AgentConfig.mode`` and ``session.set_mode``; nothing the model or a tool
writes can change it.
"""

from __future__ import annotations

import copy
from typing import Any, Optional

from cs329z_hw1.types import ToolCall, ToolResult, ToolSpec

# Tools that never ask for approval, in either mode.
NEVER_ASK = frozenset({"ask_user", "remember", "recall"})

# Added to the system prompt when a user is connected.
PROMPT_NOTE = (
    "A user is connected to this session. Calls that change something outside your own "
    "memory (such as running a terminal command) may need their approval first. If a call "
    "is denied, it did not run: do not repeat it unchanged; follow the user's reason, try "
    "another way, or tell the user what you could not do. Use ask_user when a request is "
    "ambiguous and guessing would give a wrong answer. A message marked as sent while you "
    "were working comes from the user and takes precedence over their earlier request "
    "where the two conflict."
)

STEERING_PREFIX = "[Message from the user, sent while you were working:]"

NO_REASON = "The user gave no reason."


def needs_approval(mode: str, tool: Optional[ToolSpec]) -> bool:
    """Whether a validated call to ``tool`` must be approved before it runs."""
    if mode != "confirm" or tool is None:
        return False
    if tool.name in NEVER_ASK:
        return False
    return not tool.read_only


def denial(name: str, reason: str) -> ToolResult:
    """The result the model sees for a call the user refused."""
    reason = " ".join(str(reason or "").split()) or NO_REASON
    return ToolResult(
        "denied",
        f"The user denied this {name} call, so it was not run. Their reason: {reason}\n"
        "Do not repeat the same call. Follow the reason if it says what to do instead, "
        "otherwise continue without it or tell the user what you could not do.",
    )


def check_approval(user: Any, mode: str, tool: Optional[ToolSpec], call: ToolCall) -> Optional[ToolResult]:
    """None if the call may run; otherwise the "denied" result to log."""
    if not needs_approval(mode, tool):
        return None
    if user is None:
        return denial(call.name, "No user is connected to approve it, and this tool needs approval in confirm mode.")
    # The user gets a copy: whatever they do to it cannot change what runs.
    request = ToolCall(call.name, copy.deepcopy(call.args))
    try:
        decision = user.approve(request)
    except Exception as exc:  # fail closed
        return denial(call.name, f"The approval request failed ({type(exc).__name__}: {exc}).")
    if getattr(decision, "approved", False) is True:
        return None
    return denial(call.name, getattr(decision, "reason", "") or "")


def poll_steering(user: Any) -> Optional[str]:
    """The message the user sent while the agent was working, or None.
    Called exactly once before every model call."""
    if user is None:
        return None
    try:
        message = user.pending_message()
    except Exception:  # a broken channel must not stop the run
        return None
    if message is None:
        return None
    message = str(message)
    return message if message.strip() else None


def format_steering(message: str) -> str:
    """How a steering message is shown to the model."""
    return f"{STEERING_PREFIX}\n{message}"
