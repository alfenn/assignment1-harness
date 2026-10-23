"""Problem (daily_digest): summarize one day of email for a busy employee."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from cs329z_hw1.pipelines.priority import classify_priority
from cs329z_hw1.types import Email, LMCallable

EMPTY_DAY = "No email today."
# The classification calls are independent; this many run at once.
MAX_WORKERS = 16


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


def write_digest(emails: list[Email], lm: LMCallable) -> str:
    if not emails:
        return EMPTY_DAY
    labeled = classify_all(emails, lm)
    # Placeholder until aggregation and the final call exist.
    counts = {c: sum(item["category"] == c for item in labeled) for c in ("urgent", "normal", "ignore")}
    return f"{counts['urgent']} urgent, {counts['normal']} normal, {counts['ignore']} ignored."
