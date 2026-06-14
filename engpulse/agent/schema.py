"""Agent I/O schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from engpulse.synth.schema import Claim, EvidenceItem


class PlannedCall(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)


class GeneratedPlan(BaseModel):
    """An LLM planner's structured output."""

    calls: list[PlannedCall] = Field(default_factory=list)


class GeneratedAnswer(BaseModel):
    """The model's grounded answer — schema-enforced like insights."""

    answer: str
    claims: list[Claim] = Field(default_factory=list)
    confidence: float = 0.5


class ToolCall(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)
    evidence_count: int = 0


class AgentAnswer(BaseModel):
    question: str
    plan: list[ToolCall] = Field(default_factory=list)
    answer: str | None = None
    claims: list[Claim] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    abstained: bool = False
    clarifying_question: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
