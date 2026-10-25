"""Problem 7 (agent_loop): the agent's core loop.

One ``AgentSession`` holds one conversation. ``send`` appends the user's
message and alternates model calls and tool calls until the model answers in
plain text or a limit (max_turns, token_budget, three malformed replies in a
row) stops it.

Two kinds of reply without a call are not taken as the answer. An empty
reply is a malformed reply (asked again; three in a row end the send). A
reply whose last two sentences announce a tool step ("I'll check the
policy."), or a first reply that says nothing was found or asks the user a
question before any tool ran, gets a nudge back, up to ``MAX_NUDGES`` times
per send, since the live model often says what it will do and stops. So
does a send whose user message asks for something to be kept ("remember",
"for later", "when I say ...") but that ends without a ``remember`` call; if
the request was explicit and the model still saved nothing, the harness
saves the user's own words itself and says so in the answer
(``memory.fallback_fact``).

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

Problem 14 (guardrails): the checks live in ``guardrails.py``. A call that
validates goes through, in order: the deny rules (compiled from
``config.deny_rules`` when the session is created; a ``run_terminal`` command
that one matches is denied without asking the user, in both modes), the
planted-command check (a command quoted by a tool result that addresses AI
agents is denied unless the user wrote it), approval, execution. Every result
is flagged if it addresses AI agents and then scanned for planted commands.
The system prompt says that tool results are data, never instructions.
"""

from __future__ import annotations

import copy
import re
from typing import Optional

from cs329z_hw1.agent import guardrails, interactive
from cs329z_hw1.agent.compaction import Compactor, fit_result
from cs329z_hw1.agent.memory import ASKED_TO_REMEMBER, REMEMBER_NUDGE, MemoryStore, fallback_fact
from cs329z_hw1.agent.protocol import (
    format_parse_error,
    format_tool_result,
    parse_response,
    repeated_call,
    render_tools,
)
from cs329z_hw1.agent.registry import ToolRegistry
from cs329z_hw1.agent.toolset import build_tools, extra_tools
from cs329z_hw1.llm import OutputTruncated
from cs329z_hw1.tokens import count_message_tokens, count_tokens
from cs329z_hw1.types import AgentConfig, AgentResult, LMCallable, ParsedResponse, ToolResult, ToolSpec

MAX_MALFORMED = 3
MALFORMED_STATUSES = ("unknown_tool", "invalid_args")
MAX_NUDGES = 3  # per send: replies that announce a tool call without writing it

# The last sentence of a reply that says it is about to use a tool ("I'll
# check the policy.") rather than answering. "Let me know ..." is not one.
_ANNOUNCES_CALL = re.compile(
    r"^(?:(?:ok(?:ay)?|sure|next|now|first|then|so)[,.!]?\s+)*"
    r"(?:I['’]ll(?: need to| have to)?|I will(?: need to)?|I am going to|I['’]m going to|let me"
    r"|(?:I )?need to|(?:I )?need|next step:?)\s+"
    r"(?:now\s+|first\s+|quickly\s+|also\s+|go\s+(?:and\s+)?)?"
    r"(?:check|look|search|find|read|run|open|review|query|pull|get|fetch|try|verify|confirm|calculate|count"
    r"|use|call|grab|see|start|dig|investigate|scan|examine|inspect|locate|consult|retrieve|compute|grep|list"
    r"|remember|save|store|note)\b"
    r"|^(?:I['’]m |I am )?(?:now |still )?(?:checking|looking|searching|reading|running|reviewing|pulling"
    r"|fetching|opening|querying|retrieving)\s+(?:the|for|into|up|through|it|that|this|company|our)\b[^,]*$",
    re.IGNORECASE,
)
NUDGE = (
    "<tool_result status=\"no_call\">\nYour last reply said what you would do next but contained no "
    "<tool_call> block, so no tool ran and the user has no answer yet. Write the tool call now, or, "
    "if you already have what you need, write the final answer itself.\n</tool_result>"
)

# A first reply that says nothing was found, written before any tool ran.
# (A first reply that asks the user a question gets the same nudge.)
_CLAIMS_NOT_FOUND = re.compile(
    r"\b(?:couldn['\u2019]t|could not|can['\u2019]t|cannot|unable to|wasn['\u2019]t able to|not able to"
    r"|did not|didn['\u2019]t)\s+(?:\w+\s+){0,2}?"
    r"(?:find|locate|retrieve|access|see|determine|look|tell|answer|confirm|verify|check)\b"
    r"|\bdon['\u2019]t know\b|\b(?:don['\u2019]t|do not) have (?:enough |the |any )?(?:information|details|access)\b|\bno (?:search )?results\b|\bno (?:information|record|mention|reference|data)\b"
    r"|\bnot (?:available|found)\b",
    re.IGNORECASE,
)
NUDGE_NO_SEARCH = (
    "<tool_result status=\"no_call\">\nYou have not called any tool for this request yet, so nothing "
    "has been searched. Use the tools to look it up before saying it cannot be found or asking the user what they mean.\n</tool_result>"
)

