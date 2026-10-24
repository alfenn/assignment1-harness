"""Problem (daily_digest): summarize one day of email for a busy employee."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from cs329z_hw1.llm import OutputTruncated
from cs329z_hw1.pipelines.priority import classify_priority
from cs329z_hw1.types import Email, LMCallable

EMPTY_DAY = "No email today."
# The classification calls are independent; this many run at once.
MAX_WORKERS = 16
# The hard limit on len(digest.split()), and the margin the prompt leaves
# under it, since the model's own word count is approximate.
WORD_LIMIT = 300
WORD_MARGIN = 50
# Characters of each email body shown to the final call.
BODY_CHARS = {"urgent": 800, "normal": 300}
# Longer threads show their first email and the last few.
THREAD_HEAD, THREAD_TAIL = 1, 2

SYSTEM_PROMPT = """You write the morning email digest for a busy employee. You are given the day's email threads that need attention, already sorted: URGENT threads first, then NORMAL ones.

Write the digest in plain text, in this layout:

Urgent:
- <one line per URGENT thread>

Also today:
- <one short line per NORMAL thread, or one line grouping several>

Rules:
- The whole digest is at most {target} words. Be extremely brief.
- Cover every URGENT thread. Each urgent line must name the specific company, project, site, pipeline or plant the thread is about, spelled exactly as in the email, then say what is needed and by when.
- Keep NORMAL lines to a few words each. If space runs short, group or drop NORMAL threads, never URGENT ones.
- If there are no URGENT threads, write "Urgent: nothing today."
- Use only what the threads say. No greeting, no sign-off, no preamble."""

SHORTEN_PROMPT = (
    "That digest is {words} words. Rewrite it in at most {target} words. Keep every "
    "urgent line and the company, project or site name in each; shorten or drop "
    "the other lines. Reply with the digest only."
)


def classify_all(emails: list[Email], lm: LMCallable) -> list[dict]:
    """Classify every email concurrently, in input order.

    Each result is {"email", "category", "reason"}; "unknown" is treated as
    "normal", so category is one of urgent, normal, ignore.
    """

    def classify(email: Email) -> dict:
        result = classify_priority(email, lm)
        category = "normal" if result["category"] == "unknown" else result["category"]
        return {"email": email, "category": category, "reason": result["reason"]}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        return list(pool.map(classify, emails))


_RANK = {"urgent": 0, "normal": 1}


def aggregate(labeled: list[dict]) -> list[dict]:
    """Turn classified emails into digest items, one per thread, most
    important first.

    Ignore emails are dropped one by one, so nothing from them reaches the
    final prompt. The rest are grouped by thread; a thread is urgent if any of
    its emails is. Each item is {"category", "entries"}, with the thread's
    entries in time order (ISO dates compare correctly as strings). Items are
    ordered urgent before normal, then by the thread's first email.
    """
    threads: dict[str, list[dict]] = {}
    for entry in labeled:
        if entry["category"] == "ignore":
            continue
        email = entry["email"]
        threads.setdefault(email.get("thread_id") or email["id"], []).append(entry)

    items = []
    for entries in threads.values():
        entries = sorted(entries, key=lambda e: e["email"]["date"])
        category = min((e["category"] for e in entries), key=_RANK.__getitem__)
        items.append({"category": category, "entries": entries})
    items.sort(key=lambda item: (_RANK[item["category"]], item["entries"][0]["email"]["date"]))
    return items


def _trim(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + " ..."


def format_items(items: list[dict]) -> str:
    blocks = []
    for n, item in enumerate(items, 1):
        entries = item["entries"]
        shown = entries
        if len(entries) > THREAD_HEAD + THREAD_TAIL:
            shown = entries[:THREAD_HEAD] + entries[-THREAD_TAIL:]
        subject = next((e["email"]["subject"] for e in entries if e["email"]["subject"].strip()), "")
        lines = [
            f"[{n}] {item['category'].upper()} ({len(entries)} email{'s' if len(entries) > 1 else ''})",
            f"Subject: {subject or '(no subject)'}",
        ]
        for entry in shown:
            email = entry["email"]
            body = _trim(email["body"], BODY_CHARS[item["category"]]) or "(empty)"
            lines.append(f"- From {email['from']} at {email['date'][11:16]} UTC: {body}")
        # The reason from the latest email that carries the thread's label.
        reason = next(e["reason"] for e in reversed(entries) if e["category"] == item["category"])
        lines.append(f"Why it was flagged: {reason}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def fallback_digest(items: list[dict]) -> str:
    """A plain digest built in code, for when the model's reply is empty."""
    urgent = [item for item in items if item["category"] == "urgent"]
    normal = len(items) - len(urgent)
    subjects = [
        _trim(next((e["email"]["subject"] for e in item["entries"] if e["email"]["subject"].strip()), "(no subject)"), 80)
        for item in urgent
    ]
    lines = ["Urgent: " + ("; ".join(subjects) if subjects else "nothing today.")]
    lines.append(f"Also today: {normal} other thread{'s' if normal != 1 else ''}.")
    return "\n".join(lines)


def _call(lm: LMCallable, messages: list[dict]) -> str:
    # A truncated reply still holds usable text; other errors propagate.
    try:
        return lm(messages) or ""
    except OutputTruncated as exc:
        return exc.text or ""


def write_digest(emails: list[Email], lm: LMCallable, max_words: int | None = None) -> str:
    if not emails:
        return EMPTY_DAY
    items = aggregate(classify_all(emails, lm))
    if not items:
        return "Nothing needs your attention today."

    limit = WORD_LIMIT if max_words is None else max(1, min(WORD_LIMIT, max_words))
    target = max(1, min(WORD_LIMIT - WORD_MARGIN, limit))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(target=target)},
        {"role": "user", "content": format_items(items)},
    ]
    digest = _call(lm, messages).strip()
    if not digest:
        return fallback_digest(items)

    # One retry if the model overshot: it rewrites its own digest shorter,
    # so the result is still text the model wrote, not a cut.
    words = len(digest.split())
    if words > limit:
        shorter = _call(lm, messages + [
            {"role": "assistant", "content": digest},
            {"role": "user", "content": SHORTEN_PROMPT.format(words=words, target=target)},
        ]).strip()
        if shorter and len(shorter.split()) < words:
            digest = shorter
    return digest
