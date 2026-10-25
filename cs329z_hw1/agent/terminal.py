"""Problem 10 (terminal): the run_terminal tool and its observation policy.

Every command goes through ``sandbox.run_terminal``, with
``config.workspace`` and ``config.terminal_timeout``; nothing here starts a
process itself.

What the model sees (the observation policy):

* Always the exit code (or "timed out" / "rejected" with the sandbox's
  reason), then stdout and stderr, each labelled, with its size in lines and
  characters.
* A stream that fits its share of the observation budget is shown in full.
* A longer stream is cut to its head and its tail, at line boundaries, with
  a marker saying how many lines were left out. The full stream is written
  to a file in the workspace (``.outputs/cmd-N.stdout.txt``), and the
  observation names the file and how to search or page through it with
  ``grep -n`` / ``sed -n``. Output that is cut is therefore never lost: the
  model can read any part of it with another command, and compaction (P11)
  can drop an old observation knowing its content is still on disk.

The observation budget scales with ``config.context_budget`` (an eighth of
it, between 300 and 2,000 tokens), so one command can never fill the
context: with the default 16,000-token budget a result is at most about
2,000 tokens.

Status: the function returns (status "ok") only when the command ran and
exited with code 0. A non-zero exit, a timeout or a rejection raises
``CommandFailed`` with the same observation as its message, which the
registry turns into a "tool_error" whose content still holds the whole
observation.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Optional

from cs329z_hw1 import sandbox
from cs329z_hw1.tokens import CHARS_PER_TOKEN
from cs329z_hw1.types import AgentConfig

# Tokens one observation may use: a fraction of the context budget, clamped.
OBSERVATION_SHARE = 8  # context_budget // OBSERVATION_SHARE
MIN_OBSERVATION_TOKENS = 300
MAX_OBSERVATION_TOKENS = 2000
# Of a stream that is cut, the share of its allowance given to the head.
HEAD_FRACTION = 0.6
# Directory in the workspace that holds the full output of cut streams.
OUTPUT_DIR = ".outputs"

DESCRIPTION = (
    "Run one bash command in a sandboxed workspace and return its exit code, stdout and "
    "stderr. The working directory holds emails.jsonl (the email archive, one JSON object "
    "per line with keys id, thread_id, reply_to, from, to (a list), date (UTC, "
    "e.g. 2001-06-01T00:03:01Z), subject, body) and docs/ (the company documents as .md "
    "files). Each line is written as {\"id\": \"em-00001\", \"thread_id\": ..., \"from\": "
    "\"x@enron.com\", ...}, so plain tools work too when scripts are not allowed: "
    "grep -c '\"from\": \"x@enron.com\"' emails.jsonl counts an exact from field. "
    "Use it to count, sort, filter or compute over the data. Only these programs "
    "are allowed: " + ", ".join(sandbox.ALLOWED_PROGRAMS) + " (python3 has only the "
    "standard library). Programs given by path, variable assignments (X=1 cmd), $(...), "
    "backticks and here-documents (<<) are rejected: write a multi-line script as "
    "python3 -c '...' with the code in single quotes. Commands time out after a few "
    "seconds. Only the working directory is writable: write any temporary file there "
    "with a relative path (out.txt), never in /tmp. Long output is cut to its first and last lines, and the full output is "
    "saved to a file whose path is given, so print only what you need (counts, top-10 "
    "lists) and use grep -n or sed -n on the saved file to find the rest."
)


class CommandFailed(Exception):
    """A command that did not run to a zero exit code. The message is the observation."""


_counter = itertools.count(1)


def observation_chars(context_budget: int) -> int:
    """Characters one run_terminal observation may hold."""
    tokens = min(MAX_OBSERVATION_TOKENS, max(MIN_OBSERVATION_TOKENS, context_budget // OBSERVATION_SHARE))
    return tokens * CHARS_PER_TOKEN


def _size(text: str) -> str:
    lines = text.count("\n") + (0 if text.endswith("\n") else 1)
    return f"{lines:,} line{'s' if lines != 1 else ''}, {len(text):,} characters"


def _head(text: str, limit: int) -> str:
    """At most ``limit`` characters from the start, cut after a newline if one is near."""
    part = text[:limit]
    cut = part.rfind("\n")
    return part[: cut + 1] if cut >= limit // 2 else part


def _tail(text: str, limit: int) -> str:
    """At most ``limit`` characters from the end, cut after a newline if one is near."""
    part = text[-limit:] if limit > 0 else ""
    cut = part.find("\n")
    return part[cut + 1 :] if 0 <= cut < len(part) // 2 else part


def _save(workspace: Path, name: str, text: str) -> Optional[str]:
    """Write ``text`` to the output directory; return its path relative to the workspace."""
    out_dir = workspace / OUTPUT_DIR
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        while True:
            path = out_dir / f"cmd-{next(_counter)}.{name}.txt"
            if not path.exists():
                break
        path.write_text(text, encoding="utf-8")
    except OSError:
        return None
    return f"{OUTPUT_DIR}/{path.name}"


def _stream(label: str, text: str, limit: int, workspace: Path) -> str:
    """One labelled stream, in full or as head + tail with a pointer to the saved file."""
    if not text:
        return f"{label}: (empty)"
    if len(text) <= limit:
        return f"{label} ({_size(text)}):\n{text.rstrip(chr(10))}"
    head = _head(text, int(limit * HEAD_FRACTION))
    tail = _tail(text[len(head) :], limit - len(head))
    hidden = text[len(head) : len(text) - len(tail)]
    first = head.count("\n") + 1
    skipped = hidden.count("\n")
    saved = _save(workspace, label, text)
    where = (
        f"The full {label} is saved in {saved}; read more with "
        f"grep -n 'PATTERN' {saved} or sed -n '{first},{first + 99}p' {saved}."
        if saved
        else "The full output could not be saved; rerun with a narrower command."
    )
    return (
        f"{label} ({_size(text)}; too long, showing the start and the end). {where}\n"
        f"{head.rstrip(chr(10))}\n"
        f"[... {len(hidden):,} characters ({skipped:,} lines) left out, from line {first} on ...]\n"
        f"{tail.rstrip(chr(10))}"
    )


def make_run_terminal(config: AgentConfig):
    """The run_terminal function for one session."""
    limit = observation_chars(config.context_budget)

    def run_terminal(cmd: str) -> str:
        result = sandbox.run_terminal(cmd, workspace=config.workspace, timeout=config.terminal_timeout)
        if result.rejected:
            raise CommandFailed(f"{result.reason}\nThe command was not run (no exit code).")
        workspace = Path(config.workspace) if config.workspace is not None else sandbox.default_workspace()
        # stderr is usually short and the most useful part of a failure: it gets
        # a third of the allowance when both streams are long.
        out_limit, err_limit = limit, limit
        if len(result.stdout) + len(result.stderr) > limit:
            err_limit = max(limit // 3, limit - len(result.stdout))
            out_limit = limit - min(len(result.stderr), err_limit)
        if result.timed_out:
            status = f"{result.reason} No exit code; the output below is what it printed before it timed out."
        else:
            status = f"exit code: {result.exit_code}"
        shown = "\n".join(
            [
                status,
                _stream("stdout", result.stdout, out_limit, workspace),
                _stream("stderr", result.stderr, err_limit, workspace),
            ]
        )
        if result.timed_out or result.exit_code != 0:
            raise CommandFailed(shown)
        return shown

    return run_terminal
