"""Problem 7 (agent_loop): the agent's core loop.

One ``AgentSession`` holds one conversation. ``send`` appends the user's
message and alternates model calls and tool calls until the model answers in
plain text or a limit (max_turns, token_budget, three malformed replies in a
row) stops it.

Two records are kept side by side:

* ``transcript``: the append-only event log the tests read.
* ``_messages``: the whole conversation in the model's format (user/assistant
  messages, without the system prompt). Tool results and parse errors are
  sent back as user messages, using the strings stored in the transcript.
  ``_kinds`` says what each message is (user, assistant, tool, error).

Problem 11 (compaction): neither list is ever shortened. Each model call's
messages are built by ``Compactor.build`` (``compaction.py``), which shows
the model a shortened view when the full conversation would exceed
``config.context_budget``.

Problem 12 (memory): when the session has the ``remember`` tool and
``config.memory_dir`` is set, the system prompt ends with the memory block
(``MemoryStore.prompt_block``): how to use memory, and the newest stored
facts that fit, read once when the session is created.

Problem 13 (interactive): the policy lives in ``interactive.py``. Before
every model call the loop polls ``config.user.pending_message()`` once; a
steering message becomes a "user" event and stays protected from compaction
until the send ends. A call that validates is checked against the mode
(``self.mode``, changed only by ``set_mode``) before it runs; a refused call
is logged as "tool_call" + "tool_result" with status "denied" and the run
continues.
"""

from __future__ import annotations

import copy
from typing import Optional

from cs329z_hw1.agent import interactive
from cs329z_hw1.agent.compaction import Compactor, fit_result
from cs329z_hw1.agent.memory import MemoryStore
from cs329z_hw1.agent.protocol import (
    format_parse_error,
    format_tool_result,
    parse_response,
    render_tools,
)
from cs329z_hw1.agent.registry import ToolRegistry
from cs329z_hw1.agent.toolset import build_tools, extra_tools
from cs329z_hw1.llm import OutputTruncated
from cs329z_hw1.tokens import count_message_tokens, count_tokens
from cs329z_hw1.types import AgentConfig, AgentResult, LMCallable, ToolResult, ToolSpec

MAX_MALFORMED = 3
MALFORMED_STATUSES = ("unknown_tool", "invalid_args")

SYSTEM_INTRO = """You are Cardinal, a helpful assistant for the employees of a company. Work step by step: call a tool when you need information or need to act, read its result, and continue until you can answer. Base your answers on what the tools return; do not invent facts. When you are done, reply in plain text with your final answer."""


