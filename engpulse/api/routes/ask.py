"""The Ask EngPulse Q&A endpoint."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
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


@router.post("/ask/stream")
def ask_stream(req: AskRequest, session: Session = Depends(get_session)) -> StreamingResponse:
    """Stream the agent's reasoning stages as Server-Sent Events."""

    agent = get_agent(session, req.repo, req.team, parse_as_of(req.as_of))

    def event_source():
        for event in agent.ask_events(req.question):
            yield f"event: {event['stage']}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
