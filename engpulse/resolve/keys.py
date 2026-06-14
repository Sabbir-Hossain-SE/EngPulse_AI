"""Issue-key extraction from free text (branch names, PR bodies, titles).

Linear keys look like ``ENG-123``. We uppercase before matching so a lowercase
branch ref (``alice/eng-101-...``) and an uppercase body mention (``ENG-101``)
both resolve to the same key.
"""

from __future__ import annotations

import re

# Two+ leading letters/digits, a hyphen, then digits — e.g. ENG-123, OPS2-7.
_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")

# A closing keyword anywhere in the text bumps a body mention to high confidence.
_CLOSING_RE = re.compile(
    r"\b(clos(?:e|es|ed)|fix(?:e|es|ed)?|resolv(?:e|es|ed))\b", re.IGNORECASE
)


def extract_issue_keys(text: str | None) -> list[str]:
    """Unique issue keys in ``text``, order-preserving."""

    if not text:
        return []
    seen: dict[str, None] = {}
    for match in _KEY_RE.findall(text.upper()):
        seen.setdefault(match, None)
    return list(seen)


def has_closing_keyword(text: str | None) -> bool:
    return bool(text and _CLOSING_RE.search(text))
