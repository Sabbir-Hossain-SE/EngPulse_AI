"""GitHub API clients.

Two interchangeable implementations behind one ``GitHubClient`` protocol:

* ``RestGitHubClient`` — async ``httpx`` client with pagination, rate-limit
  awareness, and retry-with-backoff. This is the live read path.
* ``FixtureGitHubClient`` — serves recorded JSON from disk so the entire
  end-to-end read path (and its tests) runs offline, with no live API calls.

The reader/normalizer depends only on the protocol, so swapping live ↔ fixture
is a one-line change and requires no other code to know the difference.
"""

from __future__ import annotations

import asyncio
import json
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
from engpulse.connectors.github.schemas import (
    CIRunDTO,
    CommitDTO,
    PullRequestDTO,
    RepositoryDTO,
    ReviewDTO,
)
from engpulse.logging import get_logger

log = get_logger(__name__)


class GitHubClient(Protocol):
    """The contract the reader depends on (live and fixture both satisfy it)."""

    async def get_repository(self, owner: str, repo: str) -> RepositoryDTO: ...

    async def list_pull_requests(
        self, owner: str, repo: str, limit: int = 20
    ) -> list[PullRequestDTO]: ...

    async def list_reviews(
        self, owner: str, repo: str, pr_number: int
    ) -> list[ReviewDTO]: ...

    async def list_commits(
        self, owner: str, repo: str, limit: int = 50
    ) -> list[CommitDTO]: ...

    async def list_workflow_runs(
        self, owner: str, repo: str, limit: int = 50
    ) -> list[CIRunDTO]: ...


class RetryableStatus(Exception):
    """Raised on a transient HTTP status so tenacity retries the request."""


class RestGitHubClient:
    """Live GitHub REST client with pagination, rate-limit, and backoff."""

    def __init__(
        self,
        token: str | None = None,
        api_url: str | None = None,
        per_page: int = 50,
    ) -> None:
        settings = get_settings()
        self._token = token if token is not None else settings.github_token
        self._api_url = (api_url or settings.github_api_url).rstrip("/")
        self._per_page = per_page

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "engpulse-scaffold",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, RetryableStatus)),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _get(self, client: httpx.AsyncClient, url: str, **params) -> httpx.Response:
        resp = await client.get(url, params=params or None)
        # Respect GitHub's primary rate limit: if exhausted, surface clearly.
        if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
            reset = resp.headers.get("X-RateLimit-Reset", "?")
            raise RuntimeError(
                f"GitHub rate limit exhausted (resets at epoch {reset}). "
                "Add a GITHUB_TOKEN or wait for the reset window."
            )
        if resp.status_code in (429, 500, 502, 503, 504):
            log.warning("Transient GitHub status %s on %s — retrying", resp.status_code, url)
            raise RetryableStatus(str(resp.status_code))
        resp.raise_for_status()
        return resp

    async def get_repository(self, owner: str, repo: str) -> RepositoryDTO:
        url = f"{self._api_url}/repos/{owner}/{repo}"
        async with httpx.AsyncClient(headers=self._headers(), timeout=30) as client:
            resp = await self._get(client, url)
            return RepositoryDTO.from_api(resp.json())

    async def list_pull_requests(
        self, owner: str, repo: str, limit: int = 20
    ) -> list[PullRequestDTO]:
        list_url = f"{self._api_url}/repos/{owner}/{repo}/pulls"
        collected: list[dict] = []
        async with httpx.AsyncClient(headers=self._headers(), timeout=30) as client:
            page = 1
            while len(collected) < limit:
                resp = await self._get(
                    client,
                    list_url,
                    state="all",
                    per_page=min(self._per_page, limit - len(collected)),
                    page=page,
                    sort="created",
                    direction="desc",
                )
                batch = resp.json()
                if not batch:
                    break
                collected.extend(batch)
                if "next" not in resp.links:
                    break
                page += 1

            collected = collected[:limit]

            # The list endpoint omits size fields; fetch each PR's detail to get
            # additions/deletions/changed_files. Bounded by `limit`, so cheap.
            async def detail(pr: dict) -> PullRequestDTO:
                durl = f"{list_url}/{pr['number']}"
                dresp = await self._get(client, durl)
                return PullRequestDTO.from_api(dresp.json())

            return list(await asyncio.gather(*(detail(pr) for pr in collected)))

    async def list_reviews(
        self, owner: str, repo: str, pr_number: int
    ) -> list[ReviewDTO]:
        url = f"{self._api_url}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        async with httpx.AsyncClient(headers=self._headers(), timeout=30) as client:
            resp = await self._get(client, url, per_page=100)
            return [ReviewDTO.from_api(row, pr_number=pr_number) for row in resp.json()]

    async def list_commits(
        self, owner: str, repo: str, limit: int = 50
    ) -> list[CommitDTO]:
        url = f"{self._api_url}/repos/{owner}/{repo}/commits"
        async with httpx.AsyncClient(headers=self._headers(), timeout=30) as client:
            resp = await self._get(client, url, per_page=min(self._per_page, limit))
            return [CommitDTO.from_api(row) for row in resp.json()[:limit]]

    async def list_workflow_runs(
        self, owner: str, repo: str, limit: int = 50
    ) -> list[CIRunDTO]:
        url = f"{self._api_url}/repos/{owner}/{repo}/actions/runs"
        async with httpx.AsyncClient(headers=self._headers(), timeout=30) as client:
            resp = await self._get(client, url, per_page=min(self._per_page, limit))
            runs = resp.json().get("workflow_runs", [])
            return [CIRunDTO.from_api(row) for row in runs[:limit]]


