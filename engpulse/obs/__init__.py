"""Observability: a pluggable tracer so no LLM call or pipeline step is silent."""

from engpulse.obs.tracer import (
    LangfuseTracer,
    NoOpTracer,
    RecordingTracer,
    Span,
    Tracer,
    get_tracer,
    set_tracer,
)

__all__ = [
    "Span",
    "Tracer",
    "NoOpTracer",
    "RecordingTracer",
    "LangfuseTracer",
    "get_tracer",
    "set_tracer",
]
