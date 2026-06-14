"""Sub-step 4.1 — ownership graph + bus-factor detection + eval."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from engpulse.db.models import Commit, Person, Repository
from engpulse.eval import load_corpus, prf
from engpulse.ingest.github_ingest import _fetch as gh_fetch
from engpulse.ingest.github_ingest import _persist as gh_persist
from engpulse.metrics import compute_knowledge_risk

UTC = timezone.utc


def _setup(db_session):
    repo = Repository(github_id=1, full_name="acme/x", name="x")
    dave = Person(github_user_id=1, github_login="dave")
    erin = Person(github_user_id=2, github_login="erin")
    db_session.add_all([repo, dave, erin])
    db_session.flush()
    return repo, dave, erin


def test_single_owner_module_with_churn_is_flagged(db_session):
    repo, dave, erin = _setup(db_session)
    # auth/tokens.py: 3 commits all by dave → single owner + churn → flagged.
    # shared.py: touched by dave AND erin → not single-owner.
    # one_off.py: single owner but only 1 commit → below the churn floor.
    db_session.add_all([
        Commit(sha="c1", repo_id=repo.id, author_id=dave.id,
               files_changed=["auth/tokens.py", "shared.py"],
               committed_at=datetime(2026, 5, 1, tzinfo=UTC)),
        Commit(sha="c2", repo_id=repo.id, author_id=dave.id,
               files_changed=["auth/tokens.py"],
               committed_at=datetime(2026, 5, 2, tzinfo=UTC)),
        Commit(sha="c3", repo_id=repo.id, author_id=dave.id,
               files_changed=["auth/tokens.py", "one_off.py"],
               committed_at=datetime(2026, 5, 3, tzinfo=UTC)),
        Commit(sha="c4", repo_id=repo.id, author_id=erin.id,
               files_changed=["shared.py"],
               committed_at=datetime(2026, 5, 4, tzinfo=UTC)),
    ])
    db_session.flush()

    report = compute_knowledge_risk(db_session, "acme/x")
    modules = {m.module: m for m in report.modules}

    assert modules["auth/tokens.py"].commit_count == 3
    assert modules["auth/tokens.py"].contributors == ["dave"]
    assert modules["auth/tokens.py"].ownership_share == 1.0
    assert "single_point_of_failure" in modules["auth/tokens.py"].flags

    # shared.py has two contributors → not a SPOF.
    assert "single_point_of_failure" not in modules["shared.py"].flags
    # one_off.py is single-owner but only 1 commit → below churn floor.
    assert "single_point_of_failure" not in modules["one_off.py"].flags

    assert report.flagged_modules() == {"auth/tokens.py"}


def test_bus_factor_scores_perfect_on_corpus(db_session):
    corpus = load_corpus()
    owner, name = corpus.repo["full_name"].split("/", 1)
    bundle = asyncio.run(gh_fetch(corpus.github_client(), owner, name, 50, 100, 100))
    gh_persist(db_session, corpus.repo["full_name"], bundle)
    db_session.flush()

    report = compute_knowledge_risk(db_session, corpus.repo["full_name"])
    predicted = report.flagged_modules()
    expected = {b.module for b in corpus.labels.bus_factors}
    assert predicted == {"auth/tokens.py"}

    score = prf("bus_factor", predicted, expected)
    assert score.precision == 1.0 and score.recall == 1.0
