"""Liveness endpoint (public).

Keep this lean: it must answer in single-digit milliseconds and never leak
operational detail. Anything richer belongs behind auth on ``/system/*``.
"""

from __future__ import annotations

from time import monotonic

from fastapi import APIRouter

from core.config import get_settings


router = APIRouter()


_PROCESS_STARTED_AT = monotonic()


@router.get("/health", tags=["health"], summary="Liveness probe")
def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "env": settings.app_env,
        "version": "0.1.0",
        "app_uptime_seconds": max(0.0, monotonic() - _PROCESS_STARTED_AT),
    }
