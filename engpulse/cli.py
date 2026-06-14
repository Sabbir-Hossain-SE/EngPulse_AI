"""EngPulse command-line entrypoint.

    engpulse check-config            # show resolved settings (secrets masked)
    engpulse init-db                 # enable pgvector + create all tables
    engpulse sync-repo ...           # run the GitHub read path

Run via the installed console script (`engpulse ...`) or `python -m engpulse.cli`.
"""

from __future__ import annotations

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
) -> None:
    """Incremental Linear ingestion: issues, status, estimates, transitions."""

    from engpulse.ingest import ingest_linear

    team = team_key if team_key is not None else (get_settings().linear_team_key or None)
    console.print(
        f"Ingesting Linear (team={team or 'all'}) via [bold]{source}[/bold] "
        f"(dry_run={dry_run})…"
    )
    report = ingest_linear(source=source, team_key=team, limit=limit, dry_run=dry_run)

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
