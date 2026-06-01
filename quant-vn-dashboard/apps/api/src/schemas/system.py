"""DTOs for the System Status + Data Quality endpoints.

These payloads are designed to be safe to render verbatim in the dashboard:
no secrets, no full URLs, no exception bodies. Anything that could leak is
either redacted upstream or replaced with a boolean ``configured`` flag and
a host-only string.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

HealthLevel = Literal["ok", "degraded", "down"]


class ProviderHealth(BaseModel):
    """Market data provider readiness snapshot."""

    name: str
    ready: bool
    mock: bool
    token_cached: bool
    last_call_ts: datetime | None = None
    note: str | None = None
    error: str | None = None


class CacheHealth(BaseModel):
    """Hot cache health snapshot."""

    name: str = Field(description="memory | redis | unknown")
    configured: bool = Field(description="True when an external cache URL is set.")
    healthy: bool = Field(description="True when ping/round-trip succeeds.")
    last_poll_ts: datetime | None = None
    last_poll_ok: bool | None = None
    last_poll_error: str | None = None
    error: str | None = None


class SupabaseHealth(BaseModel):
    """Supabase reachability flags.

    The host is parsed from ``supabase_url`` so the dashboard can display
    ``localhost`` or ``xyz.supabase.co`` without ever surfacing the full URL.
    """

    configured: bool
    url_host: str | None = None


class DuckDBHealth(BaseModel):
    """DuckDB warehouse health snapshot."""

    configured: bool
    path: str | None = None
    exists: bool = False
    size_bytes: int | None = None


class PollerHealth(BaseModel):
    """Market poller health snapshot."""

    enabled: bool
    running: bool
    active_symbols_count: int = 0


class StaleQuoteRow(BaseModel):
    """Per-symbol stale-quote row for the data-quality UI table."""

    symbol: str
    ts: str
    age_seconds: int
    stale: bool
    source: str


class DataQualitySnapshot(BaseModel):
    """Aggregated data-quality metrics across the cache + provider surface."""

    timestamp: datetime
    stale_quote_count: int = 0
    total_tracked_symbols: int = 0
    symbols_without_quote: list[str] = Field(default_factory=list)
    stale_quote_rows: list[StaleQuoteRow] = Field(default_factory=list)
    cache_misses: int | None = None
    provider_errors: int | None = None
    last_successful_sync: datetime | None = None
    notes: list[str] = Field(default_factory=list)


class SystemHealth(BaseModel):
    """Lightweight liveness payload that never requires auth."""

    status: HealthLevel
    env: str
    version: str
    app_uptime_seconds: float | None = None
    cache_reachable: bool = True
    settings_loaded: bool = True
    checked_at: datetime


class SystemStatus(BaseModel):
    """Full operator snapshot. Auth-gated to avoid leaking ops data."""

    # ── Backwards-compatible fields from the previous /system/status ─────────
    app_env: str
    missing_secrets: list[str] = Field(default_factory=list)
    ssi_base_url: str
    redis_configured: bool

    # ── New structured fields ────────────────────────────────────────────────
    provider: ProviderHealth
    cache: CacheHealth
    supabase: SupabaseHealth
    duckdb: DuckDBHealth
    poller: PollerHealth
    data_quality: DataQualitySnapshot
    checked_at: datetime
