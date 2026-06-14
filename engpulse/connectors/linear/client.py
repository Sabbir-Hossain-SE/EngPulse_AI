"""Linear API clients (GraphQL).

Same pattern as the GitHub connector: a ``LinearClient`` protocol with a live
GraphQL implementation and an offline fixture implementation, so ingestion and
its tests run without a live workspace. Incremental sync is expressed as a
GraphQL ``updatedAt`` filter; pagination follows ``pageInfo.endCursor``.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from engpulse.config import get_settings
from engpulse.connectors.linear.schemas import LinearIssueDTO
from engpulse.logging import get_logger

log = get_logger(__name__)

_ISSUES_QUERY = """
query Issues($after: String, $filter: IssueFilter) {
  issues(first: 50, after: $after, filter: $filter) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      identifier
      title
      createdAt
      updatedAt
      estimate
      dueDate
      state { name type }
      assignee { id name displayName email }
      team { key name }
      project { name }
      labels { nodes { name } }
      history {
        nodes {
          createdAt
          fromState { name }
          toState { name }
          fromEstimate
          toEstimate
          fromDueDate
          toDueDate
        }
      }
    }
  }
}
"""


class LinearClient(Protocol):
    async def list_issues(
        self,
        team_key: str | None = None,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[LinearIssueDTO]: ...


class RetryableStatus(Exception):
    """Raised on a transient HTTP status so tenacity retries the request."""


class RestLinearClient:
    """Live Linear GraphQL client with pagination and incremental filtering."""

    def __init__(self, api_key: str | None = None, api_url: str | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.linear_api_key
        self._api_url = api_url or settings.linear_api_url

    def _headers(self) -> dict[str, str]:
        # Linear personal API keys go directly in Authorization (no "Bearer").
        return {"Authorization": self._api_key, "Content-Type": "application/json"}

    @staticmethod
    def _build_filter(team_key: str | None, since: datetime | None) -> dict | None:
        filt: dict = {}
        if team_key:
            filt["team"] = {"key": {"eq": team_key}}
        if since is not None:
            filt["updatedAt"] = {"gt": since.isoformat()}
        return filt or None

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, RetryableStatus)),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _post(self, client: httpx.AsyncClient, variables: dict) -> dict:
        resp = await client.post(
            self._api_url, json={"query": _ISSUES_QUERY, "variables": variables}
        )
        if resp.status_code in (429, 500, 502, 503, 504):
            log.warning("Transient Linear status %s — retrying", resp.status_code)
            raise RetryableStatus(str(resp.status_code))
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise RuntimeError(f"Linear GraphQL error: {payload['errors']}")
        return payload["data"]

    async def list_issues(
        self,
        team_key: str | None = None,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[LinearIssueDTO]:
        filt = self._build_filter(team_key, since)
        collected: list[LinearIssueDTO] = []
        after: str | None = None
        async with httpx.AsyncClient(headers=self._headers(), timeout=30) as client:
            while len(collected) < limit:
                data = await self._post(client, {"after": after, "filter": filt})
                block = data["issues"]
                collected.extend(LinearIssueDTO.from_api(n) for n in block["nodes"])
                page = block["pageInfo"]
                if not page["hasNextPage"]:
                    break
                after = page["endCursor"]
        return collected[:limit]


class FixtureLinearClient:
    """Serves recorded Linear issues from ``<fixtures_dir>/linear_issues.json``."""

    def __init__(self, fixtures_dir: str | Path) -> None:
        self._dir = Path(fixtures_dir)

    async def list_issues(
        self,
        team_key: str | None = None,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[LinearIssueDTO]:
        path = self._dir / "linear_issues.json"
        if not path.exists():
            raise FileNotFoundError(f"Fixture not found: {path}")
        nodes = json.loads(path.read_text())
        issues = [LinearIssueDTO.from_api(n) for n in nodes]
        if team_key:
            issues = [i for i in issues if i.team_key == team_key]
        return issues[:limit]


def build_linear_client(
    source: str, fixtures_dir: str | Path | None = None
) -> LinearClient:
    if source == "live":
        return RestLinearClient()
    if source == "fixture":
        base = fixtures_dir or Path(__file__).resolve().parents[3] / "tests" / "fixtures"
        return FixtureLinearClient(base)
    raise ValueError(f"Unknown source '{source}' (expected 'live' or 'fixture')")
