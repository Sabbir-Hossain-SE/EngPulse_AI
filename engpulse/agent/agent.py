"""The Ask EngPulse agent: plan → call tools → ground → cited answer / abstain.

Composes the whole stack: a planner picks tools, the tools gather citable
evidence across hops, and the answer is produced under the same grounding
contract as insights (schema-enforced, claims must cite supplied evidence, and
the agent abstains rather than guess).
"""

from __future__ import annotations

from datetime import datetime

from engpulse.agent.planner import RuleBasedPlanner, needs_clarification
from engpulse.agent.schema import AgentAnswer, GeneratedAnswer, ToolCall
from engpulse.agent.tools import AgentContext, build_registry
from engpulse.llm.chat import ChatClient
from engpulse.logging import get_logger
from engpulse.synth.grounded import check_grounding, generate_structured, render_evidence
from engpulse.synth.schema import EvidenceItem

log = get_logger(__name__)

_SYSTEM = (
    "You are EngPulse, answering questions about an engineering organization. "
    "Use ONLY the evidence provided. For every claim, cite the [REF:<id>] id(s) "
    "it rests on in evidence_refs. Do NOT invent facts or numbers. If the evidence "
    "does not answer the question, return an empty claims list. Respond with ONLY a "
    'JSON object: {"answer": str, "claims": [{"text": str, "evidence_refs": [str]}], '
    '"confidence": number 0..1}.'
)

_CLARIFY = (
    "Could you specify the project, module, or person you're asking about?"
)


def _answer_messages(question: str, evidence: list[EvidenceItem]) -> list[dict]:
    user = (
        f"Question: {question}\n\nEvidence:\n{render_evidence(evidence)}\n\n"
        "Answer the question, grounded only in the evidence."
    )
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


class AskAgent:
    def __init__(
        self,
        ctx: AgentContext,
        chat: ChatClient,
        planner=None,
    ) -> None:
        self._ctx = ctx
        self._chat = chat
        self._planner = planner or RuleBasedPlanner()
        self._tools = build_registry()

    def ask(self, question: str) -> AgentAnswer:
        if needs_clarification(question):
            return AgentAnswer(question=question, clarifying_question=_CLARIFY)

        plan = self._planner.plan(question)

        evidence: list[EvidenceItem] = []
        seen: set[str] = set()
        tool_calls: list[ToolCall] = []
        for call in plan:
            tool = self._tools.get(call.tool)
            if tool is None:
                continue
            fresh = []
            for item in tool.run(self._ctx, call.args):
                if item.ref not in seen:
                    seen.add(item.ref)
                    fresh.append(item)
            evidence.extend(fresh)
            tool_calls.append(ToolCall(tool=call.tool, args=call.args,
                                       evidence_count=len(fresh)))

        if not evidence:
            return AgentAnswer(question=question, plan=tool_calls, abstained=True)

        gen: GeneratedAnswer = generate_structured(
            self._chat, _answer_messages(question, evidence), schema=GeneratedAnswer
        )
        grounded, dropped = check_grounding(gen, {e.ref for e in evidence})
        if dropped:
            log.warning("Agent dropped %d ungrounded claim(s)", len(dropped))
        if not grounded:
            return AgentAnswer(question=question, plan=tool_calls,
                               evidence=evidence, abstained=True)

        grounded_ratio = len(grounded) / len(gen.claims) if gen.claims else 0.0
        citations = sorted({r for c in grounded for r in c.evidence_refs})
        return AgentAnswer(
            question=question, plan=tool_calls, answer=gen.answer, claims=grounded,
            citations=citations, confidence=round(min(gen.confidence, grounded_ratio), 4),
            evidence=evidence, abstained=False,
        )


def build_agent(
    session,
    repo: str,
    chat: ChatClient,
    retriever,
    team: str | None = None,
    as_of: datetime | None = None,
    planner=None,
) -> AskAgent:
    ctx = AgentContext(session=session, retriever=retriever, repo=repo,
                       team=team, as_of=as_of)
    return AskAgent(ctx, chat, planner=planner)