class AgentSession:
    def __init__(
        self,
        lm: LMCallable,
        tools: list[ToolSpec],
        config: AgentConfig,
        aux_lm: Optional[LMCallable] = None,
    ):
        self.lm = lm
        self.config = config
        self.registry = ToolRegistry(tools)
        self.mode = config.mode
        self.transcript: list[dict] = []
        self._messages: list[dict] = []
        self._kinds: list[str] = []
        self._current_user = 0  # index in _messages of the message being worked on
        self._steering: list[int] = []  # indices in _messages of this send's steering messages
        self._system = SYSTEM_INTRO + "\n\n" + render_tools(self.registry.schemas())
        if config.user is not None:
            self._system += "\n\n" + interactive.PROMPT_NOTE
        if config.memory_dir is not None and "remember" in self.registry.names():
            self._system += "\n\n" + MemoryStore(config.memory_dir).prompt_block(config.context_budget)
        self.compactor = Compactor(aux_lm or lm, config.context_budget, self._system)

    # ------------------------------------------------------------ public ----

    def set_mode(self, mode: str) -> None:
        if mode not in ("confirm", "auto"):
            raise ValueError(f"mode must be 'confirm' or 'auto', got {mode!r}")
        self.mode = mode

    def send(self, user_message: str) -> AgentResult:
        self._add_user(user_message)
        turns = 0
        spent = 0
        malformed = 0

        while True:
            if turns >= self.config.max_turns:
                return self._result(
                    f"I stopped after {turns} steps without finishing. "
                    "Ask me to continue if you want me to keep going.",
                    "max_turns",
                )
            if spent >= self.config.token_budget:
                return self._result(
                    "I stopped because this request used up its token budget before I "
                    "could finish. Ask me to continue if you want me to keep going.",
                    "token_budget",
                )

            steer = interactive.poll_steering(self.config.user)
            if steer is not None:
                self._add_steering(steer)

            messages = self._context()
            turns += 1
            try:
                reply = self.lm(messages)
            except OutputTruncated as exc:
                spent += count_message_tokens(messages) + count_tokens(exc.text or "")
                malformed += 1
                self._add_assistant(exc.text or "")
                self._add_error(
                    format_parse_error(
                        "your reply was cut off because it hit the output length limit. "
                        "Write a shorter reply."
                    )
                )
                if malformed >= MAX_MALFORMED:
                    return self._malformed_stop()
                continue

            reply = reply if isinstance(reply, str) else str(reply)
            spent += count_message_tokens(messages) + count_tokens(reply)
            self._add_assistant(reply)
            parsed = parse_response(reply)

            if parsed.error is not None:
                malformed += 1
                self._add_error(format_parse_error(parsed.error))
                if malformed >= MAX_MALFORMED:
                    return self._malformed_stop()
                continue

            if parsed.tool_call is None:
                text = parsed.text or reply.strip() or "(The model gave an empty answer.)"
                return self._result(text, "done")

            call = parsed.tool_call
            self.transcript.append({"type": "tool_call", "name": call.name, "args": copy.deepcopy(call.args)})
            # Validate first: a call the registry rejects is never sent for approval.
            result = self.registry.validate(call.name, call.args)
            if result is None:
                result = interactive.check_approval(
                    self.config.user, self.mode, self.registry.get(call.name), call
                )
            if result is None:
                result = self.registry.execute(call.name, call.args)
            if not result.content.strip():
                result = ToolResult(result.status, "(no output)")
            # Cap a huge result before it is logged, so the event holds what the model sees.
            result = ToolResult(result.status, fit_result(result.content, self.config.context_budget))
            self.transcript.append(
                {"type": "tool_result", "name": call.name, "status": result.status, "content": result.content}
            )
            self._append("user", format_tool_result(call.name, result), "tool")

            if result.status in MALFORMED_STATUSES:
                malformed += 1
                if malformed >= MAX_MALFORMED:
                    return self._malformed_stop()
            else:
                malformed = 0

    # ----------------------------------------------------------- helpers ----

    def _context(self) -> list[dict]:
        """This call's messages: the system prompt and the (compacted) conversation.
        The current user message, this send's steering messages and the
        newest message are never compacted."""
        protected = {self._current_user, len(self._messages) - 1, *self._steering}
        return self.compactor.build(self._messages, self._kinds, protected)

    def _append(self, role: str, content: str, kind: str) -> None:
        self._messages.append({"role": role, "content": content})
        self._kinds.append(kind)

    def _add_user(self, content: str) -> None:
        self.transcript.append({"type": "user", "content": content})
        self._current_user = len(self._messages)
        self._steering = []
        self._append("user", content, "user")

    def _add_steering(self, content: str) -> None:
        """A message the user sent mid-send: logged as they wrote it, shown
        to the model marked as mid-run, protected until the send ends."""
        self.transcript.append({"type": "user", "content": content})
        self._steering.append(len(self._messages))
        self._append("user", interactive.format_steering(content), "user")

    def _add_assistant(self, content: str) -> None:
        self.transcript.append({"type": "assistant", "content": content})
        # Some providers reject an empty assistant message.
        self._append("assistant", content or "(empty reply)", "assistant")

    def _add_error(self, content: str) -> None:
        self.transcript.append({"type": "error", "content": content})
        self._append("user", content, "error")

    def _malformed_stop(self) -> AgentResult:
        return self._result(
            "I stopped because my last few replies had malformed tool calls. "
            "Please try again or rephrase the request.",
            "malformed",
        )

    def _result(self, text: str, status: str) -> AgentResult:
        return AgentResult(text=text, status=status, transcript=copy.deepcopy(self.transcript))


def create_session(
    lm: LMCallable, tools: Optional[list[ToolSpec]], config: AgentConfig
) -> AgentSession:
    aux_lm = config.aux_lm if config.aux_lm is not None else lm
    if tools is None:
        return AgentSession(lm, build_tools(config, aux_lm), config, aux_lm)
    tools = list(tools)
    listed = {t.name for t in tools}
    tools += [t for t in extra_tools(config, aux_lm) if t.name not in listed]
    return AgentSession(lm, tools, config, aux_lm)
