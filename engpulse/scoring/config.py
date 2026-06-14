"""Typed, YAML-backed scoring configuration.

Every weight, penalty, and band lives in ``config/scoring.yaml`` so the health
model is transparent and admin-tunable (PRD §10) — no magic numbers in code.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "scoring.yaml"


class ScoringConfig(BaseModel):
    severity_penalties: dict[str, float] = Field(
        default_factory=lambda: {"low": 5, "medium": 10, "high": 20, "critical": 35}
    )
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "review_flow": 0.30, "delivery": 0.30, "ci_test": 0.20, "knowledge": 0.20,
        }
    )
    bands: dict[str, float] = Field(
        default_factory=lambda: {"healthy": 90, "watch": 75, "at_risk": 60}
    )
    flaky_severity: str = "medium"
    duration_regression_severity: str = "high"

    def penalty(self, severity: str) -> float:
        return self.severity_penalties.get(severity, 0.0)

    def band_for(self, score: float) -> str:
        if score >= self.bands["healthy"]:
            return "Healthy"
        if score >= self.bands["watch"]:
            return "Watch"
        if score >= self.bands["at_risk"]:
            return "At Risk"
        return "Critical"


def load_scoring_config(path: str | Path | None = None) -> ScoringConfig:
    path = Path(path) if path else _DEFAULT_PATH
    if not path.exists():
        return ScoringConfig()
    return ScoringConfig.model_validate(yaml.safe_load(path.read_text()) or {})
