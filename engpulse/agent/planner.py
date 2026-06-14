"""Planners decide which tools to consult for a question.

* ``RuleBasedPlanner`` — deterministic intent routing (offline default).
* ``LLMPlanner`` — asks the model for a JSON plan (schema-enforced), falling
  back to the rule-based plan on any failure.

Both always append a retrieval hop, so semantic context is gathered alongside
the deterministic tools (multi-hop).
"""

from __future__ import annotations

import re

from engpulse.agent.schema import GeneratedPlan, PlannedCall
from engpulse.llm.chat import ChatClient
from engpulse.llm.embeddings import tokenize

_STOPWORDS = {
    "who", "what", "when", "where", "why", "how", "is", "are", "the", "a", "an",
    "of", "and", "to", "in", "on", "about", "at", "for", "do", "does", "did",
    "it", "this", "that", "they", "them", "our", "we", "i", "you", "with", "by",
    "owns", "own", "owned",  # intent words, not subjects
}

_INTENT = {
    "ownership": ("own", "owns", "ownership", "bus factor", "bus-factor",
                  "maintain", "knows", "expert", "spof", "single point"),
    "delivery": ("risk", "deadline", "drift", "late", "slip", "behind",
                 "stale", "estimat", "due date", "on track"),
    "ci_health": ("flaky", "flak", " ci ", "test", "build", "pipeline", "failing"),
    "pr_flow": ("review", "pull request", " pr ", "merge", "bottleneck", "unreviewed"),
}


def extract_subject(question: str) -> str:
    tokens = [t for t in tokenize(question) if t not in _STOPWORDS and len(t) > 1]
    return " ".join(tokens)


class RuleBasedPlanner:
    def plan(self, question: str) -> list[PlannedCall]:
        q = f" {question.lower()} "
        calls: list[PlannedCall] = []
        if any(kw in q for kw in _INTENT["ownership"]):
            calls.append(PlannedCall(tool="ownership", args={"subject": extract_subject(question)}))
        if any(kw in q for kw in _INTENT["delivery"]):
            calls.append(PlannedCall(tool="delivery", args={}))
        if any(kw in q for kw in _INTENT["ci_health"]):
            calls.append(PlannedCall(tool="ci_health", args={}))
        if any(kw in q for kw in _INTENT["pr_flow"]):
            calls.append(PlannedCall(tool="pr_flow", args={}))
        calls.append(PlannedCall(tool="retrieval", args={"query": question}))
        return calls


class LLMPlanner:
    """Schema-enforced LLM planning, with a rule-based safety net."""

    _SYSTEM = (
        "Plan which tools to call to answer the question. Tools: "
        "ownership(subject), delivery(), ci_health(), pr_flow(), retrieval(query). "
        'Respond ONLY JSON: {"calls": [{"tool": str, "args": {}}]}.'
    )

    def __init__(self, chat: ChatClient) -> None:
        self._chat = chat
        self._fallback = RuleBasedPlanner()

    def plan(self, question: str) -> list[PlannedCall]:
        from engpulse.synth.grounded import generate_structured

        try:
            messages = [
                {"role": "system", "content": self._SYSTEM},
                {"role": "user", "content": question},
            ]
            plan = generate_structured(self._chat, messages, schema=GeneratedPlan)
            calls = [c for c in plan.calls if c.tool]
            if not any(c.tool == "retrieval" for c in calls):
                calls.append(PlannedCall(tool="retrieval", args={"query": question}))
            return calls or self._fallback.plan(question)
        except Exception:  # noqa: BLE001 - never let planning crash the answer
            return self._fallback.plan(question)


_CONTENT_RE = re.compile(r"[A-Za-z0-9_]+")


def needs_clarification(question: str) -> bool:
    """True when the question has no concrete subject to act on."""

    content = [t for t in tokenize(question) if t not in _STOPWORDS and len(t) > 1]
    return len(content) == 0
