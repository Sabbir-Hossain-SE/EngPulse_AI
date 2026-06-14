"""Sub-step 2.4 — the labeled synthetic corpus: validity + pipeline compatibility."""

from __future__ import annotations

import asyncio

from engpulse.db.models import Issue, Person, PullRequest
from engpulse.eval import load_corpus, validate_corpus
from engpulse.ingest.github_ingest import _fetch as gh_fetch
from engpulse.ingest.github_ingest import _persist as gh_persist
from engpulse.ingest.linear_ingest import _persist as linear_persist
from engpulse.resolve.identity import merge_people
from engpulse.resolve.pr_issue import link_prs_to_issues


def test_corpus_loads_with_typed_labels():
    corpus = load_corpus()
    assert corpus.labels.repo == "acme/payments"
    assert len(corpus.labels.stale_prs) == 1
    assert len(corpus.labels.flaky_tests) == 1
    assert len(corpus.labels.deadline_drifts) == 1
    assert len(corpus.labels.bus_factors) == 1
    assert len(corpus.labels.pr_issue_links) == 3
    assert len(corpus.labels.identities) == 2


def test_corpus_is_internally_consistent():
    problems = validate_corpus(load_corpus())
    assert problems == [], f"corpus has consistency problems: {problems}"


def test_injected_problems_are_real():
    corpus = load_corpus()

    # Flaky: the labeled SHA really flips failure -> success.
    flaky = corpus.labels.flaky_tests[0]
    sha_runs = [r for r in corpus.runs if r["head_sha"] == flaky.commit_sha]
    assert {"failure", "success"} <= {r["conclusion"] for r in sha_runs}

    # Bus factor: the module is touched by exactly one author.
    bf = corpus.labels.bus_factors[0]
    authors = {
        c["author"]["login"] for c in corpus.commits if bf.module in c.get("files", [])
    }
    assert authors == {"dave"}

    # Drift: original due predates current due.
    drift = corpus.labels.deadline_drifts[0]
    assert drift.original_due < drift.current_due


def test_corpus_flows_through_ingest_and_resolve(db_session):
    corpus = load_corpus()
    owner, name = corpus.repo["full_name"].split("/", 1)

    bundle = asyncio.run(gh_fetch(corpus.github_client(), owner, name, 50, 100, 100))
    gh_persist(db_session, "acme/payments", bundle)
    issues = asyncio.run(corpus.linear_client().list_issues(team_key="PAY"))
    linear_persist(db_session, "linear:PAY", issues)
    db_session.flush()

    # People count before merge matches the label.
    assert db_session.query(Person).count() == corpus.labels.people_before  # 6

    links = link_prs_to_issues(db_session)
    merge = merge_people(db_session)
    db_session.commit()

    # Identity merge matches the label.
    assert merge.people_before == corpus.labels.people_before
    assert merge.people_after == corpus.labels.people_after  # 4
    assert len(merge.merges) == 2

    # PR↔Issue links match the labels exactly (issue + method).
    actual = {
        pr.number: (pr.linked_issue.key, pr.linked_issue_method)
        for pr in db_session.query(PullRequest).all()
        if pr.linked_issue_id is not None
    }
    expected = {
        link.pr_number: (link.issue, link.method)
        for link in corpus.labels.pr_issue_links
    }
    assert actual == expected
    assert links.linked == 3

    # The drift issue carries original != current due in the DB.
    pay12 = db_session.query(Issue).filter(Issue.key == "PAY-12").one()
    assert pay12.original_due_date != pay12.current_due_date
