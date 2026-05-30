"""System status + data-quality routes.

Endpoint design notes
---------------------
* ``/system/health`` is the only **public** endpoint here. It must NEVER leak
  secrets or upstream error bodies — we return shape, not detail. Status is
  ``ok | degraded | down`` based on a minimal liveness check.
* Every other endpoint requires a valid Supabase JWT. That keeps operational
  data (cache backend name, missing-secret list, poller state) off the open
  internet.
* All upstream error strings flow through ``services.data_quality._redact``
  so a misconfigured provider can't surface a Bearer token in the UI.
"""

from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic

from fastapi import APIRouter, Depends

from core.config import Settings, get_settings
from core.deps import get_cache, get_market_provider, get_poller
from core.security import AuthContext, get_current_user
from providers.market_data.base import MarketDataProvider
from schemas.system import (
    CacheHealth,
    DataQualitySnapshot,
    DuckDBHealth,
    PollerHealth,
    ProviderHealth,
    SupabaseHealth,
    SystemHealth,
    SystemStatus,
)
from services.cache import Cache
from services.data_quality import (
    build_data_quality_snapshot,
    summarize_cache,
    summarize_duckdb,
    summarize_poller,
    summarize_provider,
    summarize_supabase,
)
from workers.market_poller import MarketPoller


router = APIRouter()


# Process start time — used for a best-effort ``app_uptime_seconds`` value
# in ``/system/health``. Reset on every cold start.
_PROCESS_STARTED_AT = monotonic()


# ── Public liveness ─────────────────────────────────────────────────────────


@router.get(
    "/health",
    response_model=SystemHealth,
    summary="Liveness/readiness probe (public)",
)
async def system_health(
    settings: Settings = Depends(get_settings),
    cache: Cache = Depends(get_cache),
) -> SystemHealth:
    """Lightweight liveness check. Always returns 200 with a status field.

    Status logic:
        * ``ok``       — cache reachable + settings loaded
        * ``degraded`` — settings loaded but cache ping failed
        * ``down``     — settings load itself failed (will not happen in
                         practice because FastAPI would refuse to boot first)
    """
    cache_reachable = False
    try:
        if hasattr(cache, "ping"):
            cache_reachable = bool(await cache.ping())
        else:
            cache_reachable = True
    except Exception:
        cache_reachable = False

    settings_loaded = True
    status: str = "ok" if cache_reachable and settings_loaded else "degraded"
    if not settings_loaded:
        status = "down"

    return SystemHealth(
        status=status,  # type: ignore[arg-type]
        env=settings.app_env,
        version="0.1.0",
        app_uptime_seconds=max(0.0, monotonic() - _PROCESS_STARTED_AT),
        cache_reachable=cache_reachable,
        settings_loaded=settings_loaded,
        checked_at=datetime.now(timezone.utc),
    )


# ── Auth-gated operator endpoints ───────────────────────────────────────────


@router.get(
    "/status",
    response_model=SystemStatus,
    summary="Full operator status snapshot",
)
async def system_status(
    _user: AuthContext = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    cache: Cache = Depends(get_cache),
    provider: MarketDataProvider = Depends(get_market_provider),
    poller: MarketPoller | None = Depends(get_poller),
) -> SystemStatus:
    provider_summary = await summarize_provider(provider)
    cache_summary = await summarize_cache(cache, settings)
    supabase_summary = summarize_supabase(settings)
    duckdb_summary = summarize_duckdb(settings)
    poller_summary = await summarize_poller(poller)
    data_quality = await build_data_quality_snapshot(cache, poller, settings)

    return SystemStatus(
        app_env=settings.app_env,
        missing_secrets=settings.missing_secrets(),
        ssi_base_url=settings.ssi_base_url,
        redis_configured=bool(
            settings.redis_url or settings.upstash_redis_rest_url
        ),
        provider=ProviderHealth(**provider_summary),
        cache=CacheHealth(**cache_summary),
        supabase=SupabaseHealth(**supabase_summary),
        duckdb=DuckDBHealth(**duckdb_summary),
        poller=PollerHealth(**poller_summary),
        data_quality=DataQualitySnapshot(**data_quality),
        checked_at=datetime.now(timezone.utc),
    )


@router.get(
    "/providers",
    response_model=list[ProviderHealth],
    summary="List configured market data providers + their health",
)
async def system_providers(
    _user: AuthContext = Depends(get_current_user),
    provider: MarketDataProvider = Depends(get_market_provider),
) -> list[ProviderHealth]:
    summary = await summarize_provider(provider)
    return [ProviderHealth(**summary)]


@router.get(
    "/cache",
    response_model=CacheHealth,
    summary="Hot cache health",
)
async def system_cache(
    _user: AuthContext = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    cache: Cache = Depends(get_cache),
) -> CacheHealth:
    summary = await summarize_cache(cache, settings)
    return CacheHealth(**summary)


@router.get(
    "/data-quality",
    response_model=DataQualitySnapshot,
    summary="Cache-derived data-quality snapshot",
)
async def system_data_quality(
    _user: AuthContext = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    cache: Cache = Depends(get_cache),
    poller: MarketPoller | None = Depends(get_poller),
) -> DataQualitySnapshot:
    payload = await build_data_quality_snapshot(cache, poller, settings)
    return DataQualitySnapshot(**payload)
