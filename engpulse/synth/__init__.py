"""Grounded synthesis (Module I): evidence → schema-enforced, cited insight."""

from engpulse.synth.grounded import (
    EvidenceItem,
    synthesize_for_flag,
    synthesize_insight,
)
from engpulse.synth.schema import GeneratedInsight, Insight

__all__ = [
    "EvidenceItem",
    "Insight",
    "GeneratedInsight",
    "synthesize_insight",
    "synthesize_for_flag",
]
