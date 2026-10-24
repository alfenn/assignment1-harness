"""Problem 8 (cardinal): assemble the Cardinal toolset.

``build_tools(config, aux_lm)`` returns the ten Cardinal ``ToolSpec``s, in
``CARDINAL_TOOLS`` order. ``extra_tools(config, aux_lm)`` returns the tools an
explicit tool list gets on top: ``ask_user`` when ``config.user`` is set,
``remember`` and ``recall`` when ``config.memory_dir`` is set.

Nothing here reads the email archive until a tool needs it. The BM25 index
over the archive is built on first use and shared by every session in the
process (it takes a few seconds and the archive never changes).

Tools from later problems (search_docs, read_doc, run_terminal, remember,
recall) are registered already, so the model and the tests see all ten; until
their problem is done, calling one raises, which the registry turns into a
``tool_error``.
"""

from __future__ import annotations

import threading
from typing import Optional

from cs329z_hw1 import data
from cs329z_hw1.cardinal import CARDINAL_TOOLS, cardinal_spec
from cs329z_hw1.pipelines import bm25
from cs329z_hw1.pipelines.daily_digest import write_digest
from cs329z_hw1.pipelines.email_qa import answer_question
from cs329z_hw1.types import AgentConfig, Email, LMCallable, ToolSpec

# search_emails: the most results one call returns, and characters of body per result.
MAX_K = 20
SNIPPET_CHARS = 200
# read_email: characters of body shown. The longest emails are ~50,000
# characters; read_email has no offset argument, so the rest is not reachable.
READ_EMAIL_CHARS = 8000


# ------------------------------------------------------ the email index ----


class _EmailIndex:
    """The archive and its BM25 index, loaded the first time it is needed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._emails: Optional[list[Email]] = None
        self._by_id: dict[str, Email] = {}
        self._index: Optional[bm25.BM25Index] = None

    def _load(self) -> None:
        with self._lock:
            if self._index is not None:
                return
            emails = data.load_emails()
            self._by_id = {e["id"]: e for e in emails}
            self._index = bm25.build_index([data.email_text(e) for e in emails])
            self._emails = emails

    def search(self, query: str, k: int) -> list[Email]:
        self._load()
        return [self._emails[i] for i, _ in bm25.search(self._index, query, k)]

    def get(self, email_id: str) -> Optional[Email]:
        self._load()
        return self._by_id.get(email_id)


EMAIL_INDEX = _EmailIndex()


# --------------------------------------------------------- formatting ----


def _one_line(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _header(email: Email) -> str:
    return (
        f"[{email['id']}] {email['date']} from {email['from']} "
        f"to {', '.join(email['to'][:5])}{' ...' if len(email['to']) > 5 else ''}\n"
        f"Subject: {email['subject']}"
    )


# -------------------------------------------------------------- tools ----


def _search_emails(query: str, k: int = 5) -> str:
    hits = EMAIL_INDEX.search(query, min(k, MAX_K))
    if not hits:
        return f"No emails match {query!r}. Try other keywords (names, companies, places)."
    blocks = [_header(e) + "\n" + _one_line(e["body"], SNIPPET_CHARS) for e in hits]
    return (
        f"{len(hits)} emails, best match first. Call read_email with an id for the full text.\n\n"
        + "\n\n".join(blocks)
    )


def _read_email(email_id: str) -> str:
    email = EMAIL_INDEX.get(email_id.strip())
    if email is None:
        raise LookupError(f"no email with id {email_id!r}; ids look like 'em-00001'")
    body = email["body"]
    if len(body) > READ_EMAIL_CHARS:
        body = (
            body[:READ_EMAIL_CHARS]
            + f"\n[... body truncated: showing {READ_EMAIL_CHARS:,} of {len(body):,} characters]"
        )
    reply = f"In reply to: {email['reply_to']}\n" if email["reply_to"] else ""
    return f"{_header(email)}\nThread: {email['thread_id']}\n{reply}\n{body}"


def _not_yet(problem: str):
    def fn(**kwargs):
        raise NotImplementedError(f"this tool is not available yet ({problem})")

    return fn


def build_tools(config: AgentConfig, aux_lm: LMCallable) -> list[ToolSpec]:
    """The ten Cardinal tools for one session, in ``CARDINAL_TOOLS`` order."""

    def email_qa(question: str) -> str:
        result = answer_question(question, EMAIL_INDEX.search, aux_lm)
        if not result["answer"]:
            return "No answer found in the email archive. Try search_emails with other keywords."
        support = ", ".join(result["support"]) or "(none)"
        return f"Answer: {result['answer']}\nSupporting emails: {support}"

    def daily_digest(date: str) -> str:
        emails = data.emails_on(date)
        if not emails:
            return f"No emails in the archive on {date}."
        return f"Digest of the {len(emails)} emails on {date}:\n\n" + write_digest(emails, aux_lm)

    def ask_user(question: str) -> str:
        if config.user is None:
            raise RuntimeError("no user is connected to this session; answer without asking")
        return str(config.user.ask(question))

    impls = {
        "search_emails": (
            "Keyword (BM25) search over the email archive (about 26,000 emails, June-August 2001). "
            "Returns up to k matches with id, date, sender, subject and the start of the body. "
            "Use specific words: names, companies, places, project names.",
            _search_emails,
        ),
        "read_email": (
            "Read one email by its id (e.g. 'em-00001'): headers, thread id and body.",
            _read_email,
        ),
        "email_qa": (
            "Answer a factual question from the email archive. Runs its own multi-step search "
            "and returns a short answer with the ids of the supporting emails.",
            email_qa,
        ),
        "daily_digest": (
            "Summarize the emails sent on one day (YYYY-MM-DD, UTC): the urgent threads first, "
            "then the others.",
            daily_digest,
        ),
        "search_docs": (
            "Search the Cardinal Energy company documents (policies, handbook, project notes). "
            "Returns doc ids, titles and short snippets.",
            _not_yet("Problem 9"),
        ),
        "read_doc": (
            "Read part of one company document by doc_id, starting at start_line.",
            _not_yet("Problem 9"),
        ),
        "run_terminal": (
            "Run one shell command in a sandboxed workspace that holds emails.jsonl and docs/.",
            _not_yet("Problem 10"),
        ),
        "remember": (
            "Save a fact about the user or their preferences to persistent memory.",
            _not_yet("Problem 12"),
        ),
        "recall": (
            "Search persistent memory for facts saved in earlier conversations.",
            _not_yet("Problem 12"),
        ),
        "ask_user": (
            "Ask the user a clarifying question and wait for the answer. Use it when the "
            "request is ambiguous.",
            ask_user,
        ),
    }
    return [cardinal_spec(name, *impls[name]) for name in CARDINAL_TOOLS]


def extra_tools(config: AgentConfig, aux_lm: LMCallable) -> list[ToolSpec]:
    """What an explicit tool list gets added: ask_user and remember/recall, as configured."""
    wanted = []
    if config.user is not None:
        wanted.append("ask_user")
    if config.memory_dir is not None:
        wanted += ["remember", "recall"]
    if not wanted:
        return []
    return [spec for spec in build_tools(config, aux_lm) if spec.name in wanted]
