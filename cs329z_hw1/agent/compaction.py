"""Problem 11 (compaction): keep every model call within ``context_budget``.

Compaction changes only what is sent to the model. The session's transcript
is never touched; the session's ``_messages`` list is never edited either.
The ``Compactor`` keeps its own overlay on top of ``_messages``: which
messages have been folded into the summary (``dropped``), which old tool
results are shown as a short stub (``short``), and the running summary.

The policy, cheapest step first:

1. **Cap each tool result when it arrives** (``fit_result``) at a quarter of
   the budget, keeping its head and tail. This runs before the result is
   logged, so the "tool_result" event still holds exactly what the model
   saw, and it is what keeps a single 30,000-token result from breaking the
   budget on the very next call (where the result must appear verbatim).
2. **Trigger lazily**: nothing happens while the next call fits the budget.
   When it would not, compact down to ``TARGET_FRACTION`` of the budget, so
   the next few calls have headroom and the summary model is not called on
   every turn.
3. **Stub old tool results first** (oldest first). Tool results are the bulk
   of the context and the cheapest thing to lose: the stub keeps the tool
   name, status, size, the start of the output, and any ``.outputs/...``
   file path the terminal tool saved, so the model can re-read it.
4. **Then fold the oldest messages into a summary written by
   ``aux_lm``**, whole steps at a time (an assistant call together with its
   result). The previous summary is passed back in, and the summary prompt
   asks for the user's requirements and constraints first, copied
   word for word, so they survive any number of compactions.
5. **Never compacted away**: the system prompt (tool list), the user message
   currently being worked on, and the newest message (the tool result or
   error the next call must show verbatim). If even those do not fit, the
   summary and then the protected user message are cut in the copy that is
   sent (``_squeeze``), so the budget always holds.

The summary is appended to the system message, so the message list keeps
its system/user/assistant shape and the first message still names every
tool.
"""

from __future__ import annotations

import re
from typing import Optional

from cs329z_hw1.agent.terminal import _head, _tail
from cs329z_hw1.tokens import CHARS_PER_TOKEN, MESSAGE_OVERHEAD, count_message_tokens, count_tokens
from cs329z_hw1.types import LMCallable

# One tool result may use at most context_budget // RESULT_SHARE tokens.
RESULT_SHARE = 4
MIN_RESULT_TOKENS = 200
# The summary may use at most context_budget // SUMMARY_SHARE tokens.
SUMMARY_SHARE = 8
MIN_SUMMARY_TOKENS = 150
# When compaction triggers, shrink the context to this share of the budget.
TARGET_FRACTION = 0.6
# How much of an old tool result its stub keeps.
STUB_PREVIEW_CHARS = 160
# Of a cut tool result, the share of its allowance given to the head.
HEAD_FRACTION = 0.6

_SAVED_PATH = re.compile(r"\.outputs/[\w.\-]+")

SUMMARY_HEADER = (
    "## Summary of the earlier conversation\n"
    "Earlier messages were removed to save space; this summary replaces them. "
    "The user's requirements and constraints listed here still apply."
)

SUMMARY_INSTRUCTIONS = """You maintain the running summary of a conversation between a user and an AI assistant that uses tools. The oldest messages are being removed from the assistant's context, and your summary is all the assistant will have of them.

Write the new summary in two sections:
1. "User requirements and constraints:" every requirement, constraint, preference, limit, deadline, number, name, place and reference ID the user stated, copied word for word. Copy this section from the previous summary first, then add new ones. Never drop one unless the user explicitly withdrew it.
2. "Progress:" what the user asked for, what the assistant found or did (key facts and tool results that may matter later, with exact values), and what is still open.

Be brief and factual. Plain text, no preamble. Stay under {chars} characters."""


