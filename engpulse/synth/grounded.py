"""Grounded synthesis pipeline.

Steps, in order:
  1. Assemble evidence (deterministic metric facts + retrieved context).
  2. Abstain immediately if evidence is too thin.
  3. Prompt the model under a strict grounding contract and enforce the JSON
     schema, retrying/repairing on violation (open models need this).
  4. Hallucination check: drop any claim whose cited refs are not in the
     evidence; abstain if nothing grounded survives.

Severity and numbers never come from the model — only prose and which evidence
each claim rests on.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from engpulse.llm.chat import ChatClient
from engpulse.logging import get_logger
from engpulse.synth.schema import EvidenceItem, GeneratedInsight, Insight

log = get_logger(__name__)

_SYSTEM = (
    "You are an engineering-delivery analyst. Use ONLY the evidence provided. "
    "For every claim, cite the [REF:<id>] id(s) it rests on in evidence_refs. "
    "Do NOT invent numbers or facts that are not in the evidence. If the evidence "
    "is insufficient, return an empty claims list. Respond with ONLY a JSON object: "
    '{"summary": str, "likely_cause": str, "recommended_action": str, '
    '"claims": [{"text": str, "evidence_refs": [str]}], "confidence": number 0..1}.'
)


class SynthesisError(RuntimeError):
    pass


def render_evidence(items: list[EvidenceItem]) -> str:
    return "\n".join(f"[REF:{e.ref}] ({e.kind}) {e.text}" for e in items)


def build_messages(condition_type: str, subject: str, items: list[EvidenceItem]) -> list[dict]:
    user = (
        f"Condition: {condition_type} on {subject}.\n\n"
        f"Evidence:\n{render_evidence(items)}\n\n"
        "Write a grounded insight as specified."
    )
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


def _extract_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = raw.rstrip("`").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(raw[start : end + 1])


def generate_structured(
    chat: ChatClient, messages: list[dict], max_retries: int = 2
) -> GeneratedInsight:
    """Call the model and enforce the schema, repairing on failure."""

    convo = list(messages)
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        raw = chat.complete(convo)
        try:
            return GeneratedInsight.model_validate(_extract_json(raw))
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            log.warning("Schema violation (attempt %d): %s", attempt + 1, exc)
            convo = convo + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content":
                    f"That was invalid ({exc}). Return ONLY valid JSON matching the schema."},
            ]
    raise SynthesisError(f"model did not return valid JSON: {last_error}")


def check_grounding(gen: GeneratedInsight, valid_refs: set[str]):
    """Split claims into grounded (every cited ref exists) and dropped."""

    grounded, dropped = [], []
    for claim in gen.claims:
        if claim.evidence_refs and all(r in valid_refs for r in claim.evidence_refs):
            grounded.append(claim)
        else:
            dropped.append(claim)
    return grounded, dropped


def _abstain(condition_type: str, subject: str, severity: str, reason: str) -> Insight:
    return Insight(
        condition_type=condition_type, subject=subject, severity=severity,
        abstained=True, abstention_reason=reason, confidence=0.0,
    )


def synthesize_insight(
    condition_type: str,
    subject: str,
    severity: str,
    evidence: list[EvidenceItem],
    chat: ChatClient,
    min_evidence: int = 1,
) -> Insight:
    valid_refs = {e.ref for e in evidence}
    if len(evidence) < min_evidence:
        return _abstain(condition_type, subject, severity, "insufficient evidence")

    gen = generate_structured(chat, build_messages(condition_type, subject, evidence))
    grounded, dropped = check_grounding(gen, valid_refs)
    if not grounded:
        return _abstain(condition_type, subject, severity, "no grounded claims")

    grounded_ratio = len(grounded) / len(gen.claims) if gen.claims else 0.0
    confidence = round(min(gen.confidence, grounded_ratio), 4)
    citations = sorted({r for c in grounded for r in c.evidence_refs})
    if dropped:
        log.warning("Dropped %d ungrounded claim(s) for %s", len(dropped), subject)

    return Insight(
        condition_type=condition_type, subject=subject, severity=severity,
        summary=gen.summary, likely_cause=gen.likely_cause,
        recommended_action=gen.recommended_action,
        claims=grounded, confidence=confidence, citations=citations,
    )


def synthesize_for_flag(
    condition_type: str,
    subject: str,
    severity: str,
    metric_text: str,
    retriever,
    chat: ChatClient,
    query: str,
    k: int = 4,
) -> Insight:
    """Assemble metric + retrieved evidence for a detector flag, then synthesize."""

    evidence = [EvidenceItem(ref=f"metric:{subject}", kind="metric", text=metric_text)]
    for r in retriever.retrieve(query, k=k):
        evidence.append(EvidenceItem(ref=r.chunk.ref, kind=r.chunk.kind, text=r.chunk.text))
    return synthesize_insight(condition_type, subject, severity, evidence, chat)
