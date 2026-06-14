"""Typed insight schemas.

``GeneratedInsight`` is what the LLM must return (enforced + repaired).
``Insight`` is the final, grounded record we keep — note that severity and the
underlying numbers come from the deterministic layer, never the model.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Claim(BaseModel):
    text: str
    evidence_refs: list[str] = Field(default_factory=list)


class GeneratedInsight(BaseModel):
    """The LLM's structured output — schema-enforced on every call."""

    summary: str
    likely_cause: str
    recommended_action: str
    claims: list[Claim] = Field(default_factory=list)
    confidence: float = 0.5


class EvidenceItem(BaseModel):
    ref: str            # citable id: metric:auth/tokens.py, PR#1, ENG-12, sha…
    kind: str           # metric | pr | issue | commit | ownership
    text: str


class Insight(BaseModel):
    condition_type: str
    subject: str
    severity: str       # from the deterministic flag, NOT the model
    summary: str | None = None
    likely_cause: str | None = None
    recommended_action: str | None = None
    claims: list[Claim] = Field(default_factory=list)
    confidence: float = 0.0
    citations: list[str] = Field(default_factory=list)
    abstained: bool = False
    abstention_reason: str | None = None
