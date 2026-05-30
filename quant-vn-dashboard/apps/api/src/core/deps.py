"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends

from core.config import Settings, get_settings
from providers.market_data import (
    MarketDataProvider,
    MockMarketDataProvider,
    SSIFastConnectProvider,
)
from services.cache import Cache, build_cache
from services.supabase_db import PostgrestDB, SupabaseDB
from workers.market_poller import MarketPoller


def get_db(settings: Settings = Depends(get_settings)) -> SupabaseDB:
    """Return a Supabase data-access client.

    Production: a thin httpx-based PostgREST wrapper.
    Tests: override via ``app.dependency_overrides[get_db] = lambda: FakeSupabaseDB()``.
    """
    return PostgrestDB(
        base_url=settings.supabase_url,
        anon_key=settings.supabase_anon_key,
    )


# Process-wide cache for the market provider so its token cache survives
# across requests. Keyed by ``ssi_use_mock`` so flipping the env var resets it.
_market_provider_instance: MarketDataProvider | None = None
_market_provider_use_mock: bool | None = None


def get_market_provider(
    settings: Settings = Depends(get_settings),
) -> MarketDataProvider:
    """Return the SSI gateway (or the mock provider when ``SSI_USE_MOCK=true``)."""
    global _market_provider_instance, _market_provider_use_mock
    if (
        _market_provider_instance is None
        or _market_provider_use_mock != settings.ssi_use_mock
    ):
        if settings.ssi_use_mock:
            _market_provider_instance = MockMarketDataProvider()
        else:
            _market_provider_instance = SSIFastConnectProvider(
                consumer_id=settings.ssi_consumer_id,
                consumer_secret=settings.ssi_consumer_secret,
                base_url=settings.ssi_base_url,
                timeout=settings.ssi_timeout_seconds,
                max_retries=settings.ssi_max_retries,
            )
        _market_provider_use_mock = settings.ssi_use_mock
    return _market_provider_instance


def reset_market_provider_cache() -> None:
    """Drop the cached market provider — used by tests between scenarios."""
    global _market_provider_instance, _market_provider_use_mock
    _market_provider_instance = None
    _market_provider_use_mock = None


# Process-wide cache + poller singletons. Initialized lazily so unit tests
# that override these dependencies never touch them.
_cache_instance: Cache | None = None
_poller_instance: MarketPoller | None = None


def get_cache(settings: Settings = Depends(get_settings)) -> Cache:
    """Return the hot cache — Redis if configured, else in-memory."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = build_cache(settings.redis_url)
    return _cache_instance


def set_cache(cache: Cache | None) -> None:
    """Used by the FastAPI lifespan to install / tear down the cache."""
    global _cache_instance
    _cache_instance = cache


def reset_cache() -> None:
    global _cache_instance
    _cache_instance = None


def get_poller() -> MarketPoller | None:
    """Return the running poller, or ``None`` when it isn't enabled."""
    return _poller_instance


def set_poller(poller: MarketPoller | None) -> None:
    global _poller_instance
    _poller_instance = poller