def result_tokens(context_budget: int) -> int:
    return max(MIN_RESULT_TOKENS, context_budget // RESULT_SHARE)


def summary_tokens(context_budget: int) -> int:
    return max(MIN_SUMMARY_TOKENS, context_budget // SUMMARY_SHARE)


def _cut_middle(text: str, limit: int, what: str) -> str:
    """``text`` cut to at most about ``limit`` characters: head, marker, tail."""
    if len(text) <= limit:
        return text
    head = _head(text, int(limit * HEAD_FRACTION))
    tail = _tail(text[len(head) :], limit - len(head))
    hidden = text[len(head) : len(text) - len(tail)]
    return (
        f"{head.rstrip(chr(10))}\n"
        f"[... {len(hidden):,} characters ({hidden.count(chr(10)):,} lines) of this {what} "
        f"left out to fit the context ...]\n"
        f"{tail.lstrip(chr(10))}"
    )


def fit_result(content: str, context_budget: int) -> str:
    """A tool result's content, cut to its share of the budget if it is longer."""
    return _cut_middle(content, result_tokens(context_budget) * CHARS_PER_TOKEN, "output")


def _stub(message: str) -> str:
    """What an old tool result is replaced by: header, size, preview, saved file."""
    first, _, body = message.partition("\n")
    if not first.startswith("<tool_result"):
        first, body = "<tool_result>", message
    body = body.removesuffix("</tool_result>").strip()
    preview = " ".join(body[:STUB_PREVIEW_CHARS].split())
    more = "..." if len(body) > STUB_PREVIEW_CHARS else ""
    saved = sorted(set(_SAVED_PATH.findall(body)))
    where = f" The full output is saved in {', '.join(saved)}." if saved else " Call the tool again if you need it."
    return (
        f"{first}\n[Old result shortened to save context; it was {count_tokens(body):,} tokens. "
        f"It began: {preview}{more}]{where}\n</tool_result>"
    )


class Compactor:
    """The overlay that turns a session's full message list into one call's messages."""

    def __init__(self, aux_lm: LMCallable, context_budget: int, system: str) -> None:
        self.aux_lm = aux_lm
        self.budget = context_budget
        self.system = system
        self.summary = ""
        self.dropped: set[int] = set()
        self.short: dict[int, str] = {}
        self.compactions = 0  # times aux_lm was asked for a summary

    # ------------------------------------------------------------ public ----

    def build(self, messages: list[dict], kinds: list[str], protected: set[int]) -> list[dict]:
        """The messages for the next model call, compacting first if they would not fit.

        ``kinds[i]`` is "user", "assistant", "tool" or "error" for
        ``messages[i]``; indices in ``protected`` are never shortened or dropped.
        """
        if self._size(messages) > self.budget:
            self._compact(messages, kinds, protected)
        out = self._assemble(messages, self.summary)
        if count_message_tokens(out) > self.budget:
            out = self._squeeze(out, messages, protected)
        return out

    # ----------------------------------------------------------- helpers ----

    def _system_message(self, summary: str) -> dict:
        content = self.system if not summary else f"{self.system}\n\n{SUMMARY_HEADER}\n{summary}"
        return {"role": "system", "content": content}

    def _assemble(self, messages: list[dict], summary: str) -> list[dict]:
        out = [self._system_message(summary)]
        for i, m in enumerate(messages):
            if i not in self.dropped:
                out.append({"role": m["role"], "content": self.short.get(i, m["content"])})
        return out

    def _size(self, messages: list[dict], summary: Optional[str] = None) -> int:
        """Tokens of the call as currently assembled (cheaper than building it)."""
        summary = self.summary if summary is None else summary
        total = count_tokens(self._system_message(summary)["content"]) + MESSAGE_OVERHEAD
        for i, m in enumerate(messages):
            if i not in self.dropped:
                total += count_tokens(self.short.get(i, m["content"])) + MESSAGE_OVERHEAD
        return total

    def _compact(self, messages: list[dict], kinds: list[str], protected: set[int]) -> None:
        target = int(self.budget * TARGET_FRACTION)
        live = [i for i in range(len(messages)) if i not in self.dropped and i not in protected]

        # Step 1: stub old tool results, oldest first.
        for i in live:
            if self._size(messages) <= target:
                return
            if kinds[i] in ("tool", "error") and i not in self.short:
                stub = _stub(messages[i]["content"])
                if count_tokens(stub) < count_tokens(messages[i]["content"]):
                    self.short[i] = stub

        # Step 2: fold the oldest steps into the summary. Reserve room for the
        # summary at its full allowance, since it is written after the drop.
        reserve = summary_tokens(self.budget) + len(SUMMARY_HEADER) // CHARS_PER_TOKEN + 2
        folded: list[int] = []
        for i in live:
            if self._size(messages, summary="") + reserve <= target:
                break
            if i in self.dropped:
                continue
            self.dropped.add(i)
            folded.append(i)
            # Keep a call and its result together.
            nxt = i + 1
            if kinds[i] == "assistant" and nxt < len(messages) and nxt not in protected and kinds[nxt] in ("tool", "error"):
                self.dropped.add(nxt)
                folded.append(nxt)
        if folded:
            self.summary = self._summarize(messages, kinds, folded)

    def _summarize(self, messages: list[dict], kinds: list[str], folded: list[int]) -> str:
        """A new summary from the previous one and the folded messages, by aux_lm."""
        limit = summary_tokens(self.budget) * CHARS_PER_TOKEN
        labels = {"user": "User", "assistant": "Assistant", "tool": "Tool result", "error": "Error"}
        lines = [f"[{labels[kinds[i]]}] {self.short.get(i, messages[i]['content'])}" for i in folded]
        prompt = (
            f"Previous summary:\n{self.summary or '(none)'}\n\n"
            "Messages to fold into the summary, oldest first:\n" + "\n\n".join(lines) +
            "\n\nWrite the new summary."
        )
        request = [
            {"role": "system", "content": SUMMARY_INSTRUCTIONS.format(chars=limit)},
            {"role": "user", "content": prompt},
        ]
        self.compactions += 1
        try:
            text = self.aux_lm(request)
            text = (text if isinstance(text, str) else str(text)).strip()
        except Exception as exc:  # a failed summary must not end the session
            text = (getattr(exc, "text", "") or "").strip()
        if not text:
            text = self._fallback_summary(messages, kinds, folded)
        return _head(text, limit).rstrip() if len(text) > limit else text

    def _fallback_summary(self, messages: list[dict], kinds: list[str], folded: list[int]) -> str:
        """Without a model summary, keep the previous one plus the user's own words."""
        said = [" ".join(messages[i]["content"].split())[:300] for i in folded if kinds[i] == "user"]
        parts = [self.summary] if self.summary else []
        if said:
            parts.append("Earlier user messages:\n" + "\n".join(f"- {s}" for s in said))
        return "\n".join(parts) or "(Earlier steps were removed to save space.)"

    def _squeeze(self, out: list[dict], messages: list[dict], protected: set[int]) -> list[dict]:
        """Last resort when even the protected messages do not fit: cut the
        summary, then the longest protected message, in the copy that is sent."""
        over = count_message_tokens(out) - self.budget
        if self.summary:
            keep = max(0, len(self.summary) - (over + 8) * CHARS_PER_TOKEN)
            out[0] = self._system_message(_cut_middle(self.summary, keep, "summary") if keep else "")
            over = count_message_tokens(out) - self.budget
        while over > 0:
            j = max(range(1, len(out)), key=lambda k: len(out[k]["content"]), default=None)
            if j is None or len(out[j]["content"]) < 200:
                break  # only the system prompt is left; nothing more can be cut
            text = out[j]["content"]
            keep = max(100, len(text) - (over + 40) * CHARS_PER_TOKEN)
            out[j] = {"role": out[j]["role"], "content": _cut_middle(text, keep, "message")}
            over = count_message_tokens(out) - self.budget
        return out
