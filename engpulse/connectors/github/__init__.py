"""GitHub connector: typed DTOs, an async REST client, and a fixture client."""

from engpulse.connectors.github.client import (
    FixtureGitHubClient,
    GitHubClient,
    RestGitHubClient,
    build_client,
)
from engpulse.connectors.github.schemas import PullRequestDTO, RepositoryDTO

__all__ = [
    "GitHubClient",
    "RestGitHubClient",
    "FixtureGitHubClient",
    "build_client",
    "RepositoryDTO",
    "PullRequestDTO",
]