SYSTEM_INTRO = """You are Cardinal, a helpful assistant for the employees of a company. Work step by step: call a tool when you need information or need to act, read its result, and continue until you can answer. Base your answers on what the tools return; do not invent facts. Search before asking the user what they mean: when the question names something the tools can look up, look it up first, and ask only if the results leave it unclear. When a result says the detail you need is in another document (for example "see the Benefits Summary"), search for that document and read it before you answer. When you are done, reply in plain text with your final answer."""


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
        # Snapshot: the rules are fixed for the session, whatever changes config later.
        self.deny_rules = guardrails.DenyRules(config.deny_rules)
        self._provenance = guardrails.Provenance()
        self.transcript: list[dict] = []
        self._messages: list[dict] = []
        self._kinds: list[str] = []
        self._current_user = 0  # index in _messages of the message being worked on
        self._steering: list[int] = []  # indices in _messages of this send's steering messages
        self._system = (
            SYSTEM_INTRO + "\n\n" + guardrails.PROMPT_NOTE + "\n\n" + render_tools(self.registry.schemas())
        )
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
        nudges = 0
        called = False  # whether any tool call was made in this send
        remembered = False  # whether remember ran (or was nudged for) in this send
        saved = False  # whether a remember call succeeded in this send

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

            if parsed.error is not None and (same := repeated_call(reply)) is not None:
                parsed = ParsedResponse(text=parsed.text, tool_call=same)
            if parsed.error is not None:
                malformed += 1
                self._add_error(format_parse_error(parsed.error))
                if malformed >= MAX_MALFORMED:
                    return self._malformed_stop()
                continue

            if parsed.tool_call is None:
                text = parsed.text or reply.strip()
                if not text:
                    # Empty replies are not cached by the LM wrapper, so asking again gets a fresh one.
                    malformed += 1
                    self._add_error(format_parse_error("your reply was empty. Call a tool or write your answer"))
                    if malformed >= MAX_MALFORMED:
                        return self._result("(The model gave an empty answer.)", "done")
                    continue
                if nudges < MAX_NUDGES and announces_call(text):
                    nudges += 1
                    self._add_error(NUDGE)
                    continue
                if nudges < MAX_NUDGES and not called and (_CLAIMS_NOT_FOUND.search(text) or text.endswith("?")):
                    nudges += 1
                    self._add_error(NUDGE_NO_SEARCH)
                    continue
                if nudges < MAX_NUDGES and self._should_have_remembered(remembered):
                    nudges += 1
                    remembered = True  # one memory nudge per send
                    self._add_error(REMEMBER_NUDGE)
                    continue
                if self._should_have_remembered(saved):
                    text += self._fallback_save()
                return self._result(text, "done")

            call = parsed.tool_call
            called = True
            remembered = remembered or call.name == "remember"
            self.transcript.append({"type": "tool_call", "name": call.name, "args": copy.deepcopy(call.args)})
            # Validate first: a call the registry rejects is never sent for approval.
            result = self.registry.validate(call.name, call.args)
            if result is None:
                result = self._guard(call)
            if result is None:
                result = interactive.check_approval(
                    self.config.user, self.mode, self.registry.get(call.name), call
                )
            if result is None:
                result = self.registry.execute(call.name, call.args)
            if not result.content.strip():
                result = ToolResult(result.status, "(no output)")
            if result.status not in ("denied", *MALFORMED_STATUSES) and call.name != "ask_user":
                self._provenance.observe(result.content)
                result = ToolResult(result.status, guardrails.flag_result(result.content))
            # Cap a huge result before it is logged, so the event holds what the model sees.
            result = ToolResult(result.status, fit_result(result.content, self.config.context_budget))
            self.transcript.append(
                {"type": "tool_result", "name": call.name, "status": result.status, "content": result.content}
            )
            self._append("user", format_tool_result(call.name, result), "tool")

            saved = saved or (call.name == "remember" and result.status == "ok")
            if result.status in MALFORMED_STATUSES:
                malformed += 1
                if malformed >= MAX_MALFORMED:
                    return self._malformed_stop()
            else:
                malformed = 0

    # ----------------------------------------------------------- helpers ----

    def _guard(self, call) -> Optional[ToolResult]:
        """The P14 checks for a validated call: None if it may go on to approval."""
        if call.name != "run_terminal":
            return None
        cmd = str(call.args.get("cmd", ""))
        rule = self.deny_rules.match(cmd)
        if rule is not None:
            return guardrails.deny_rule_denial(rule)
        return self._provenance.check(cmd, self._user_text())

    def _should_have_remembered(self, remembered: bool) -> bool:
        """The user asked for something to be kept and this send saved nothing."""
        return (
            not remembered
            and "remember" in self.registry.names()
            and self.config.memory_dir is not None
            and ASKED_TO_REMEMBER.search(self._messages[self._current_user]["content"]) is not None
        )

    def _fallback_save(self) -> str:
        """Save the user's own words when they asked for something to be kept
        and the model saved nothing (the live model sometimes refuses work
        identifiers as "sensitive"). Returns a note for the answer, or ''."""
        fact = fallback_fact(self._messages[self._current_user]["content"])
        if fact is None:
            return ""
        try:
            guardrails.check_fact(fact)
            reply = MemoryStore(self.config.memory_dir).remember(fact)
        except (OSError, ValueError):
            return ""
        return "\n\n(Cardinal saved your message to memory, as you asked: " + reply.split("\n")[0] + ")"

    def _user_text(self) -> str:
        """Everything the user wrote this session: messages and ask_user answers."""
        parts = [e["content"] for e in self.transcript if e["type"] == "user"]
        parts += [
            e["content"]
            for e in self.transcript
            if e["type"] == "tool_result" and e.get("name") == "ask_user" and e.get("status") == "ok"
        ]
        return "\n".join(parts)

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


def announces_call(text: str) -> bool:
    """True if the reply ends by announcing a step instead of answering."""
    text = re.sub(r"\([^()]*\)", " ", text).strip()  # asides like "(I'm ignoring it.)"
    sentences = [x.strip() for x in re.split(r"(?<=[.!?:])\s+|[,;] (?:so|but|and)\s+|;\s+", text) if x.strip()]
    return any(_ANNOUNCES_CALL.match(x) is not None for x in sentences[-2:])


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
