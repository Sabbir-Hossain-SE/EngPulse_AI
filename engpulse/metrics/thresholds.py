"""Typed, YAML-backed detector thresholds.

All detector tuning lives in ``config/thresholds.yaml`` (PRD: "no hard-coded
values; admin-tunable"). The model carries sane defaults, so the system runs
even if the file is absent; the file only overrides.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "thresholds.yaml"


class PRFlowThresholds(BaseModel):
    stale_pr_days: int = 7
    abandoned_pr_days: int = 30
    oversized_pr_lines: int = 500
    oversized_pr_files: int = 20
    reviewer_concentration: float = 0.5


class CIHealthThresholds(BaseModel):
    flaky_min_runs: int = 2
    duration_regression_pct: float = 0.5
    duration_min_runs: int = 3


class DeliveryThresholds(BaseModel):
    stale_issue_days: int = 10
    deadline_drift_min_moves: int = 2
    reestimation_min_changes: int = 1


class Thresholds(BaseModel):
    pr_flow: PRFlowThresholds = PRFlowThresholds()
    ci_health: CIHealthThresholds = CIHealthThresholds()
    delivery: DeliveryThresholds = DeliveryThresholds()


def load_thresholds(path: str | Path | None = None) -> Thresholds:
    """Load thresholds from YAML, falling back to model defaults if absent."""

    path = Path(path) if path else _DEFAULT_PATH
    if not path.exists():
        return Thresholds()
    data = yaml.safe_load(path.read_text()) or {}
    return Thresholds.model_validate(data)
