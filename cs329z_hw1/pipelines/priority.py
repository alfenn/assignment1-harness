"""Problem (priority): classify one email as urgent, normal, or ignore."""

from __future__ import annotations

import re
from datetime import datetime

from cs329z_hw1.data import REPO_ROOT
from cs329z_hw1.types import Email, LMCallable

RUBRIC = (REPO_ROOT / "data" / "priority_rubric.md").read_text()

SYSTEM_PROMPT = f"""You triage email. Classify one email for the person it is addressed to, at the time it was sent, using this rubric:

{RUBRIC}

Reply in exactly this format, with nothing else:
LABEL: <urgent, normal, or ignore>
REASON: <one sentence>"""

# The format the prompt asks for.
_STRICT_LABEL = re.compile(r"LABEL:\s*(urgent|normal|ignore)\b")
_REASON = re.compile(r"REASON:\s*(.+)")
# Fallback for replies that ignore the format: the last label word anywhere.
_ANY_LABEL = re.compile(r"\b(urgent|normal|ignore)\b", re.I)
_NO_REASON = "The model reply gave no reason."


def _format_email(email: Email) -> str:
    date = email["date"]
    try:
        date = datetime.fromisoformat(date.replace("Z", "+00:00")).strftime("%A %Y-%m-%d %H:%M UTC")
    except ValueError:
        pass
    return (
        f"From: {email['from']}\n"
        f"To: {', '.join(email['to'])}\n"
        f"Date: {date}\n"
        f"Subject: {email['subject']}\n\n"
        f"{email['body']}"
    )


def parse_priority(reply: str) -> dict:
    text = reply or ""

    m = _STRICT_LABEL.search(text)
    if m:
        category = m.group(1)
    else:
        found = _ANY_LABEL.findall(text)
        category = found[-1].lower() if found else "unknown"

    r = _REASON.search(text)
    reason = r.group(1).strip() if r else ""
    return {"category": category, "reason": reason or _NO_REASON}


def classify_priority(email: Email, lm: LMCallable) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _format_email(email)},
    ]
    try:
        reply = lm(messages)
    except Exception as exc:
        return {"category": "unknown", "reason": f"Model call failed: {type(exc).__name__}."}
    return parse_priority(reply)
