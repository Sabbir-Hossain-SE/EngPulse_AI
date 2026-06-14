"""Config loads, parses owner/name, and never leaks secrets."""

from __future__ import annotations

from engpulse.config import Settings, get_settings


def test_repo_is_split_into_owner_and_name(monkeypatch):
    monkeypatch.setenv("GITHUB_REPO", "octocat/hello-world")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.github_owner == "octocat"
    assert settings.github_repo_name == "hello-world"
    get_settings.cache_clear()


def test_safe_dump_masks_token():
    settings = Settings(github_token="ghp_supersecrettoken123")
    dumped = settings.safe_dump()
    assert "supersecret" not in dumped["github_token"]
    assert dumped["github_token"] != "ghp_supersecrettoken123"


def test_safe_dump_marks_unset_token():
    settings = Settings(github_token="")
    assert settings.safe_dump()["github_token"] == "<unset>"


def test_ollama_seam_defaults_are_openai_compatible():
    settings = Settings()
    assert settings.ollama_base_url.endswith("/v1")
    assert settings.ollama_embed_model  # an embedding model is configured
