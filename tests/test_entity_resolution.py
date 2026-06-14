"""Sub-step 2.3 — entity resolution: key extraction, PR↔Issue links, identity merge."""

from __future__ import annotations

import asyncio

from engpulse.connectors.github.client import FixtureGitHubClient
from engpulse.connectors.linear.client import FixtureLinearClient
from engpulse.db.models import Commit, Issue, Person, PullRequest
from engpulse.ingest.github_ingest import _fetch as gh_fetch
from engpulse.ingest.github_ingest import _persist as gh_persist
from engpulse.ingest.linear_ingest import _persist as linear_persist
from engpulse.resolve.identity import merge_people
from engpulse.resolve.keys import extract_issue_keys, has_closing_keyword
from engpulse.resolve.pr_issue import link_prs_to_issues

GH_SCOPE = "engpulse-demo/demo-repo"
LINEAR_SCOPE = "linear:ENG"


def _ingest_all(db_session, fixtures_dir):
    gh = FixtureGitHubClient(fixtures_dir)
    bundle = asyncio.run(gh_fetch(gh, "engpulse-demo", "demo-repo", 50, 100, 100))
    gh_persist(db_session, GH_SCOPE, bundle)
    issues = asyncio.run(FixtureLinearClient(fixtures_dir).list_issues(team_key="ENG"))
    linear_persist(db_session, LINEAR_SCOPE, issues)
    db_session.flush()


# --- key extraction --------------------------------------------------------

def test_extract_issue_keys_case_insensitive():
    assert extract_issue_keys("alice/eng-101-retry") == ["ENG-101"]
    assert extract_issue_keys("Closes ENG-102 and ENG-102") == ["ENG-102"]
    assert extract_issue_keys("no key here") == []
    assert extract_issue_keys(None) == []


def test_closing_keyword_detection():
    assert has_closing_keyword("Closes ENG-102") is True
    assert has_closing_keyword("Fixes the bug") is True
    assert has_closing_keyword("Part of ENG-103 epic") is False


# --- PR <-> Issue linking --------------------------------------------------

def test_pr_issue_linking_methods(db_session, fixtures_dir):
    _ingest_all(db_session, fixtures_dir)
    result = link_prs_to_issues(db_session)
    db_session.commit()

    assert result.total_prs == 3
    assert result.linked == 3
    assert result.unlinked == []
    # PR101 via branch, PR102 via closing keyword, PR103 via body mention
    assert result.by_method == {"branch": 1, "body_keyword": 1, "body_mention": 1}

    by_number = {pr.number: pr for pr in db_session.query(PullRequest).all()}
    eng101 = db_session.query(Issue).filter(Issue.key == "ENG-101").one()
    assert by_number[101].linked_issue_id == eng101.id
    assert by_number[101].linked_issue_method == "branch"
    assert by_number[102].linked_issue_method == "body_keyword"
    assert by_number[102].linked_issue_confidence == 0.95


def test_pr_not_linked_to_unknown_key(db_session, fixtures_dir):
    # Ingest only GitHub (no Linear issues), so no keys are valid → nothing links.
    gh = FixtureGitHubClient(fixtures_dir)
    bundle = asyncio.run(gh_fetch(gh, "engpulse-demo", "demo-repo", 50, 100, 100))
    gh_persist(db_session, GH_SCOPE, bundle)
    db_session.flush()

    result = link_prs_to_issues(db_session)
    assert result.linked == 0
    assert sorted(result.unlinked) == [101, 102, 103]


# --- identity merge --------------------------------------------------------

def test_identity_merge_by_email(db_session, fixtures_dir):
    _ingest_all(db_session, fixtures_dir)
    link_prs_to_issues(db_session)

    # Before: alice(gh), bob(gh), carol(gh), alice(linear), bob(linear) = 5
    assert db_session.query(Person).count() == 5

    result = merge_people(db_session)
    db_session.commit()

    assert result.people_before == 5
    assert result.people_after == 3  # alice, bob merged; carol untouched
    assert len(result.merges) == 2
    assert all(m.method == "email" for m in result.merges)

    # The merged alice carries BOTH identities.
    alice = db_session.query(Person).filter(Person.email == "alice@example.com").one()
    assert alice.github_login == "alice"
    assert alice.tracker_id == "lin-alice"

    # carol (reviewer-only, no email) is left alone.
    assert db_session.query(Person).filter(Person.github_login == "carol").count() == 1


def test_merge_repoints_foreign_keys(db_session, fixtures_dir):
    _ingest_all(db_session, fixtures_dir)
    link_prs_to_issues(db_session)
    merge_people(db_session)
    db_session.commit()

    alice = db_session.query(Person).filter(Person.email == "alice@example.com").one()
    # ENG-101 + ENG-103 were assigned to the Linear alice; now point at merged alice.
    assert db_session.query(Issue).filter(Issue.assignee_id == alice.id).count() == 2
    # alice authored PRs 101 & 103 and commits — all on the canonical row.
    assert db_session.query(PullRequest).filter(PullRequest.author_id == alice.id).count() == 2
    assert db_session.query(Commit).filter(Commit.author_id == alice.id).count() >= 2
    # No orphaned duplicate identities remain.
    assert db_session.query(Person).filter(Person.tracker_id == "lin-alice").count() == 1


def test_resolution_is_idempotent(db_session, fixtures_dir):
    _ingest_all(db_session, fixtures_dir)
    link_prs_to_issues(db_session)
    merge_people(db_session)
    db_session.commit()

    # Second pass: links stay put and no further merges happen.
    second_links = link_prs_to_issues(db_session)
    second_merge = merge_people(db_session)
    db_session.commit()

    assert second_links.linked == 3
    assert second_merge.people_before == 3
    assert second_merge.people_after == 3
    assert second_merge.merges == []
    assert db_session.query(Person).count() == 3
