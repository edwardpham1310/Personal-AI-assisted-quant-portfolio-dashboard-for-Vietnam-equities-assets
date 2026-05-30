"""Structured stdlib logging.

Stays on the standard library to avoid adding a heavy dependency for the
base structure. Swap to structlog or python-json-logger later if a log
aggregator demands JSON output.
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    """Idempotent root-logger setup. Safe to call from lifespan startup."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    # Clear default handlers (uvicorn adds its own; we want one source of truth).
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
