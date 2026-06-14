"""Typed, YAML-backed alert routing configuration."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "alerts.yaml"

_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def severity_rank(severity: str) -> int:
    return _SEVERITY_RANK.get(severity, 0)


class AlertConfig(BaseModel):
    routing: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "delivery_risk": ["EM", "PM"],
            "review_bottleneck": ["TL"],
            "ci_health": ["TL"],
            "knowledge_risk": ["EM"],
            "execution": ["IC"],
        }
    )
    actions: dict[str, str] = Field(default_factory=dict)
    min_severity: str = "low"
    flaky_alert_severity: str = "medium"

    def roles_for(self, alert_type: str) -> list[str]:
        return self.routing.get(alert_type, [])

    def action_for(self, alert_type: str) -> str:
        return self.actions.get(alert_type, "Review with the responsible owner.")


def load_alert_config(path: str | Path | None = None) -> AlertConfig:
    path = Path(path) if path else _DEFAULT_PATH
    if not path.exists():
        return AlertConfig()
    return AlertConfig.model_validate(yaml.safe_load(path.read_text()) or {})
