"""Typed transfer objects for the Linear connector.

Parses the GraphQL ``Issue`` node (with its assignee, team, project, labels, and
history) into a flat, typed shape. Normalization reads only from these DTOs.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LinearTransitionDTO(BaseModel):
    """One Linear issue history entry (a state/estimate/due-date change)."""

    at: datetime | None = None
    from_state: str | None = None
    to_state: str | None = None
    from_estimate: float | None = None
    to_estimate: float | None = None
    from_due_date: datetime | None = None
    to_due_date: datetime | None = None

    @classmethod
    def from_api(cls, node: dict) -> "LinearTransitionDTO":
        from_state = (node.get("fromState") or {}).get("name")
        to_state = (node.get("toState") or {}).get("name")
        return cls(
            at=node.get("createdAt"),
            from_state=from_state,
            to_state=to_state,
            from_estimate=node.get("fromEstimate"),
            to_estimate=node.get("toEstimate"),
            from_due_date=node.get("fromDueDate"),
            to_due_date=node.get("toDueDate"),
        )

    def serializable(self) -> dict:
        """JSON-safe dict (datetimes → ISO strings) for storage in JSON columns."""

        def iso(value: datetime | None) -> str | None:
            return value.isoformat() if value is not None else None

        return {
            "at": iso(self.at),
            "from_state": self.from_state,
            "to_state": self.to_state,
            "from_estimate": self.from_estimate,
            "to_estimate": self.to_estimate,
            "from_due_date": iso(self.from_due_date),
            "to_due_date": iso(self.to_due_date),
        }


class LinearIssueDTO(BaseModel):
    id: str
    identifier: str  # e.g. "ENG-123" — the human key used for PR↔issue linking
    title: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    estimate: float | None = None
    due_date: datetime | None = None
    status: str | None = None
    status_type: str | None = None
    assignee_id: str | None = None
    assignee_name: str | None = None
    assignee_email: str | None = None
    team_key: str | None = None
    project_name: str | None = None
    labels: list[str] = Field(default_factory=list)
    transitions: list[LinearTransitionDTO] = Field(default_factory=list)

    @classmethod
    def from_api(cls, node: dict) -> "LinearIssueDTO":
        state = node.get("state") or {}
        assignee = node.get("assignee") or {}
        team = node.get("team") or {}
        project = node.get("project") or {}
        labels = [n.get("name") for n in (node.get("labels") or {}).get("nodes", [])]
        history = (node.get("history") or {}).get("nodes", [])
        return cls(
            id=node["id"],
            identifier=node["identifier"],
            title=node.get("title"),
            created_at=node.get("createdAt"),
            updated_at=node.get("updatedAt"),
            estimate=node.get("estimate"),
            due_date=node.get("dueDate"),
            status=state.get("name"),
            status_type=state.get("type"),
            assignee_id=assignee.get("id"),
            assignee_name=assignee.get("name") or assignee.get("displayName"),
            assignee_email=assignee.get("email"),
            team_key=team.get("key"),
            project_name=project.get("name"),
            labels=[label for label in labels if label],
            transitions=[LinearTransitionDTO.from_api(n) for n in history],
        )
