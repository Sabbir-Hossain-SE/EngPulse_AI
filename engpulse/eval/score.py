"""Precision/recall scoring for detectors against the labeled corpus.

A detector's predictions and the ground-truth labels are reduced to comparable
sets of identifiers (PR numbers, issue keys, "test@sha" pairs); ``prf`` then
computes true/false positives and negatives. This is the measurement backbone
the whole eval harness is built on.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PRFScore:
    detector: str
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return 1.0 if denom == 0 else self.tp / denom

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return 1.0 if denom == 0 else self.tp / denom

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 0.0 if (p + r) == 0 else 2 * p * r / (p + r)

    def as_dict(self) -> dict:
        return {
            "detector": self.detector,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


def prf(detector: str, predicted: set, expected: set) -> PRFScore:
    return PRFScore(
        detector=detector,
        tp=len(predicted & expected),
        fp=len(predicted - expected),
        fn=len(expected - predicted),
    )
