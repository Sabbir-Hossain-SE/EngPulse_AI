"""Link pull requests to their Linear issue, with a method + confidence.

Signals, strongest first:
  body + closing keyword  ("Closes ENG-102")   → 0.95  body_keyword
  body mention            ("Part of ENG-103")  → 0.85  body_mention
  branch name             ("alice/eng-101-…")  → 0.80  branch
  title mention           ("… ENG-104 …")      → 0.70  title

Only keys that exist as issues in the DB are linked (favours precision). Each PR
gets its highest-confidence candidate; the method + confidence are recorded so
the eval harness can measure linking precision/recall.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from engpulse.db.models import Issue, PullRequest
from engpulse.resolve.keys import extract_issue_keys, has_closing_keyword


@dataclass
class PrIssueResult:
    total_prs: int = 0
    linked: int = 0
    unlinked: list[int] = field(default_factory=list)
    by_method: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "total_prs": self.total_prs,
            "linked": self.linked,
            "unlinked": self.unlinked,
            "by_method": self.by_method,
        }


def _candidates(pr: PullRequest) -> list[tuple[str, str, float]]:
    """(key, method, confidence) candidates for one PR, across all signals."""

    out: list[tuple[str, str, float]] = []
    body_method = "body_keyword" if has_closing_keyword(pr.body) else "body_mention"
    body_conf = 0.95 if body_method == "body_keyword" else 0.85
    for key in extract_issue_keys(pr.body):
        out.append((key, body_method, body_conf))
    for key in extract_issue_keys(pr.head_ref):
        out.append((key, "branch", 0.80))
    for key in extract_issue_keys(pr.title):
        out.append((key, "title", 0.70))
    return out


def link_prs_to_issues(session: Session) -> PrIssueResult:
    issues_by_key = {i.key: i for i in session.scalars(select(Issue)).all()}
    valid = set(issues_by_key)

    result = PrIssueResult()
    for pr in session.scalars(select(PullRequest)).all():
        result.total_prs += 1
        candidates = [c for c in _candidates(pr) if c[0] in valid]
        if not candidates:
            pr.linked_issue_id = None
            pr.linked_issue_method = None
            pr.linked_issue_confidence = None
            result.unlinked.append(pr.number)
            continue
        key, method, confidence = max(candidates, key=lambda c: c[2])
        pr.linked_issue_id = issues_by_key[key].id
        pr.linked_issue_method = method
        pr.linked_issue_confidence = confidence
        result.linked += 1
        result.by_method[method] = result.by_method.get(method, 0) + 1

    session.flush()
    return result
