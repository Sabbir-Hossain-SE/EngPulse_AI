"""Run entity resolution over the current DB and return a resolution report.

Order matters: link PRs to issues first, then merge identities (so reviewer/
author links are repointed onto the canonical person). The report is the
measurable artifact the eval harness scores precision/recall against.
"""

from __future__ import annotations

from dataclasses import dataclass

from engpulse.db.base import get_session_factory
from engpulse.logging import get_logger
from engpulse.resolve.identity import merge_people
from engpulse.resolve.pr_issue import link_prs_to_issues

log = get_logger(__name__)


@dataclass
class ResolutionReport:
    pr_issue: dict
    identity: dict


def resolve_entities(dry_run: bool = False) -> ResolutionReport:
    """Link PRs↔issues and merge identities. ``dry_run`` rolls back at the end."""

    session = get_session_factory()()
    try:
        pr_result = link_prs_to_issues(session)
        identity_result = merge_people(session)
        report = ResolutionReport(
            pr_issue=pr_result.as_dict(),
            identity=identity_result.as_dict(),
        )
        if dry_run:
            session.rollback()
        else:
            session.commit()
        log.info(
            "Resolution: %d/%d PRs linked, %d people merged (%d→%d)",
            pr_result.linked, pr_result.total_prs,
            len(identity_result.merges),
            identity_result.people_before, identity_result.people_after,
        )
        return report
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
