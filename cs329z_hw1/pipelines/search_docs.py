"""Problem (search_docs): retrieval over the company documents for an agent.

The documents have one paragraph per line, so passages are built from
lines. A passage is a run of consecutive non-blank lines of one section, cut
when it would pass ``SNIPPET_CHARS`` characters: a long paragraph is a
passage of its own, while a table, a list or a heading with its first short
line are grouped, so no passage is a lone "| Status | Code |" row. Each
passage is one document of the P3 BM25 index (reused as is). The text
indexed for it is the document title, the heading of its section and the
passage, so a paragraph under "## Parental leave" matches the query
"parental leave" even when it never repeats those words.

``search_docs`` returns pointers with short evidence: doc_id, title, the
first line of the passage, the document's date, and a snippet of at most
``SNIPPET_CHARS`` characters of the passage around the rarest query term it holds,
prefixed with the section heading. A document gives at most ``MAX_PER_DOC``
results, so a query that matches one long document still shows the others
(an older and a newer version of a policy, for example).

``read_doc`` returns a window of whole lines from ``start_line``: as many as
fit in ``WINDOW_TOKENS`` tokens and ``WINDOW_LINES`` non-blank lines, but
always at least one. The window is smaller than the 1,500 tokens the tests
allow because the live test caps what the two tools return per conversation
at 6,000 tokens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cs329z_hw1.pipelines import bm25
from cs329z_hw1.tokenizer import tokenize
from cs329z_hw1.tokens import count_tokens
from cs329z_hw1.types import DocWindow, SearchResult

# search: characters of line text in a snippet, and of the heading before it.
# 440 + 80 + framing stays well under the 150-token (600-character) limit.
SNIPPET_CHARS = 440
HEADING_CHARS = 80
SNIPPET_MAX_CHARS = 600
# search: a passage shorter than this many tokens is never cut off on its own.
MIN_PASSAGE_TOKENS = 8
# search: results one document may give for one query.
MAX_PER_DOC = 2
# read: the bounds of one window.
WINDOW_TOKENS = 600
WINDOW_LINES = 40

_TOKEN = re.compile(r"[a-z0-9]+")
_DATE = re.compile(
    r"^(Date|Effective|Posted|Updated|Last updated|As of):\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE
)


@dataclass
class Passage:
    doc: int  # position in DocIndex.docs
    line: int  # 1-based number of its first line
    text: str  # its lines, joined by spaces
    heading: str  # the heading of the section it starts in ("" at the top)


@dataclass
class DocIndex:
    docs: list[dict]
    lines: list[list[str]]  # per document, text.splitlines()
    dates: list[str]  # per document, its first Date/Effective/Posted/... line, or ""
    by_id: dict[str, int]
    passages: list[Passage]
    bm25: bm25.BM25Index


def _passages(doc: int, lines: list[str]) -> list[Passage]:
    out: list[Passage] = []
    heading, first, parts, size = "", 0, [], 0
    start_heading = ""

    def flush() -> None:
        if parts:
            out.append(Passage(doc=doc, line=first, text=" ".join(parts), heading=start_heading))

    for n, line in enumerate(lines, start=1):
        line = " ".join(line.split())
        if not line:
            continue
        is_heading = line.startswith("#")
        big_enough = len(tokenize(" ".join(parts))) >= MIN_PASSAGE_TOKENS
        if parts and big_enough and (is_heading or size + len(line) + 1 > SNIPPET_CHARS):
            flush()
            parts, size = [], 0
        if is_heading:
            heading = line.lstrip("#").strip()
        if not parts:
            first, start_heading = n, ("" if is_heading else heading)
        parts.append(line)
        size += len(line) + 1
    flush()
    return out


def build_doc_index(docs: list[dict]) -> DocIndex:
    lines = [d["text"].splitlines() for d in docs]
    passages = [p for i in range(len(docs)) for p in _passages(i, lines[i])]
    texts = [f"{docs[p.doc]['title']}\n{p.heading}\n{p.text}" for p in passages]
    dates = []
    for doc in docs:
        m = _DATE.search("\n".join(doc["text"].splitlines()[:10]))
        dates.append(f"{m.group(1).lower()} {m.group(2)}" if m else "")
    return DocIndex(
        docs=docs,
        lines=lines,
        dates=dates,
        by_id={d["doc_id"]: i for i, d in enumerate(docs)},
        passages=passages,
        bm25=bm25.build_index(texts),
    )


# ---------------------------------------------------------------- search ----


def _excerpt(line: str, terms: list[str]) -> str:
    """At most SNIPPET_CHARS of ``line``, cut at spaces, around the first
    occurrence of the rarest query term it contains (``terms`` is rarest first)."""
    if len(line) <= SNIPPET_CHARS:
        return line
    found = {}
    for m in _TOKEN.finditer(line.lower()):
        found.setdefault(m.group(), m)
    hit = next((found[t] for t in terms if t in found), None)
    start = 0 if hit is None else max(0, hit.start() - SNIPPET_CHARS // 4)
    start = min(start, len(line) - SNIPPET_CHARS)
    if start > 0:  # snap forward to a word start
        space = line.find(" ", start)
        start = space + 1 if 0 <= space < start + 40 else start
    end = min(len(line), start + SNIPPET_CHARS)
    if end < len(line):  # snap back to a word end
        space = line.rfind(" ", start, end)
        end = space if space > start + SNIPPET_CHARS // 2 else end
    return ("..." if start > 0 else "") + line[start:end] + ("..." if end < len(line) else "")


def _snippet(index: DocIndex, p: Passage, terms: list[str]) -> str:
    text = _excerpt(p.text, terms)
    heading = p.heading[:HEADING_CHARS]
    snippet = f"[{heading}] {text}" if heading else text
    return snippet[:SNIPPET_MAX_CHARS]


def search_docs(index: DocIndex, query: str, k: int = 5) -> list[SearchResult]:
    idf = index.bm25.idf
    terms = sorted(set(tokenize(query)), key=lambda t: (-idf.get(t, 0.0), t))
    if k <= 0 or not terms:
        return []
    # Enough candidates that the per-document cap can still fill k results.
    hits = bm25.search(index.bm25, query, max(k * 8, 40))
    results: list[SearchResult] = []
    per_doc: dict[int, int] = {}
    for pid, _score in hits:
        p = index.passages[pid]
        if per_doc.get(p.doc, 0) >= MAX_PER_DOC:
            continue
        per_doc[p.doc] = per_doc.get(p.doc, 0) + 1
        doc = index.docs[p.doc]
        results.append(
            {
                "doc_id": doc["doc_id"],
                "title": doc["title"],
                "snippet": _snippet(index, p, terms),
                "line": p.line,
                "date": index.dates[p.doc],
            }
        )
        if len(results) == k:
            break
    return results


# ------------------------------------------------------------------ read ----


def read_doc(index: DocIndex, doc_id: str, start_line: int = 1) -> DocWindow:
    if doc_id not in index.by_id:
        raise LookupError(f"no document with doc_id {doc_id!r}")
    i = index.by_id[doc_id]
    lines = index.lines[i]
    total = len(lines)
    if not isinstance(start_line, int) or not 1 <= start_line <= total:
        raise ValueError(f"start_line must be between 1 and {total} for {doc_id!r}, got {start_line!r}")
    end, used, counted = start_line, count_tokens(lines[start_line - 1]), 1
    while end < total:
        nxt = lines[end]  # line end + 1
        if nxt.strip():
            cost = count_tokens(nxt) + 1  # + the joining newline
            if used + cost > WINDOW_TOKENS or counted >= WINDOW_LINES:
                break
            used += cost
            counted += 1
        end += 1
    return {
        "doc_id": doc_id,
        "start_line": start_line,
        "end_line": end,
        "total_lines": total,
        "text": "\n".join(lines[start_line - 1 : end]),
    }
