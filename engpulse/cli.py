"""EngPulse command-line entrypoint.

    engpulse check-config            # show resolved settings (secrets masked)
    engpulse init-db                 # enable pgvector + create all tables
    engpulse sync-repo ...           # run the GitHub read path

Run via the installed console script (`engpulse ...`) or `python -m engpulse.cli`.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from engpulse.config import get_settings
from engpulse.logging import get_logger

app = typer.Typer(add_completion=False, help="EngPulse AI CLI")
console = Console()
log = get_logger(__name__)


@app.command("check-config")
def check_config() -> None:
    """Print the resolved configuration with secrets masked."""

    table = Table(title="EngPulse configuration", show_header=True)
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")
    for key, value in get_settings().safe_dump().items():
        table.add_row(key, str(value))
    console.print(table)


@app.command("init-db")
def init_db() -> None:
    """Enable the pgvector extension and create all tables."""

    from sqlalchemy import text

    from engpulse.db.base import Base, get_engine
    from engpulse.db import models  # noqa: F401  (register models on Base.metadata)

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    console.print(
        f"[green]✓[/green] Schema ready ({len(Base.metadata.tables)} tables) "
        "and pgvector extension enabled."
    )


@app.command("sync-repo")
def sync_repo(
    repo: str = typer.Option(
        None, "--repo", help="owner/name (defaults to GITHUB_REPO from config)"
    ),
    source: str = typer.Option(
        "fixture", "--source", help="'fixture' (offline) or 'live' (GitHub API)"
    ),
    limit: int = typer.Option(20, "--limit", help="max pull requests to read"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="fetch + normalize but do not write to the DB"
    ),
) -> None:
    """Read one repository end-to-end (repo metadata + recent PRs)."""

    from engpulse.ingest import sync_repository

    target = repo or get_settings().github_repo
    if not target:
        console.print(
            "[red]No repo given.[/red] Pass --repo owner/name or set GITHUB_REPO."
        )
        raise typer.Exit(code=2)

    console.print(
        f"Reading [bold]{target}[/bold] via [bold]{source}[/bold] "
        f"(limit={limit}, dry_run={dry_run})…"
    )
    summary = sync_repository(target, source=source, limit=limit, dry_run=dry_run)

    table = Table(title=f"Sync summary — {summary.repo_full_name}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white", justify="right")
    table.add_row("Pull requests", str(summary.pull_requests))
    table.add_row("Distinct authors", str(summary.authors))
    table.add_row("Distinct reviewers", str(summary.reviewers))
    table.add_row("Persisted to DB", "yes" if summary.persisted else "no (dry-run)")
    table.add_row(
        "Sample PR #s", ", ".join(str(n) for n in summary.sample_pr_numbers) or "—"
    )
    console.print(table)


@app.command("ingest-github")
def ingest_github_cmd(
    repo: str = typer.Option(
        None, "--repo", help="owner/name (defaults to GITHUB_REPO from config)"
    ),
    source: str = typer.Option(
        "fixture", "--source", help="'fixture' (offline) or 'live' (GitHub API)"
    ),
    pr_limit: int = typer.Option(50, "--pr-limit", help="max pull requests to read"),
    commit_limit: int = typer.Option(100, "--commit-limit", help="max commits to read"),
    run_limit: int = typer.Option(100, "--run-limit", help="max CI runs to read"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="fetch + count but do not write to the DB"
    ),
    fixtures_dir: str = typer.Option(
        None, "--fixtures-dir", help="fixture corpus directory (for --source fixture)"
    ),
) -> None:
    """Incremental GitHub ingestion: PRs+reviews, commits, and CI runs."""

    from engpulse.ingest import ingest_github

    target = repo or get_settings().github_repo
    if not target:
        console.print("[red]No repo given.[/red] Pass --repo owner/name or set GITHUB_REPO.")
        raise typer.Exit(code=2)

    console.print(
        f"Ingesting [bold]{target}[/bold] via [bold]{source}[/bold] "
        f"(dry_run={dry_run})…"
    )
    report = ingest_github(
        target, source=source, pr_limit=pr_limit,
        commit_limit=commit_limit, run_limit=run_limit, dry_run=dry_run,
        fixtures_dir=fixtures_dir,
    )

    table = Table(title=f"Ingest report — {report.repo_full_name}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white", justify="right")
    table.add_row("Pull requests", str(report.pull_requests))
    table.add_row("Reviews", str(report.reviews))
    table.add_row("Commits", str(report.commits))
    table.add_row("CI runs", str(report.ci_runs))
    table.add_row("CI runs linked to a PR", str(report.ci_runs_linked))
    table.add_row("Persisted to DB", "yes" if report.persisted else "no (dry-run)")
    console.print(table)

    if report.audits:
        _print_audit(report.audits)


@app.command("ingest-linear")
def ingest_linear_cmd(
    source: str = typer.Option(
        "fixture", "--source", help="'fixture' (offline) or 'live' (Linear API)"
    ),
    team_key: str = typer.Option(
        None, "--team", help="scope to a Linear team key (defaults to LINEAR_TEAM_KEY)"
    ),
    limit: int = typer.Option(200, "--limit", help="max issues to read"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="fetch + count but do not write to the DB"
    ),
    fixtures_dir: str = typer.Option(
        None, "--fixtures-dir", help="fixture corpus directory (for --source fixture)"
    ),
) -> None:
    """Incremental Linear ingestion: issues, status, estimates, transitions."""

    from engpulse.ingest import ingest_linear

    team = team_key if team_key is not None else (get_settings().linear_team_key or None)
    console.print(
        f"Ingesting Linear (team={team or 'all'}) via [bold]{source}[/bold] "
        f"(dry_run={dry_run})…"
    )
    report = ingest_linear(
        source=source, team_key=team, limit=limit, dry_run=dry_run,
        fixtures_dir=fixtures_dir,
    )

    table = Table(title=f"Linear ingest report — {report.scope}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white", justify="right")
    table.add_row("Issues", str(report.issues))
    table.add_row("Distinct assignees", str(report.assignees))
    table.add_row("With deadline drift", str(report.with_due_drift))
    table.add_row("With re-estimation", str(report.with_reestimation))
    table.add_row("Persisted to DB", "yes" if report.persisted else "no (dry-run)")
    console.print(table)

    if report.audits:
        _print_audit(report.audits)


@app.command("resolve")
def resolve_cmd(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="compute links/merges but roll back (no writes)"
    ),
) -> None:
    """Entity resolution: link PRs↔issues and merge GitHub↔Linear identities."""

    from engpulse.resolve import resolve_entities

    console.print(f"Resolving entities (dry_run={dry_run})…")
    report = resolve_entities(dry_run=dry_run)

    pr = report.pr_issue
    pr_table = Table(title="PR ↔ Issue linking")
    pr_table.add_column("Metric", style="cyan")
    pr_table.add_column("Value", style="white", justify="right")
    pr_table.add_row("Pull requests", str(pr["total_prs"]))
    pr_table.add_row("Linked", str(pr["linked"]))
    pr_table.add_row("Unlinked PR #s", ", ".join(map(str, pr["unlinked"])) or "—")
    pr_table.add_row("By method", ", ".join(f"{k}={v}" for k, v in pr["by_method"].items()) or "—")
    console.print(pr_table)

    ident = report.identity
    id_table = Table(title="Identity merge (GitHub ↔ Linear)")
    id_table.add_column("Metric", style="cyan")
    id_table.add_column("Value", style="white", justify="right")
    id_table.add_row("People before", str(ident["people_before"]))
    id_table.add_row("People after", str(ident["people_after"]))
    id_table.add_row("Merged", str(ident["merged"]))
    id_table.add_row("By method", ", ".join(f"{k}={v}" for k, v in ident["by_method"].items()) or "—")
    console.print(id_table)


@app.command("pr-flow")
def pr_flow_cmd(
    repo: str = typer.Option(
        None, "--repo", help="owner/name (defaults to GITHUB_REPO from config)"
    ),
    as_of: str = typer.Option(
        None, "--as-of", help="ISO timestamp reference for staleness (default: now)"
    ),
) -> None:
    """PR & review-flow report: per-PR metrics and flow detectors."""

    from datetime import datetime, timezone

    from engpulse.db.base import session_scope
    from engpulse.metrics import compute_pr_flow

    target = repo or get_settings().github_repo
    if not target:
        console.print("[red]No repo given.[/red] Pass --repo owner/name or set GITHUB_REPO.")
        raise typer.Exit(code=2)
    as_of_dt = (
        datetime.fromisoformat(as_of).replace(tzinfo=timezone.utc)
        if as_of
        else datetime.now(timezone.utc)
    )

    with session_scope() as session:
        report = compute_pr_flow(session, target, as_of=as_of_dt)

    metrics_table = Table(title=f"PR-flow — {report.repo} (as of {report.as_of.date()})")
    for col in ("PR", "State", "Author", "Lines", "TTFR h", "TTM h", "Rounds", "Flags"):
        metrics_table.add_column(col)
    for pr in report.pull_requests:
        metrics_table.add_row(
            f"#{pr.number}", pr.state or "—", pr.author or "—", str(pr.size_lines),
            "—" if pr.time_to_first_review_hours is None else str(pr.time_to_first_review_hours),
            "—" if pr.time_to_merge_hours is None else str(pr.time_to_merge_hours),
            str(pr.review_rounds), ", ".join(pr.flags) or "—",
        )
    console.print(metrics_table)

    if report.flags:
        flag_table = Table(title="Flags")
        for col in ("Type", "Severity", "PR", "Evidence"):
            flag_table.add_column(col)
        for f in report.flags:
            flag_table.add_row(
                f.type, f.severity,
                f"#{f.pr_number}" if f.pr_number else "—", str(f.evidence),
            )
        console.print(flag_table)
    else:
        console.print("[green]No flags raised.[/green]")


@app.command("ci-health")
def ci_health_cmd(
    repo: str = typer.Option(
        None, "--repo", help="owner/name (defaults to GITHUB_REPO from config)"
    ),
) -> None:
    """CI/test-health report: flaky tests, failure clusters, duration trends."""

    from engpulse.db.base import session_scope
    from engpulse.metrics import compute_ci_health

    target = repo or get_settings().github_repo
    if not target:
        console.print("[red]No repo given.[/red] Pass --repo owner/name or set GITHUB_REPO.")
        raise typer.Exit(code=2)

    with session_scope() as session:
        report = compute_ci_health(session, target)

    flaky_table = Table(title=f"Flaky tests — {report.repo}")
    for col in ("Test", "Flip rate", "Fail/Total", "SHAs", "Run ids"):
        flaky_table.add_column(col)
    for f in report.flaky_tests:
        flaky_table.add_row(
            f.test, str(f.flip_rate), f"{f.fail_runs}/{f.total_runs}",
            ", ".join(f.commit_shas), ", ".join(map(str, f.evidence_run_ids)),
        )
    console.print(flaky_table if report.flaky_tests else "[green]No flaky tests.[/green]")

    if report.failure_clusters:
        cluster_table = Table(title="Failure clusters")
        for col in ("Signature", "Count", "Run ids"):
            cluster_table.add_column(col)
        for c in report.failure_clusters:
            cluster_table.add_row(c.signature, str(c.count), ", ".join(map(str, c.run_ids)))
        console.print(cluster_table)

    if report.duration_trends:
        trend_table = Table(title="Duration trends")
        for col in ("Workflow", "Runs", "Avg s", "First s", "Last s", "Regression"):
            trend_table.add_column(col)
        for t in report.duration_trends:
            trend_table.add_row(
                t.workflow, str(t.runs), str(t.avg_seconds),
                str(t.first_seconds), str(t.last_seconds),
                "yes" if t.regression else "no",
            )
        console.print(trend_table)


@app.command("delivery")
def delivery_cmd(
    team_key: str = typer.Option(
        None, "--team", help="Linear team key (defaults to LINEAR_TEAM_KEY)"
    ),
    as_of: str = typer.Option(
        None, "--as-of", help="ISO timestamp reference for staleness (default: now)"
    ),
) -> None:
    """Delivery report: cycle time, stale issues, drift, re-estimation gaps."""

    from datetime import datetime, timezone

    from engpulse.db.base import session_scope
    from engpulse.metrics import compute_delivery

    team = team_key if team_key is not None else (get_settings().linear_team_key or None)
    as_of_dt = (
        datetime.fromisoformat(as_of).replace(tzinfo=timezone.utc)
        if as_of
        else datetime.now(timezone.utc)
    )

    with session_scope() as session:
        report = compute_delivery(session, team_key=team, as_of=as_of_dt)

    issue_table = Table(title=f"Delivery — {report.scope} (as of {report.as_of.date()})")
    for col in ("Issue", "Status", "Assignee", "Cycle d", "Age d", "Due moves", "Re-est", "Flags"):
        issue_table.add_column(col)
    for i in report.issues:
        issue_table.add_row(
            i.key, i.status or "—", i.assignee or "—",
            "—" if i.cycle_time_days is None else str(i.cycle_time_days),
            "—" if i.age_days is None else str(i.age_days),
            str(i.due_moves), str(i.reestimations), ", ".join(i.flags) or "—",
        )
    console.print(issue_table)

    if report.flags:
        flag_table = Table(title="Flags")
        for col in ("Type", "Severity", "Issue", "Evidence"):
            flag_table.add_column(col)
        for f in report.flags:
            flag_table.add_row(f.type, f.severity, f.issue, str(f.evidence))
        console.print(flag_table)
    if report.wip_by_assignee:
        console.print(f"WIP by assignee: {report.wip_by_assignee}")


@app.command("score")
def score_cmd(
    repo: str = typer.Option(None, "--repo", help="owner/name (defaults to GITHUB_REPO)"),
    team: str = typer.Option(None, "--team", help="Linear team key (defaults to LINEAR_TEAM_KEY)"),
    as_of: str = typer.Option(None, "--as-of", help="ISO reference timestamp (default: now)"),
    persist: bool = typer.Option(False, "--persist", help="write a Score row (with delta)"),
) -> None:
    """Project-health score: weighted 0–100 composite + status band + breakdown."""

    from datetime import datetime, timezone

    from engpulse.db.base import session_scope
    from engpulse.scoring import compute_project_score, persist_project_score

    target = repo or get_settings().github_repo
    if not target:
        console.print("[red]No repo given.[/red] Pass --repo owner/name or set GITHUB_REPO.")
        raise typer.Exit(code=2)
    team_key = team if team is not None else (get_settings().linear_team_key or None)
    as_of_dt = (
        datetime.fromisoformat(as_of).replace(tzinfo=timezone.utc)
        if as_of else datetime.now(timezone.utc)
    )

    with session_scope() as session:
        score = compute_project_score(session, target, team_key=team_key, as_of=as_of_dt)
        row = persist_project_score(session, score) if persist else None
        delta = row.delta if row else None

    band_color = {"Healthy": "green", "Watch": "yellow",
                  "At Risk": "dark_orange", "Critical": "red"}.get(score.band, "white")
    console.print(
        f"[bold]{score.project}[/bold] health: "
        f"[{band_color}]{score.composite:.1f} — {score.band}[/{band_color}]"
        + (f"  (Δ {delta:+.1f})" if delta is not None else "")
    )

    table = Table(title="Score breakdown")
    for col in ("Sub-score", "Score", "Weight", "Penalty", "Flags", "Contributors"):
        table.add_column(col)
    for s in score.sub_scores:
        table.add_row(
            s.name, f"{s.score:.0f}", f"{s.weight:.2f}", f"{s.penalty:.0f}",
            str(s.flag_count), ", ".join(s.contributors) or "—",
        )
    console.print(table)


@app.command("digest")
def digest_cmd(
    role: str = typer.Option("EM", "--role", help="recipient role: EM | TL | PM | IC"),
    period: str = typer.Option("daily", "--period", help="daily | weekly"),
    repo: str = typer.Option(None, "--repo", help="owner/name (defaults to GITHUB_REPO)"),
    team: str = typer.Option(None, "--team", help="Linear team key (defaults to LINEAR_TEAM_KEY)"),
    as_of: str = typer.Option(None, "--as-of", help="ISO reference timestamp (default: now)"),
) -> None:
    """Role-based alert digest: routed, de-duplicated alerts for one recipient."""

    from datetime import datetime, timezone

    from engpulse.alerts import build_digest, render_digest, route_project
    from engpulse.db.base import session_scope

    target = repo or get_settings().github_repo
    if not target:
        console.print("[red]No repo given.[/red] Pass --repo owner/name or set GITHUB_REPO.")
        raise typer.Exit(code=2)
    team_key = team if team is not None else (get_settings().linear_team_key or None)
    as_of_dt = (
        datetime.fromisoformat(as_of).replace(tzinfo=timezone.utc)
        if as_of else datetime.now(timezone.utc)
    )

    with session_scope() as session:
        alerts, score = route_project(session, target, team_key=team_key, as_of=as_of_dt)
    digest = build_digest(alerts, score, role=role, period=period)
    console.print(render_digest(digest))


@app.command("knowledge")
def knowledge_cmd(
    repo: str = typer.Option(
        None, "--repo", help="owner/name (defaults to GITHUB_REPO from config)"
    ),
) -> None:
    """Knowledge-risk report: ownership map + single-point-of-failure modules."""

    from engpulse.db.base import session_scope
    from engpulse.metrics import compute_knowledge_risk

    target = repo or get_settings().github_repo
    if not target:
        console.print("[red]No repo given.[/red] Pass --repo owner/name or set GITHUB_REPO.")
        raise typer.Exit(code=2)

    with session_scope() as session:
        report = compute_knowledge_risk(session, target)

    table = Table(title=f"Ownership / bus-factor — {report.repo}")
    for col in ("Module", "Owner", "Owners", "Commits", "Share", "Flags"):
        table.add_column(col)
    for m in report.modules:
        table.add_row(
            m.module, m.owner or "—", str(m.contributor_count), str(m.commit_count),
            f"{m.ownership_share:.2f}", ", ".join(m.flags) or "—",
        )
    console.print(table)

    if report.flags:
        flag_table = Table(title="Knowledge-risk flags")
        for col in ("Type", "Severity", "Module", "Evidence"):
            flag_table.add_column(col)
        for f in report.flags:
            flag_table.add_row(f.type, f.severity, f.module, str(f.evidence))
        console.print(flag_table)
    else:
        console.print("[green]No single-point-of-failure modules.[/green]")


def _print_retrieval(query: str, results) -> None:
    table = Table(title=f"Retrieved for: {query!r}")
    for col in ("Rank", "Score", "Kind", "Ref", "Text"):
        table.add_column(col)
    for i, r in enumerate(results, 1):
        snippet = r.chunk.text.replace("\n", " ")
        table.add_row(str(i), f"{r.score:.3f}", r.chunk.kind, r.chunk.ref,
                      snippet[:70] + ("…" if len(snippet) > 70 else ""))
    console.print(table if results else "[yellow]No results.[/yellow]")


@app.command("rag-demo")
def rag_demo_cmd(
    query: str = typer.Option(..., "--query", help="natural-language question"),
    k: int = typer.Option(5, "--k", help="number of chunks to return"),
) -> None:
    """Offline hybrid-retrieval demo over the synthetic corpus (no services)."""

    from engpulse.eval.harness import ephemeral_corpus_session
    from engpulse.llm import build_embedding_client
    from engpulse.rag import HybridRetriever, InMemoryVectorStore, build_index

    corpus_repo = "acme/payments"
    session = ephemeral_corpus_session()
    embedder = build_embedding_client("fake")
    store = InMemoryVectorStore()
    n = build_index(session, corpus_repo, embedder, store)
    console.print(f"Indexed [bold]{n}[/bold] chunks (fake embeddings, in-memory).")
    retriever = HybridRetriever(store, embedder)
    _print_retrieval(query, retriever.retrieve(query, k=k))


@app.command("rag-index")
def rag_index_cmd(
    repo: str = typer.Option(None, "--repo", help="owner/name (defaults to GITHUB_REPO)"),
) -> None:
    """Build the live hybrid index into pgvector using Ollama embeddings."""

    from engpulse.db.base import session_scope
    from engpulse.llm import build_embedding_client
    from engpulse.rag import build_index
    from engpulse.rag.store import PgVectorStore

    target = repo or get_settings().github_repo
    if not target:
        console.print("[red]No repo given.[/red] Pass --repo owner/name or set GITHUB_REPO.")
        raise typer.Exit(code=2)
    embedder = build_embedding_client("ollama")
    with session_scope() as session:
        store = PgVectorStore(session, dim=embedder.dim, repo=target)
        n = build_index(session, target, embedder, store)
    console.print(f"[green]✓[/green] indexed {n} chunks for {target} into pgvector.")


@app.command("rag-search")
def rag_search_cmd(
    query: str = typer.Option(..., "--query", help="natural-language question"),
    repo: str = typer.Option(None, "--repo", help="owner/name (defaults to GITHUB_REPO)"),
    k: int = typer.Option(5, "--k", help="number of chunks to return"),
) -> None:
    """Query the live pgvector hybrid index (needs Ollama + Postgres)."""

    from engpulse.db.base import session_scope
    from engpulse.llm import build_embedding_client
    from engpulse.rag import HybridRetriever
    from engpulse.rag.store import PgVectorStore

    target = repo or get_settings().github_repo
    embedder = build_embedding_client("ollama")
    with session_scope() as session:
        store = PgVectorStore(session, dim=embedder.dim, repo=target)
        retriever = HybridRetriever(store, embedder)
        _print_retrieval(query, retriever.retrieve(query, k=k))


@app.command("synthesize")
def synthesize_cmd(
    source: str = typer.Option(
        "fake", "--source", help="chat backend: 'fake' (offline) or 'ollama'"
    ),
) -> None:
    """Grounded synthesis demo: turn the top knowledge-risk flag into a cited insight.

    Retrieval runs offline over the synthetic corpus; --source ollama uses your
    live chat model to write the (still evidence-grounded) prose.
    """

    from engpulse.eval.harness import ephemeral_corpus_session
    from engpulse.llm import build_chat_client, build_embedding_client
    from engpulse.metrics import compute_knowledge_risk
    from engpulse.rag import HybridRetriever, InMemoryVectorStore, build_index
    from engpulse.synth import synthesize_for_flag

    repo = "acme/payments"
    session = ephemeral_corpus_session()
    embedder = build_embedding_client("fake")
    store = InMemoryVectorStore()
    build_index(session, repo, embedder, store)
    retriever = HybridRetriever(store, embedder)

    report = compute_knowledge_risk(session, repo)
    if not report.flags:
        console.print("[yellow]No knowledge-risk flags to synthesize.[/yellow]")
        return
    flag = report.flags[0]
    metric_text = (
        f"{flag.module} is owned by {flag.evidence['owner']} with "
        f"{flag.evidence['commit_count']} commits; "
        f"contributors: {flag.evidence['contributors']}."
    )
    chat = build_chat_client(source)
    insight = synthesize_for_flag(
        flag.type, flag.module, flag.severity, metric_text, retriever, chat,
        query=f"{flag.module} ownership and risk",
    )

    table = Table(title=f"Insight — {insight.condition_type} on {insight.subject}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Severity", insight.severity)
    table.add_row("Abstained", "yes" if insight.abstained else "no")
    if insight.abstained:
        table.add_row("Reason", insight.abstention_reason or "")
    else:
        table.add_row("Summary", insight.summary or "")
        table.add_row("Likely cause", insight.likely_cause or "")
        table.add_row("Recommended action", insight.recommended_action or "")
        table.add_row("Confidence", f"{insight.confidence:.2f}")
        table.add_row("Citations", ", ".join(insight.citations) or "—")
    console.print(table)


@app.command("ask")
def ask_cmd(
    question: str = typer.Argument(..., help="natural-language question"),
    source: str = typer.Option("fake", "--source", help="chat backend: 'fake' or 'ollama'"),
    planner: str = typer.Option("rule", "--planner", help="'rule' or 'llm'"),
) -> None:
    """Ask EngPulse a question (offline demo over the synthetic corpus)."""

    from datetime import datetime, timezone

    from engpulse.agent import LLMPlanner, RuleBasedPlanner, build_agent
    from engpulse.eval.harness import ephemeral_corpus_session
    from engpulse.llm import build_chat_client, build_embedding_client
    from engpulse.rag import HybridRetriever, InMemoryVectorStore, build_index

    repo = "acme/payments"
    session = ephemeral_corpus_session()
    embedder = build_embedding_client("fake")
    store = InMemoryVectorStore()
    build_index(session, repo, embedder, store)
    retriever = HybridRetriever(store, embedder)
    chat = build_chat_client(source)
    planner_obj = LLMPlanner(chat) if planner == "llm" else RuleBasedPlanner()
    agent = build_agent(
        session, repo, chat, retriever, team="PAY",
        as_of=datetime(2026, 6, 14, tzinfo=timezone.utc), planner=planner_obj,
    )
    answer = agent.ask(question)

    console.print(f"[bold]Q:[/bold] {answer.question}")
    if answer.plan:
        plan_str = ", ".join(f"{t.tool}(+{t.evidence_count})" for t in answer.plan)
        console.print(f"[dim]plan:[/dim] {plan_str}")

    if answer.clarifying_question:
        console.print(f"[yellow]Clarify:[/yellow] {answer.clarifying_question}")
        return
    if answer.abstained:
        console.print("[yellow]Abstained[/yellow] — no grounded evidence for this question.")
        return

    console.print(f"\n[bold]A:[/bold] {answer.answer}")
    console.print(f"[dim]confidence {answer.confidence:.2f} · citations: "
                  f"{', '.join(answer.citations)}[/dim]")
    if answer.claims:
        claim_table = Table(title="Grounded claims")
        claim_table.add_column("Claim")
        claim_table.add_column("Cites")
        for c in answer.claims:
            claim_table.add_row(c.text, ", ".join(c.evidence_refs))
        console.print(claim_table)


@app.command("evaluate")
def evaluate_cmd(
    out: str = typer.Option(None, "--out", help="write the report as JSON to this path"),
    report_path: str = typer.Option(None, "--report", help="write a markdown eval report to this path"),
) -> None:
    """Run all detectors + entity resolution on the labeled corpus and score them.

    Self-contained: builds an ephemeral in-memory DB, so no services are needed.
    """

    import json as _json

    from engpulse.eval import run_evaluation

    report = run_evaluation()

    table = Table(title="EngPulse evaluation — labeled synthetic corpus")
    for col in ("Task", "TP", "FP", "FN", "Precision", "Recall", "F1"):
        table.add_column(col)
    for s in report.scores:
        table.add_row(
            s["detector"], str(s["tp"]), str(s["fp"]), str(s["fn"]),
            f"{s['precision']:.2f}", f"{s['recall']:.2f}", f"{s['f1']:.2f}",
        )
    console.print(table)
    console.print(f"[bold]{report.headline()}[/bold]")

    if report.agent:
        a = report.agent
        agent_table = Table(title="Ask EngPulse agent")
        agent_table.add_column("Metric", style="cyan")
        agent_table.add_column("Value", justify="right")
        agent_table.add_row("Questions", f"{a['answerable']}/{a['questions']} answerable")
        agent_table.add_row("Source recall", f"{a['source_recall']:.2f}")
        agent_table.add_row("Citation faithfulness", f"{a['citation_faithfulness']:.2f}")
        agent_table.add_row("Correct abstention", f"{a['correct_abstention']:.2f}")
        console.print(agent_table)

    if out:
        payload = {
            "as_of": report.as_of.isoformat(),
            "macro_precision": report.macro_precision,
            "macro_recall": report.macro_recall,
            "scores": report.scores,
            "agent": report.agent,
        }
        Path(out).write_text(_json.dumps(payload, indent=2))
        console.print(f"[green]✓[/green] wrote {out}")

    if report_path:
        from engpulse.eval.harness import check_consistency
        from engpulse.eval.report import render_eval_report

        deterministic = check_consistency()
        Path(report_path).write_text(render_eval_report(report, deterministic))
        console.print(
            f"[green]✓[/green] wrote {report_path}"
            + ("" if deterministic else " [yellow](non-deterministic!)[/yellow]")
        )


@app.command("corpus-check")
def corpus_check(
    path: str = typer.Option(
        None, "--path", help="corpus directory (defaults to datasets/synthetic)"
    ),
) -> None:
    """Load the labeled synthetic corpus and validate its internal consistency."""

    from engpulse.eval import load_corpus, validate_corpus

    corpus = load_corpus(path)
    problems = validate_corpus(corpus)
    labels = corpus.labels

    table = Table(title=f"Synthetic corpus — {labels.repo}")
    table.add_column("Injected problem", style="cyan")
    table.add_column("Count", justify="right")
    table.add_row("Stale PRs", str(len(labels.stale_prs)))
    table.add_row("Flaky tests", str(len(labels.flaky_tests)))
    table.add_row("Deadline drifts", str(len(labels.deadline_drifts)))
    table.add_row("Bus-factor modules", str(len(labels.bus_factors)))
    table.add_row("PR↔Issue links", str(len(labels.pr_issue_links)))
    table.add_row("Identity merges", str(len(labels.identities)))
    console.print(table)

    if problems:
        console.print(f"[red]✗ {len(problems)} consistency problem(s):[/red]")
        for problem in problems:
            console.print(f"  • {problem}")
        raise typer.Exit(code=1)
    console.print("[green]✓ corpus is internally consistent[/green]")


def _print_audit(audits: list[dict]) -> None:
    audit_table = Table(title="Sync audit (per resource)")
    audit_table.add_column("Resource", style="cyan")
    audit_table.add_column("Seen", justify="right")
    audit_table.add_column("Written", justify="right")
    audit_table.add_column("Status", style="green")
    for row in audits:
        audit_table.add_row(
            row["resource"], str(row["seen"]), str(row["written"]), row["status"]
        )
    console.print(audit_table)


if __name__ == "__main__":
    app()
