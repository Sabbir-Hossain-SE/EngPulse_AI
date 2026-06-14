"""Typed application configuration.

A single ``Settings`` object is the one place every module reads configuration
from. The LLM is reached purely through ``ollama_base_url`` + model names
(OpenAI-compatible), so the provider is swappable via config with no code
change — this is the model-agnostic seam the PRD calls for.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---------------------------------------------------------------
    app_env: str = "local"
    log_level: str = "INFO"

    # --- Database ----------------------------------------------------------
    database_url: str = (
        "postgresql+psycopg://engpulse:engpulse@localhost:5432/engpulse"
    )

    # --- GitHub connector --------------------------------------------------
    github_token: str = ""
    github_repo: str = ""
    github_api_url: str = "https://api.github.com"

    # --- Linear connector (issue tracker) ----------------------------------
    linear_api_key: str = ""
    linear_api_url: str = "https://api.linear.app/graphql"
    linear_team_key: str = ""  # optional scope, e.g. "ENG"; empty = all teams

    # --- Ollama (model-agnostic LLM seam) ----------------------------------
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_chat_model: str = "llama3.1"
    ollama_embed_model: str = "nomic-embed-text"

    # --- Redis / Celery ----------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"

    # --- Langfuse ----------------------------------------------------------
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # --- Derived helpers ---------------------------------------------------
    @computed_field  # type: ignore[prop-decorator]
    @property
    def github_owner(self) -> str:
        return self.github_repo.split("/", 1)[0] if "/" in self.github_repo else ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def github_repo_name(self) -> str:
        return self.github_repo.split("/", 1)[1] if "/" in self.github_repo else ""

    def safe_dump(self) -> dict[str, str]:
        """Config snapshot with secrets masked — safe for logs / `check-config`."""

        def mask(value: str) -> str:
            if not value:
                return "<unset>"
            return f"{value[:4]}…{value[-2:]}" if len(value) > 8 else "set"

        return {
            "app_env": self.app_env,
            "log_level": self.log_level,
            "database_url": self.database_url,
            "github_repo": self.github_repo or "<unset>",
            "github_token": mask(self.github_token),
            "github_api_url": self.github_api_url,
            "linear_api_key": mask(self.linear_api_key),
            "linear_api_url": self.linear_api_url,
            "linear_team_key": self.linear_team_key or "<all teams>",
            "ollama_base_url": self.ollama_base_url,
            "ollama_chat_model": self.ollama_chat_model,
            "ollama_embed_model": self.ollama_embed_model,
            "redis_url": self.redis_url,
            "langfuse_host": self.langfuse_host,
            "langfuse_public_key": mask(self.langfuse_public_key),
            "langfuse_secret_key": mask(self.langfuse_secret_key),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton accessor for application settings."""

    return Settings()
