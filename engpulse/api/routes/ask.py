"""The Ask EngPulse Q&A endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from engpulse.agent.schema import AgentAnswer
from engpulse.api.deps import get_session, parse_as_of
from engpulse.api.services import get_agent

router = APIRouter()


class AskRequest(BaseModel):
    question: str
    repo: str = "acme/payments"
    team: str | None = "PAY"
    as_of: str | None = None


@router.post("/ask", response_model=AgentAnswer)
def ask(req: AskRequest, session: Session = Depends(get_session)) -> AgentAnswer:
    agent = get_agent(session, req.repo, req.team, parse_as_of(req.as_of))
    return agent.ask(req.question)
