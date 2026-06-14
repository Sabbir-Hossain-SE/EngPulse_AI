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


if __name__ == "__main__":
    app()
