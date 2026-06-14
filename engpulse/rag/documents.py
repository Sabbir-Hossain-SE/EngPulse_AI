"""Turn normalized records into retrievable documents.

Indexed content (PRD §7.3): PR/issue text, commit messages, and synthesized
ownership statements — each tagged with the source ref so retrieved evidence is
always citable back to a PR number, issue key, commit sha, or file path.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from engpulse.db.models import Commit, Issue, PullRequest, Repository
from engpulse.metrics import compute_knowledge_risk


@dataclass
class Document:
    doc_id: str
    kind: str          # pr | issue | commit | ownership
    ref: str           # PR#1 | ENG-12 | sha | auth/tokens.py
    text: str
    metadata: dict = field(default_factory=dict)


def build_documents(session: Session, repo_full_name: str) -> list[Document]:
    repo = session.scalars(
        select(Repository).where(Repository.full_name == repo_full_name)
    ).first()
    if repo is None:
        return []

    docs: list[Document] = []

    prs = session.scalars(
        select(PullRequest).where(PullRequest.repo_id == repo.id)
        .options(selectinload(PullRequest.author))
    ).all()
    for pr in prs:
        text = "\n".join(p for p in [pr.title, pr.body] if p)
        docs.append(Document(
            doc_id=f"pr-{pr.number}", kind="pr", ref=f"PR#{pr.number}", text=text,
            metadata={"url": pr.html_url,
                      "author": pr.author.github_login if pr.author else None},
        ))

    # Issues are tracker-scoped (not repo-scoped) in the schema; index them all.
    for issue in session.scalars(select(Issue)).all():
        text = " ".join(p for p in [issue.key, issue.title] if p)
        docs.append(Document(
            doc_id=f"issue-{issue.key}", kind="issue", ref=issue.key, text=text,
            metadata={"status": issue.status, "team": issue.team_key},
        ))

    for c in session.scalars(select(Commit).where(Commit.repo_id == repo.id)).all():
        files = ", ".join(c.files_changed or [])
        text = (c.message or "")
        if files:
            text += f"\n(files: {files})"
        docs.append(Document(
            doc_id=f"commit-{c.sha}", kind="commit", ref=c.sha[:7], text=text,
            metadata={"files": c.files_changed or []},
        ))

    # Synthesized ownership documents (so "who owns X" retrieves real evidence).
    knowledge = compute_knowledge_risk(session, repo_full_name)
    for m in knowledge.modules:
        contributors = ", ".join(m.contributors)
        text = (
            f"Module {m.module} is primarily owned by {m.owner}. "
            f"Contributors: {contributors}. {m.commit_count} commits. "
            f"{'Single point of failure.' if m.flags else ''}"
        )
        docs.append(Document(
            doc_id=f"ownership-{m.module}", kind="ownership", ref=m.module, text=text,
            metadata={"owner": m.owner, "contributors": m.contributors,
                      "spof": bool(m.flags)},
        ))

    return docs
