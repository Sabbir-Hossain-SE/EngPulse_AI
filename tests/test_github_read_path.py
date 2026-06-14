"""The end-to-end read path works offline: fixture → DTO → ORM → DB."""

from __future__ import annotations

from engpulse.connectors.github.client import FixtureGitHubClient
from engpulse.connectors.github.normalize import to_pull_request, to_repository
from engpulse.db.models import Person, PullRequest, Repository
from engpulse.ingest.repo_sync import _fetch, _persist, _summarize_only


async def test_fixture_client_parses_dtos(fixtures_dir):
    client = FixtureGitHubClient(fixtures_dir)
    repo = await client.get_repository("engpulse-demo", "demo-repo")
    prs = await client.list_pull_requests("engpulse-demo", "demo-repo", limit=20)

    assert repo.full_name == "engpulse-demo/demo-repo"
    assert repo.default_branch == "main"
    assert len(prs) == 3
    assert prs[0].number == 101
    assert prs[0].additions == 120
    assert {r["login"] for r in prs[0].requested_reviewers} == {"bob", "carol"}


def test_normalization_maps_fields(fixtures_dir):
    import json

    repo_dto_data = json.loads((fixtures_dir / "github_repo.json").read_text())
    from engpulse.connectors.github.schemas import RepositoryDTO

    repo = to_repository(RepositoryDTO.from_api(repo_dto_data))
    assert isinstance(repo, Repository)
    assert repo.github_id == 700100200
    assert repo.name == "demo-repo"


async def test_persist_links_authors_and_reviewers(db_session, fixtures_dir):
    client = FixtureGitHubClient(fixtures_dir)
    repo_dto, pr_dtos = await _fetch(client, "engpulse-demo", "demo-repo", limit=20)

    summary = _persist(db_session, repo_dto, pr_dtos)
    db_session.commit()

    assert summary.persisted is True
    assert summary.pull_requests == 3
    # alice + bob author PRs -> 2 distinct authors
    assert summary.authors == 2
    # bob, carol, alice appear as reviewers -> 3 distinct reviewers
    assert summary.reviewers == 3

    assert db_session.query(Repository).count() == 1
    assert db_session.query(PullRequest).count() == 3
    pr101 = (
        db_session.query(PullRequest).filter(PullRequest.number == 101).one()
    )
    assert pr101.author.github_login == "alice"
    assert {r.github_login for r in pr101.reviewers} == {"bob", "carol"}


async def test_persist_is_idempotent(db_session, fixtures_dir):
    client = FixtureGitHubClient(fixtures_dir)
    repo_dto, pr_dtos = await _fetch(client, "engpulse-demo", "demo-repo", limit=20)

    _persist(db_session, repo_dto, pr_dtos)
    db_session.commit()
    _persist(db_session, repo_dto, pr_dtos)  # second run must not duplicate
    db_session.commit()

    assert db_session.query(Repository).count() == 1
    assert db_session.query(PullRequest).count() == 3
    assert db_session.query(Person).count() == 3  # alice, bob, carol


async def test_dry_run_summary_counts(fixtures_dir):
    client = FixtureGitHubClient(fixtures_dir)
    repo_dto, pr_dtos = await _fetch(client, "engpulse-demo", "demo-repo", limit=20)
    summary = _summarize_only(repo_dto, pr_dtos)
    assert summary.persisted is False
    assert summary.pull_requests == 3
    assert summary.authors == 2
    assert summary.sample_pr_numbers == [101, 102, 103]
