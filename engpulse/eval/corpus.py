"""Load and validate the labeled synthetic corpus.

The corpus mirrors the connector fixture shapes, so it flows through the real
ingest → resolve pipeline. ``validate_corpus`` is a static consistency check:
every label must reference an entity that actually exists in the corpus, and the
injected signals (flaky flip, due-date moves, single-owner module) must really be
present — so the ground truth can be trusted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from engpulse.connectors.github.client import FixtureGitHubClient
from engpulse.connectors.linear.client import FixtureLinearClient
from engpulse.eval.labels import CorpusLabels

DEFAULT_CORPUS_DIR = Path(__file__).resolve().parents[2] / "datasets" / "synthetic"


@dataclass
class Corpus:
    directory: Path
    repo: dict
    pull_requests: list[dict]
    reviews: dict[str, list[dict]]
    commits: list[dict]
    runs: list[dict]
    issues: list[dict]
    labels: CorpusLabels

    def github_client(self) -> FixtureGitHubClient:
        return FixtureGitHubClient(self.directory)

    def linear_client(self) -> FixtureLinearClient:
        return FixtureLinearClient(self.directory)


def _read(directory: Path, name: str):
    return json.loads((directory / name).read_text())


def load_corpus(directory: str | Path | None = None) -> Corpus:
    directory = Path(directory) if directory else DEFAULT_CORPUS_DIR
    return Corpus(
        directory=directory,
        repo=_read(directory, "github_repo.json"),
        pull_requests=_read(directory, "github_prs.json"),
        reviews=_read(directory, "github_reviews.json"),
        commits=_read(directory, "github_commits.json"),
        runs=_read(directory, "github_runs.json"),
        issues=_read(directory, "linear_issues.json"),
        labels=CorpusLabels.model_validate(_read(directory, "labels.json")),
    )


def _github_logins(corpus: Corpus) -> set[str]:
    logins: set[str] = set()
    for pr in corpus.pull_requests:
        if (pr.get("user") or {}).get("login"):
            logins.add(pr["user"]["login"])
        for rr in pr.get("requested_reviewers", []):
            if rr.get("login"):
                logins.add(rr["login"])
    for review_list in corpus.reviews.values():
        for review in review_list:
            if (review.get("user") or {}).get("login"):
                logins.add(review["user"]["login"])
    for commit in corpus.commits:
        if (commit.get("author") or {}).get("login"):
            logins.add(commit["author"]["login"])
    return logins


def _commits_touching(corpus: Corpus, module: str) -> set[str]:
    authors: set[str] = set()
    for commit in corpus.commits:
        if module in (commit.get("files") or []):
            login = (commit.get("author") or {}).get("login")
            if login:
                authors.add(login)
    return authors


def validate_corpus(corpus: Corpus) -> list[str]:
    """Return a list of consistency problems; empty means the corpus is valid."""

    problems: list[str] = []
    pr_numbers = {pr["number"] for pr in corpus.pull_requests}
    issue_keys = {i["identifier"] for i in corpus.issues}
    issue_assignees = {(i.get("assignee") or {}).get("id") for i in corpus.issues}
    run_shas = {r.get("head_sha") for r in corpus.runs}
    gh_logins = _github_logins(corpus)

    for s in corpus.labels.stale_prs:
        if s.pr_number not in pr_numbers:
            problems.append(f"stale_pr references unknown PR #{s.pr_number}")

    for f in corpus.labels.flaky_tests:
        if f.commit_sha not in run_shas:
            problems.append(f"flaky_test sha {f.commit_sha} has no CI run")
            continue
        sha_runs = [r for r in corpus.runs if r.get("head_sha") == f.commit_sha]
        conclusions = {r.get("conclusion") for r in sha_runs}
        if not ({"failure"} <= conclusions and {"success"} <= conclusions):
            problems.append(
                f"flaky_test {f.test} sha {f.commit_sha} does not flip fail↔pass"
            )
        if not any(f.test in (r.get("failed_tests") or []) for r in sha_runs):
            problems.append(f"flaky_test {f.test} not present in any failed run")

    for d in corpus.labels.deadline_drifts:
        if d.issue not in issue_keys:
            problems.append(f"deadline_drift references unknown issue {d.issue}")
            continue
        issue = next(i for i in corpus.issues if i["identifier"] == d.issue)
        history = (issue.get("history") or {}).get("nodes", [])
        moves = sum(1 for h in history if h.get("fromDueDate") or h.get("toDueDate"))
        if moves != d.moves:
            problems.append(
                f"deadline_drift {d.issue}: label says {d.moves} moves, corpus has {moves}"
            )

    for b in corpus.labels.bus_factors:
        authors = _commits_touching(corpus, b.module)
        if not authors:
            problems.append(f"bus_factor module {b.module} touched by no commit")
        elif authors != set(b.contributors):
            problems.append(
                f"bus_factor {b.module}: label contributors {b.contributors} "
                f"!= corpus {sorted(authors)}"
            )
        if b.contributor_count != len(b.contributors):
            problems.append(f"bus_factor {b.module}: contributor_count mismatch")

    for link in corpus.labels.pr_issue_links:
        if link.pr_number not in pr_numbers:
            problems.append(f"pr_issue_link references unknown PR #{link.pr_number}")
        if link.issue not in issue_keys:
            problems.append(f"pr_issue_link references unknown issue {link.issue}")

    for ident in corpus.labels.identities:
        if ident.github_login not in gh_logins:
            problems.append(f"identity github_login {ident.github_login} not in corpus")
        if ident.tracker_id not in issue_assignees:
            problems.append(f"identity tracker_id {ident.tracker_id} not an assignee")

    # Cross-check the expected person counts against the raw corpus.
    before = len(gh_logins) + len({a for a in issue_assignees if a})
    merges = sum(
        1
        for i in corpus.labels.identities
        if i.github_login in gh_logins and i.tracker_id in issue_assignees
    )
    if corpus.labels.people_before not in (None, before):
        problems.append(
            f"people_before: label {corpus.labels.people_before} != corpus {before}"
        )
    if corpus.labels.people_after not in (None, before - merges):
        problems.append(
            f"people_after: label {corpus.labels.people_after} != corpus {before - merges}"
        )

    return problems
