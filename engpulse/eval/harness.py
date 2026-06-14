"""Consolidated evaluation harness.

Runs the full pipeline — ingest → resolve → detect — against the labeled
synthetic corpus and scores every detector and the entity-resolution output
against ground truth. Uses an ephemeral in-memory SQLite database (the schema is
portable), so it runs with no external services.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from engpulse.db import models  # noqa: F401  (register models on Base.metadata)
from engpulse.db.base import Base
from engpulse.db.models import Person, PullRequest
from engpulse.eval.corpus import Corpus, load_corpus
from engpulse.eval.score import PRFScore, prf
from engpulse.ingest.github_ingest import _fetch as gh_fetch
from engpulse.ingest.github_ingest import _persist as gh_persist
from engpulse.ingest.linear_ingest import _persist as linear_persist
from engpulse.metrics import (
    compute_ci_health,
    compute_delivery,
    compute_knowledge_risk,
    compute_pr_flow,
)
from engpulse.resolve.identity import merge_people
from engpulse.resolve.pr_issue import link_prs_to_issues


__all__ = [
    "EvaluationReport", "run_evaluation", "ephemeral_corpus_session", "evaluate_agent",
]


class EvaluationReport(BaseModel):
    as_of: datetime
    scores: list[dict] = Field(default_factory=list)
    agent: dict = Field(default_factory=dict)

    @property
    def macro_precision(self) -> float:
        return round(sum(s["precision"] for s in self.scores) / len(self.scores), 4) \
            if self.scores else 1.0

    @property
    def macro_recall(self) -> float:
        return round(sum(s["recall"] for s in self.scores) / len(self.scores), 4) \
            if self.scores else 1.0

    def headline(self) -> str:
        return (
            f"{len(self.scores)} labeled tasks · macro precision "
            f"{self.macro_precision:.2f} / recall {self.macro_recall:.2f}"
        )


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 1.0


def evaluate_agent(session: Session, corpus: Corpus) -> dict:
    """Score the Ask EngPulse agent: source recall, citation faithfulness, and
    correct-abstention rate over the labeled question set (offline, fake chat)."""

    from datetime import timezone

    from engpulse.agent import build_agent
    from engpulse.llm import build_chat_client, build_embedding_client
    from engpulse.rag import HybridRetriever, InMemoryVectorStore, build_index

    labels = corpus.labels
    repo = corpus.repo["full_name"]
    as_of = datetime.combine(labels.as_of, datetime.min.time(), tzinfo=timezone.utc)

    embedder = build_embedding_client("fake")
    store = InMemoryVectorStore()
    build_index(session, repo, embedder, store)
    retriever = HybridRetriever(store, embedder)
    agent = build_agent(session, repo, build_chat_client("fake"), retriever,
                        team=labels.team_key, as_of=as_of)

    recalls: list[float] = []
    faithfulness: list[float] = []
    abstained_correct = 0
    unanswerable = [q for q in labels.agent_questions if not q.answerable]

    for q in labels.agent_questions:
        answer = agent.ask(q.question)
        evidence_refs = {e.ref for e in answer.evidence}
        if q.answerable:
            expected = set(q.expected_sources)
            recalls.append(
                len(expected & evidence_refs) / len(expected) if expected else 1.0
            )
            if not answer.abstained and answer.citations:
                faithfulness.append(
                    1.0 if all(c in evidence_refs for c in answer.citations) else 0.0
                )
        elif answer.abstained or answer.clarifying_question:
            abstained_correct += 1

    return {
        "questions": len(labels.agent_questions),
        "answerable": len(labels.agent_questions) - len(unanswerable),
        "source_recall": _mean(recalls),
        "citation_faithfulness": _mean(faithfulness),
        "correct_abstention": round(abstained_correct / len(unanswerable), 4)
        if unanswerable else 1.0,
    }


def _ephemeral_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)()


def ephemeral_corpus_session(corpus: Corpus | None = None) -> Session:
    """An in-memory DB with the corpus ingested and entity-resolved.

    Shared by the evaluation harness and the offline RAG demo so both exercise
    the real pipeline with no external services.
    """

    corpus = corpus or load_corpus()
    owner, name = corpus.repo["full_name"].split("/", 1)
    session = _ephemeral_session()
    bundle = asyncio.run(gh_fetch(corpus.github_client(), owner, name, 200, 500, 500))
    gh_persist(session, corpus.repo["full_name"], bundle)
    issues = asyncio.run(corpus.linear_client().list_issues(team_key=corpus.labels.team_key))
    linear_persist(session, f"linear:{corpus.labels.team_key}", issues)
    session.flush()
    link_prs_to_issues(session)
    merge_people(session)
    session.flush()
    return session


def run_evaluation(
    corpus: Corpus | None = None, as_of: datetime | None = None
) -> EvaluationReport:
    corpus = corpus or load_corpus()
    labels = corpus.labels
    as_of = as_of or datetime.combine(
        labels.as_of, datetime.min.time(), tzinfo=timezone.utc
    )
    repo_name = corpus.repo["full_name"]

    session = ephemeral_corpus_session(corpus)
    try:
        # --- detect -------------------------------------------------------
        pr_report = compute_pr_flow(session, repo_name, as_of=as_of)
        ci_report = compute_ci_health(session, repo_name)
        delivery_report = compute_delivery(session, team_key=labels.team_key, as_of=as_of)
        knowledge_report = compute_knowledge_risk(session, repo_name)

        # --- score against ground truth -----------------------------------
        scores: list[PRFScore] = []

        scores.append(prf(
            "stale_pr",
            pr_report.flagged_pr_numbers("stale") | pr_report.flagged_pr_numbers("abandoned"),
            {s.pr_number for s in labels.stale_prs},
        ))
        scores.append(prf(
            "flaky_test",
            ci_report.flaky_keys(),
            {(f.test, f.commit_sha) for f in labels.flaky_tests},
        ))
        scores.append(prf(
            "deadline_drift",
            delivery_report.flagged_issues("deadline_drift"),
            {d.issue for d in labels.deadline_drifts},
        ))
        scores.append(prf(
            "bus_factor",
            knowledge_report.flagged_modules(),
            {b.module for b in labels.bus_factors},
        ))

        predicted_links = {
            (pr.number, pr.linked_issue.key)
            for pr in session.scalars(select(PullRequest)).all()
            if pr.linked_issue_id is not None
        }
        scores.append(prf(
            "pr_issue_link",
            predicted_links,
            {(link.pr_number, link.issue) for link in labels.pr_issue_links},
        ))

        predicted_identities = {
            (p.github_login, p.tracker_id)
            for p in session.scalars(select(Person)).all()
            if p.github_login and p.tracker_id
        }
        scores.append(prf(
            "identity_merge",
            predicted_identities,
            {(i.github_login, i.tracker_id) for i in labels.identities},
        ))

        agent_metrics = evaluate_agent(session, corpus)
        return EvaluationReport(
            as_of=as_of, scores=[s.as_dict() for s in scores], agent=agent_metrics
        )
    finally:
        session.close()
