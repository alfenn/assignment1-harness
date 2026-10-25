"""Problem 6 (tool_protocol): the text format for tool calls.

A call is one JSON object inside ``<tool_call>`` tags:

    Let me look that up.

    <tool_call>
    {"name": "lookup", "args": {"key": "guest_wifi"}}
    </tool_call>

The parser finds the opening tag and decodes exactly one JSON value after it
with ``raw_decode``. The decoder, not a search for the closing tag, decides
where the call ends, so a string argument may contain anything (including a
complete call in this format), and a reply cut off inside the JSON fails to
decode and is reported as an error.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from cs329z_hw1.types import ParsedResponse, ToolCall, ToolResult

OPEN = "<tool_call>"
CLOSE = "</tool_call>"

# strict=False accepts raw newlines/tabs inside strings, which models write.
_DECODER = json.JSONDecoder(strict=False)
_ARG_KEYS = ("args", "arguments", "parameters", "input")


# ---------------------------------------------------------------- render ----


def _param_line(name: str, schema: dict, required: bool) -> str:
    kind = schema.get("type", "any")
    if isinstance(kind, list):
        kind = " | ".join(map(str, kind))
    bits = [f"{kind}, {'required' if required else 'optional'}"]
    if "enum" in schema:
        bits.append("one of " + ", ".join(json.dumps(v) for v in schema["enum"]))
    if "minimum" in schema:
        bits.append(f"min {schema['minimum']}")
    if "maximum" in schema:
        bits.append(f"max {schema['maximum']}")
    line = f"  - {name} ({'; '.join(bits)})"
    if schema.get("description"):
        line += f": {schema['description']}"
    return line


def _render_tool(schema: dict) -> str:
    params = schema.get("parameters") or {}
    props = params.get("properties") or {}
    required = set(params.get("required") or [])
    lines = [f"### {schema['name']}", schema.get("description", "").strip()]
    if props:
        lines.append("Arguments:")
        lines += [_param_line(n, s, n in required) for n, s in props.items()]
    else:
        lines.append('Arguments: none (use "args": {}).')
    lines.append("JSON Schema of args: " + json.dumps(params, ensure_ascii=False))
    return "\n".join(lines)


def render_tools(schemas: list[dict]) -> str:
    tools = "\n\n".join(_render_tool(s) for s in schemas)
    return f"""# Tools

You can call the tools listed below. You call a tool by writing plain text in your reply; no special tool-calling feature is needed, and this always works. A tool runs only when your reply contains a call block, written exactly like this:

{OPEN}
{{"name": "TOOL_NAME", "args": {{"ARG_NAME": "value"}}}}
{CLOSE}

