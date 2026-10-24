"""Problem 7 (agent_loop): the agent's core loop.

One ``AgentSession`` holds one conversation. ``send`` appends the user's
message and alternates model calls and tool calls until the model answers in
plain text or a limit (max_turns, token_budget, three malformed replies in a
row) stops it.

Two records are kept side by side:

* ``transcript``: the append-only event log the tests read.
* ``_messages``: the conversation as the model sees it (user/assistant
  messages, without the system prompt). Tool results and parse errors are
  sent back as user messages, using the strings stored in the transcript.
"""

from __future__ import annotations

import copy
from typing import Optional

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
    def __init__(self, lm: LMCallable, tools: list[ToolSpec], config: AgentConfig):
        self.lm = lm
        self.config = config
        self.registry = ToolRegistry(tools)
        self.mode = config.mode
        self.transcript: list[dict] = []
        self._messages: list[dict] = []
        self._system = SYSTEM_INTRO + "\n\n" + render_tools(self.registry.schemas())

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

            messages = [{"role": "system", "content": self._system}] + self._messages
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
            result = self.registry.execute(call.name, call.args)
            self.transcript.append({"type": "tool_call", "name": call.name, "args": copy.deepcopy(call.args)})
            if not result.content.strip():
                result = ToolResult(result.status, "(no output)")
            self.transcript.append(
                {"type": "tool_result", "name": call.name, "status": result.status, "content": result.content}
            )
            self._messages.append({"role": "user", "content": format_tool_result(call.name, result)})

            if result.status in MALFORMED_STATUSES:
                malformed += 1
                if malformed >= MAX_MALFORMED:
                    return self._malformed_stop()
            else:
                malformed = 0

    # ----------------------------------------------------------- helpers ----

    def _add_user(self, content: str) -> None:
        self.transcript.append({"type": "user", "content": content})
        self._messages.append({"role": "user", "content": content})

    def _add_assistant(self, content: str) -> None:
        self.transcript.append({"type": "assistant", "content": content})
        # Some providers reject an empty assistant message.
        self._messages.append({"role": "assistant", "content": content or "(empty reply)"})

    def _add_error(self, content: str) -> None:
        self.transcript.append({"type": "error", "content": content})
        self._messages.append({"role": "user", "content": content})

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
        return AgentSession(lm, build_tools(config, aux_lm), config)
    tools = list(tools)
    listed = {t.name for t in tools}
    tools += [t for t in extra_tools(config, aux_lm) if t.name not in listed]
    return AgentSession(lm, tools, config)
