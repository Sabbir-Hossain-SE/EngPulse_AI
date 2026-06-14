"""Agent tools: each consults one source and returns citable evidence.

Tools are the agent's only window onto the data — deterministic metrics, the
ownership graph, and the hybrid retriever — so every answer is grounded in (and
cites) real records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from engpulse.llm.embeddings import content_tokens, tokenize
from engpulse.metrics import (
    compute_ci_health,
    compute_delivery,
    compute_knowledge_risk,
    compute_pr_flow,
)
from engpulse.synth.schema import EvidenceItem


@dataclass
class AgentContext:
    session: Session
    retriever: object               # HybridRetriever
    repo: str
    team: str | None = None
    as_of: datetime | None = None


class Tool(Protocol):
    name: str

    def run(self, ctx: AgentContext, args: dict) -> list[EvidenceItem]: ...


class RetrievalTool:
    name = "retrieval"

    def run(self, ctx: AgentContext, args: dict) -> list[EvidenceItem]:
        query = args.get("query", "")
        q_tokens = content_tokens(query)
        items: list[EvidenceItem] = []
        for r in ctx.retriever.retrieve(query, k=args.get("k", 5)):
            # Relevance gate: keep only chunks sharing a *content* token with the
            # query, so off-topic questions surface no evidence (→ abstention).
            if q_tokens & content_tokens(r.chunk.text):
                items.append(EvidenceItem(ref=r.chunk.ref, kind=r.chunk.kind,
                                          text=r.chunk.text))
        return items


class OwnershipTool:
    name = "ownership"

    def run(self, ctx: AgentContext, args: dict) -> list[EvidenceItem]:
        subject = (args.get("subject") or "").lower()
        subject_tokens = set(tokenize(subject))
        report = compute_knowledge_risk(ctx.session, ctx.repo)
        items: list[EvidenceItem] = []
        for m in report.modules:
            path_tokens = set(tokenize(m.module))
            if subject_tokens and not (subject_tokens & path_tokens):
                continue
            spof = " Single point of failure." if m.flags else ""
            items.append(EvidenceItem(
                ref=f"metric:{m.module}", kind="ownership",
                text=(f"{m.module} is owned by {m.owner} ({m.commit_count} commits; "
                      f"contributors: {', '.join(m.contributors)}).{spof}"),
            ))
        return items


class DeliveryTool:
    name = "delivery"

    def run(self, ctx: AgentContext, args: dict) -> list[EvidenceItem]:
        report = compute_delivery(ctx.session, team_key=ctx.team, as_of=ctx.as_of)
        items: list[EvidenceItem] = []
        for f in report.flags:
            items.append(EvidenceItem(
                ref=f"metric:{f.issue}:{f.type}", kind="delivery",
                text=f"{f.issue}: {f.type} ({f.severity}). {f.evidence}",
            ))
        return items


class CIHealthTool:
    name = "ci_health"

    def run(self, ctx: AgentContext, args: dict) -> list[EvidenceItem]:
        report = compute_ci_health(ctx.session, ctx.repo)
        items: list[EvidenceItem] = []
        for f in report.flaky_tests:
            items.append(EvidenceItem(
                ref=f"metric:flaky:{f.test}", kind="ci",
                text=(f"{f.test} is flaky (flip rate {f.flip_rate}) on "
                      f"{', '.join(f.commit_shas)}."),
            ))
        return items


class PRFlowTool:
    name = "pr_flow"

    def run(self, ctx: AgentContext, args: dict) -> list[EvidenceItem]:
        report = compute_pr_flow(ctx.session, ctx.repo, as_of=ctx.as_of)
        items: list[EvidenceItem] = []
        for f in report.flags:
            ref = f"metric:PR{f.pr_number}:{f.type}" if f.pr_number else f"metric:{f.type}"
            items.append(EvidenceItem(
                ref=ref, kind="pr_flow",
                text=f"{f.type} ({f.severity}). {f.evidence}",
            ))
        return items


def build_registry() -> dict[str, Tool]:
    tools = [RetrievalTool(), OwnershipTool(), DeliveryTool(), CIHealthTool(), PRFlowTool()]
    return {t.name: t for t in tools}