The block holds one JSON object with the keys "name" (the tool name) and "args" (an object with the tool's arguments). End your reply right after {CLOSE} and wait for the result.

Rules for a call:
- Write the block itself in this reply. Saying that you will call a tool ("I'll look that up") does nothing; only the block runs the tool. No preamble is needed.
- When the user asks for something a tool can do, call the tool even if you could answer yourself (do not do the arithmetic, echo the text, or guess the answer).
- The content of the block must be valid JSON: double-quoted keys and strings; inside strings escape double quotes as \\" and backslashes as \\\\ (a Windows path C:\\dir becomes "C:\\\\dir"); write line breaks inside a string as \\n.
- Give numbers and booleans as JSON numbers and booleans (17, 0.5, true), not as strings. Pass text arguments exactly as the user gave them.
- Use only the argument names listed for the tool and include every required one.
- Write at most one {OPEN} block per reply.

After a call, the result arrives in the next user message as <tool_result name="..." status="...">...</tool_result>. Status "ok" means the tool ran; any other status is an error you can fix and retry. When you have what you need, reply in plain text with no {OPEN} block; that reply is your final answer.

Example: if the user asks "what is 2 plus 3?" and an add tool exists, your whole reply is
{OPEN}
{{"name": "add", "args": {{"a": 2, "b": 3}}}}
{CLOSE}

# Available tools

{tools}

# Reminder

To use a tool, your reply must contain the {OPEN} ... {CLOSE} block with valid JSON. Without the block, no tool runs."""


# ----------------------------------------------------------------- parse ----


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i].isspace():
        i += 1
    return i


def _skip_fence_open(text: str, i: int) -> int:
    """Skip a ```json fence some models put inside the tags."""
    if text.startswith("```", i):
        end = text.find("\n", i)
        lang = text[i + 3 : end].strip() if end != -1 else None
        if lang is not None and (lang == "" or lang.isalnum()):
            return _skip_ws(text, end + 1)
    return i


def _to_call(obj: Any) -> ToolCall | str:
    """A ToolCall from the decoded JSON object, or an error message."""
    if not isinstance(obj, dict):
        return f"the {OPEN} block must hold a JSON object, got {type(obj).__name__}"
    name = obj.get("name")
    if not isinstance(name, str) or not name.strip():
        return 'the call has no "name" string'
    args: Any = {}
    for key in _ARG_KEYS:
        if key in obj:
            args = obj[key]
            break
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return f'"args" must be a JSON object, got {type(args).__name__}'
    return ToolCall(name=name.strip(), args=args)


def _read_call(text: str, start: int) -> tuple[Optional[ToolCall], Optional[str], int]:
    """Read the call whose OPEN tag starts at ``start``.

    Returns (call, error, end), where ``end`` is the index just past the call.
    """
    i = _skip_fence_open(text, _skip_ws(text, start + len(OPEN)))
    if i >= len(text):
        return None, f"the reply ends right after {OPEN}; the call is missing", len(text)
    try:
        obj, i = _DECODER.raw_decode(text, i)
    except Exception as exc:  # JSONDecodeError, or RecursionError on deep nesting
        return None, f"the {OPEN} block is not valid JSON ({exc}); the call may be cut off", len(text)
    call = _to_call(obj)
    if isinstance(call, str):
        return None, call, i
    i = _skip_ws(text, i)
    if text.startswith("```", i):
        i = _skip_ws(text, i + 3)
    if text.startswith(CLOSE, i):
        i += len(CLOSE)
    elif CLOSE.startswith(text[i:]):  # end tag missing or cut off: the JSON is complete
        i = len(text)
    return call, None, i


def parse_response(text: str) -> ParsedResponse:
    try:
        return _parse(text if isinstance(text, str) else str(text))
    except Exception as exc:  # never raise
        return ParsedResponse(text=str(text).strip(), error=f"could not parse the reply: {exc}")


def _parse(text: str) -> ParsedResponse:
    start = text.find(OPEN)
    if start == -1:
        return _parse_without_open_tag(text)
    call, error, end = _read_call(text, start)
    before = text[:start].strip()
    if error is not None:
        return ParsedResponse(text=before, error=error)
    if text.find(OPEN, end) != -1:
        return ParsedResponse(
            text=before,
            error=f"the reply contains more than one {OPEN} block; write exactly one call per reply",
        )
    rest = text[end:].strip()
    return ParsedResponse(text="\n\n".join(p for p in (before, rest) if p), tool_call=call)


def repeated_call(text: str) -> Optional[ToolCall]:
    """The call, if a reply holds two or more blocks that are all the same
    complete call (the live model sometimes writes one call several times).
    ``parse_response`` still reports such a reply as an error, as the
    protocol requires; the agent loop uses this to run the call once."""
    calls: list[ToolCall] = []
    start = text.find(OPEN)
    while start != -1:
        call, error, end = _read_call(text, start)
        if error is not None:
            return None
        calls.append(call)
        start = text.find(OPEN, end)
    first = calls[0] if calls else None
    if len(calls) < 2 or any(c.name != first.name or c.args != first.args for c in calls):
        return None
    return first


def _parse_without_open_tag(text: str) -> ParsedResponse:
    """A reply with no OPEN tag is plain text, unless it ends with a complete
    call object followed by CLOSE: the live model sometimes drops the opening
    tag and writes just ``{"name": ...}</tool_call>``. That call is accepted."""
    close = text.find(CLOSE)
    if close == -1 or text.find(CLOSE, close + 1) != -1:
        return ParsedResponse(text=text.strip())
    i = text.find("{")
    while i != -1 and i < close:
        try:
            obj, end = _DECODER.raw_decode(text, i)
        except Exception:
            obj, end = None, -1
        if end != -1 and _skip_ws(text, end) == close:
            call = _to_call(obj)
            if isinstance(call, ToolCall):
                before = text[:i].strip()
                rest = text[close + len(CLOSE) :].strip()
                return ParsedResponse(text="\n\n".join(p for p in (before, rest) if p), tool_call=call)
        i = text.find("{", i + 1)
    return ParsedResponse(text=text.strip())


# ---------------------------------------------------------------- format ----


def format_tool_call(text: str, call: ToolCall) -> str:
    body = json.dumps({"name": call.name, "args": call.args}, ensure_ascii=False)
    block = f"{OPEN}\n{body}\n{CLOSE}"
    text = text.strip()
    return f"{text}\n\n{block}" if text else block


def format_tool_result(name: str, result: ToolResult) -> str:
    """How a tool result is written back to the model (as a user message)."""
    return f'<tool_result name="{name}" status="{result.status}">\n{result.content}\n</tool_result>'


def format_parse_error(error: str) -> str:
    """The user message sent back after a reply whose call could not be parsed."""
    return (
        f"<tool_result status=\"malformed\">\nYour last reply had a malformed tool call: {error}\n"
        f"Write exactly one {OPEN} block holding valid JSON, or answer in plain text.\n</tool_result>"
    )
