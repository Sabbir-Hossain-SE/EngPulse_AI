"""GitHub connector: typed DTOs, an async REST client, and a fixture client."""

from engpulse.connectors.github.client import (
    FixtureGitHubClient,
    GitHubClient,
    RestGitHubClient,
    build_client,
)
from engpulse.connectors.github.schemas import (
    CIRunDTO,
    CommitDTO,
    PullRequestDTO,
    RepositoryDTO,
    ReviewDTO,
)

__all__ = [
    "GitHubClient",
    "RestGitHubClient",
    "FixtureGitHubClient",
    "build_client",
    "RepositoryDTO",
    "PullRequestDTO",
    "ReviewDTO",
    "CommitDTO",
    "CIRunDTO",
]
