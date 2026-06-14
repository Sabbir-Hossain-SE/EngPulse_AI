"""CI & Test-Health Detector (Module C).

Deterministic detectors over CI runs:
  * Flaky tests — a test that fails in one run and passes in another on the
    *same commit SHA* (no code change), ranked by flip rate.
  * Failure clusters — recurring failures grouped by signature (the failing
    test set, or the workflow when no test names are available).
  * Duration trends — per-workflow build-time growth, flagged as a regression.

Every finding is grounded in specific CI run ids. No LLM.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from engpulse.db.models import CIRun, Repository
from engpulse.metrics.thresholds import Thresholds, load_thresholds


class FlakyTest(BaseModel):
    test: str
    flip_rate: float
    fail_runs: int
    total_runs: int
    commit_shas: list[str] = Field(default_factory=list)
    evidence_run_ids: list[int] = Field(default_factory=list)


class FailureCluster(BaseModel):
    signature: str
    count: int
    run_ids: list[int] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)


class DurationTrend(BaseModel):
    workflow: str
    runs: int
    avg_seconds: float
    first_seconds: float
    last_seconds: float
    regression: bool = False


class CIHealthReport(BaseModel):
    repo: str
    flaky_tests: list[FlakyTest] = Field(default_factory=list)
    failure_clusters: list[FailureCluster] = Field(default_factory=list)
    duration_trends: list[DurationTrend] = Field(default_factory=list)

    def flaky_keys(self) -> set[tuple[str, str]]:
        """(test, sha) pairs flagged flaky — the unit the eval harness scores."""

        return {
            (f.test, sha) for f in self.flaky_tests for sha in f.commit_shas
        }


def _detect_flaky(runs_by_sha: dict[str, list[CIRun]], min_runs: int) -> list[FlakyTest]:
    acc: dict[str, dict] = {}
    for sha, runs in runs_by_sha.items():
        if len(runs) < min_runs:
            continue
        if not any(r.conclusion == "success" for r in runs):
            continue  # need a passing run on this SHA for a flip
        failing_tests: set[str] = set()
        for r in runs:
            if r.conclusion == "failure":
                failing_tests.update(r.failed_tests or [])
        for test in failing_tests:
            entry = acc.setdefault(
                test, {"shas": set(), "fail_runs": 0, "total_runs": 0, "run_ids": []}
            )
            entry["shas"].add(sha)
            entry["total_runs"] += len(runs)
            entry["fail_runs"] += sum(1 for r in runs if test in (r.failed_tests or []))
            entry["run_ids"].extend(r.github_id for r in runs if r.github_id is not None)

    flaky = [
        FlakyTest(
            test=test,
            fail_runs=data["fail_runs"],
            total_runs=data["total_runs"],
            flip_rate=round(data["fail_runs"] / data["total_runs"], 4)
            if data["total_runs"]
            else 0.0,
            commit_shas=sorted(data["shas"]),
            evidence_run_ids=sorted(set(data["run_ids"])),
        )
        for test, data in acc.items()
    ]
    return sorted(flaky, key=lambda f: f.flip_rate, reverse=True)


def _cluster_failures(runs: list[CIRun]) -> list[FailureCluster]:
    clusters: dict[str, dict] = defaultdict(lambda: {"run_ids": [], "workflows": set()})
    for r in runs:
        if r.conclusion != "failure":
            continue
        signature = ", ".join(sorted(r.failed_tests or [])) or (r.workflow or "unknown")
        clusters[signature]["run_ids"].append(r.github_id)
        clusters[signature]["workflows"].add(r.workflow)
    return sorted(
        (
            FailureCluster(
                signature=sig,
                count=len(data["run_ids"]),
                run_ids=[rid for rid in data["run_ids"] if rid is not None],
                workflows=sorted(w for w in data["workflows"] if w),
            )
            for sig, data in clusters.items()
        ),
        key=lambda c: c.count,
        reverse=True,
    )


def _duration_trends(
    runs: list[CIRun], min_runs: int, regression_pct: float
) -> list[DurationTrend]:
    by_workflow: dict[str, list[CIRun]] = defaultdict(list)
    for r in runs:
        if r.duration_seconds is not None and r.workflow:
            by_workflow[r.workflow].append(r)

    trends = []
    for workflow, wf_runs in by_workflow.items():
        wf_runs.sort(key=lambda r: r.run_started_at or r.id)
        durations = [r.duration_seconds for r in wf_runs]
        first, last = durations[0], durations[-1]
        regression = (
            len(durations) >= min_runs and first > 0 and last > first * (1 + regression_pct)
        )
        trends.append(DurationTrend(
            workflow=workflow,
            runs=len(durations),
            avg_seconds=round(sum(durations) / len(durations), 2),
            first_seconds=first,
            last_seconds=last,
            regression=regression,
        ))
    return sorted(trends, key=lambda t: t.workflow)


def compute_ci_health(
    session: Session,
    repo_full_name: str,
    thresholds: Thresholds | None = None,
) -> CIHealthReport:
    thresholds = thresholds or load_thresholds()
    cfg = thresholds.ci_health

    repo = session.scalars(
        select(Repository).where(Repository.full_name == repo_full_name)
    ).first()
    report = CIHealthReport(repo=repo_full_name)
    if repo is None:
        return report

    runs = list(
        session.scalars(select(CIRun).where(CIRun.repo_id == repo.id)).all()
    )
    runs_by_sha: dict[str, list[CIRun]] = defaultdict(list)
    for r in runs:
        if r.commit_sha:
            runs_by_sha[r.commit_sha].append(r)

    report.flaky_tests = _detect_flaky(runs_by_sha, cfg.flaky_min_runs)
    report.failure_clusters = _cluster_failures(runs)
    report.duration_trends = _duration_trends(
        runs, cfg.duration_min_runs, cfg.duration_regression_pct
    )
    return report