class FixtureGitHubClient:
    """Serves recorded JSON, so the read path runs with zero live calls.

    Expects ``<fixtures_dir>/github_repo.json`` (one object) and
    ``<fixtures_dir>/github_prs.json`` (a list of PR objects).
    """

    def __init__(self, fixtures_dir: str | Path) -> None:
        self._dir = Path(fixtures_dir)

    def _load(self, filename: str):
        path = self._dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Fixture not found: {path}")
        return json.loads(path.read_text())

    async def get_repository(self, owner: str, repo: str) -> RepositoryDTO:
        return RepositoryDTO.from_api(self._load("github_repo.json"))

    async def list_pull_requests(
        self, owner: str, repo: str, limit: int = 20
    ) -> list[PullRequestDTO]:
        rows = self._load("github_prs.json")[:limit]
        return [PullRequestDTO.from_api(row) for row in rows]

    async def list_reviews(
        self, owner: str, repo: str, pr_number: int
    ) -> list[ReviewDTO]:
        # github_reviews.json maps PR number (as string) -> list of review objects.
        by_pr = self._load("github_reviews.json")
        rows = by_pr.get(str(pr_number), [])
        return [ReviewDTO.from_api(row, pr_number=pr_number) for row in rows]

    async def list_commits(
        self, owner: str, repo: str, limit: int = 50
    ) -> list[CommitDTO]:
        rows = self._load("github_commits.json")[:limit]
        return [CommitDTO.from_api(row) for row in rows]

    async def list_workflow_runs(
        self, owner: str, repo: str, limit: int = 50
    ) -> list[CIRunDTO]:
        rows = self._load("github_runs.json")[:limit]
        return [CIRunDTO.from_api(row) for row in rows]


def build_client(source: str, fixtures_dir: str | Path | None = None) -> GitHubClient:
    """Factory: ``source`` is ``"live"`` or ``"fixture"``."""

    if source == "live":
        return RestGitHubClient()
    if source == "fixture":
        base = fixtures_dir or Path(__file__).resolve().parents[3] / "tests" / "fixtures"
        return FixtureGitHubClient(base)
    raise ValueError(f"Unknown source '{source}' (expected 'live' or 'fixture')")
