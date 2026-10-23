"""Problem (daily_digest): summarize one day of email for a busy employee."""

from __future__ import annotations

from cs329z_hw1.types import Email, LMCallable

EMPTY_DAY = "No email today."


def write_digest(emails: list[Email], lm: LMCallable) -> str:
    if not emails:
        return EMPTY_DAY
    # Placeholder until classification, aggregation and the final call exist.
    return f"{len(emails)} emails today."
