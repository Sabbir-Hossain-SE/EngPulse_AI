"""Entity resolution: PR↔Issue linking and cross-system identity merge."""

from engpulse.resolve.identity import IdentityResult, merge_people
from engpulse.resolve.keys import extract_issue_keys
from engpulse.resolve.pr_issue import PrIssueResult, link_prs_to_issues
from engpulse.resolve.run import ResolutionReport, resolve_entities

__all__ = [
    "extract_issue_keys",
    "link_prs_to_issues",
    "PrIssueResult",
    "merge_people",
    "IdentityResult",
    "resolve_entities",
    "ResolutionReport",
]
