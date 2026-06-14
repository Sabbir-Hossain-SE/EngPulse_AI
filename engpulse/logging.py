"""Minimal structured logging.

Kept intentionally light for the scaffold; the API/observability milestone
swaps this for full JSON logging wired into Langfuse.
"""

from __future__ import annotations

import logging

from engpulse.config import get_settings

_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=get_settings().log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
