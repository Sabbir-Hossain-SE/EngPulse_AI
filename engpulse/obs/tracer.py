"""Tracers behind one ``span(name, **metadata)`` context manager.

* ``NoOpTracer`` — default; near-zero overhead.
* ``RecordingTracer`` — captures spans in memory (tests assert nothing is silent).
* ``LangfuseTracer`` — forwards spans to a self-hosted Langfuse, best-effort and
  fully guarded so an SDK/version mismatch can never break a request.

The active tracer is a process global, switchable for tests via ``set_tracer``.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol

from engpulse.config import get_settings
from engpulse.logging import get_logger

log = get_logger(__name__)


@dataclass
class Span:
    name: str
    metadata: dict = field(default_factory=dict)
    output: Any = None
    error: str | None = None


class Tracer(Protocol):
    def span(self, name: str, **metadata) -> Any: ...


class NoOpTracer:
    @contextmanager
    def span(self, name: str, **metadata) -> Iterator[Span]:
        yield Span(name=name, metadata=metadata)


class RecordingTracer:
    """In-memory tracer for tests — records every span that runs."""

    def __init__(self) -> None:
        self.spans: list[Span] = []

    @contextmanager
    def span(self, name: str, **metadata) -> Iterator[Span]:
        s = Span(name=name, metadata=dict(metadata))
        try:
            yield s
        except Exception as exc:  # noqa: BLE001 - record then re-raise
            s.error = str(exc)
            raise
        finally:
            self.spans.append(s)

    def names(self) -> list[str]:
        return [s.name for s in self.spans]


class LangfuseTracer:
    def __init__(self) -> None:
        from langfuse import Langfuse  # imported lazily

        settings = get_settings()
        self._client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )

    @contextmanager
    def span(self, name: str, **metadata) -> Iterator[Span]:
        s = Span(name=name, metadata=dict(metadata))
        lf_span = None
        try:
            lf_span = self._client.span(name=name, input=metadata)
        except Exception as exc:  # noqa: BLE001 - never break the request
            log.warning("Langfuse span start failed: %s", exc)
        try:
            yield s
        except Exception as exc:  # noqa: BLE001
            s.error = str(exc)
            raise
        finally:
            try:
                if lf_span is not None:
                    lf_span.end(output=s.output, metadata={"error": s.error})
            except Exception as exc:  # noqa: BLE001
                log.warning("Langfuse span end failed: %s", exc)


_ACTIVE: Tracer | None = None


def _default_tracer() -> Tracer:
    settings = get_settings()
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        try:
            return LangfuseTracer()
        except Exception as exc:  # noqa: BLE001 - fall back to no-op
            log.warning("Langfuse unavailable (%s); tracing disabled", exc)
    return NoOpTracer()


def get_tracer() -> Tracer:
    global _ACTIVE
    if _ACTIVE is None:
        _ACTIVE = _default_tracer()
    return _ACTIVE


def set_tracer(tracer: Tracer | None) -> None:
    """Override the active tracer (tests); pass None to reset to the default."""

    global _ACTIVE
    _ACTIVE = tracer
