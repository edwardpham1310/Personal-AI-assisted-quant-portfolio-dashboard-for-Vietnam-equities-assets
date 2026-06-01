"""DTOs returned by the market data gateway."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Exchange = Literal["HOSE", "HNX", "UPCOM"]
Interval = Literal["1m", "5m", "15m", "30m", "1h"]

# Phase 2 chart-module timeframes. ``1d`` is mapped to the daily endpoint;
# intraday intervals (``1m``-``1h``) map to ``Interval`` above. ``1w`` is
# documented as "aggregate on the client" — backend returns daily and the
# UI buckets the bars; no extra SSI cost.
CandleTimeframe = Literal["1m", "5m", "15m", "30m", "1h", "1d", "1w"]


class Security(BaseModel):
    symbol: str
    name: str | None = None
    exchange: Exchange | None = None
    type: str | None = None
    status: str | None = None
    board: str | None = None
    lot_size: int | None = None
    reference_price: float | None = None


class IndexInfo(BaseModel):
    code: str
    name: str | None = None
    exchange: Exchange | None = None


class OHLCVBar(BaseModel):
    symbol: str
    ts: datetime  # bar timestamp in UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
    value: float | None = None
    # Phase 2.B: optional per-bar daily ceiling so the scanner's
    # consecutive-ceiling counter has history when bars come from
    # DailyStockPrice. Bars from DailyOhlc leave this None.
    ceiling_price: float | None = None
    floor_price: float | None = None


class Quote(BaseModel):
    symbol: str
    exchange: Exchange | None = None
    price: float
    reference_price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    volume: float | None = None
    # Phase 2 chart module: optional fields that the SSI parser populates
    # when present. Legacy consumers ignore them; the chart module uses them
    # to render ceiling/floor lines.
    ceiling_price: float | None = None
    floor_price: float | None = None
    value: float | None = None
    ts: datetime  # provider timestamp (UTC)
    stale: bool = False
    source: str  # 'ssi' | 'mock' | 'cache'


# Phase 2 data-policy status codes. The dashboard renders these directly so
# operators can distinguish "we haven't been told the credentials" from "the
# credentials are wrong" from "the upstream is briefly flaky".
#
# Phase 2.5 added ``CONNECTED`` (preferred over the legacy ``READY``),
# ``ERROR`` (preferred over ``PROVIDER_ERROR``), and ``RATE_LIMITED``. The
# old codes remain in the enum for back-compat with any cached snapshots,
# but the providers now emit the new names.
ProviderStatusCode = Literal[
    "CONNECTED",        # creds present + last call succeeded recently (preferred)
    "READY",            # legacy alias of CONNECTED — kept for cache compat
    "CONFIG_MISSING",   # SSI_CONSUMER_ID or SSI_CONSUMER_SECRET is blank
    "AUTH_FAILED",      # creds present but provider rejected (401/403)
    "RATE_LIMITED",     # provider returned 429 within the recent window
    "ERROR",            # last call failed for a non-auth reason (preferred)
    "PROVIDER_ERROR",   # legacy alias of ERROR — kept for cache compat
    "STALE",            # last successful call older than freshness window
]


# Token state for the SSI access-token cache.
TokenStatus = Literal[
    "VALID",     # have a token, not yet expired (with leeway)
    "EXPIRED",   # had a token, but it crossed the expiry window
    "MISSING",   # creds present but token has never been fetched
    "UNKNOWN",   # provider does not implement token caching (mock)
]


# What kind of provider is serving market data.
ProviderMode = Literal[
    "REAL",            # SSI FastConnect Data — production
    "MOCK_TEST_ONLY",  # MockMarketDataProvider — dev / unit tests only
]


class ProviderStatus(BaseModel):
    name: str
    ready: bool
    mock: bool
    token_cached: bool
    last_call_ts: datetime | None = None
    note: str | None = None
    # Phase 2 data policy: routes + UI consume status_code to render an
    # actionable error rather than a generic "down". ``ready`` is kept for
    # back-compat (``ready == status_code in {CONNECTED, READY}``).
    status_code: ProviderStatusCode = "CONNECTED"

    # ── Phase 2.5 additions ────────────────────────────────────────────
    # Distinct from ``mock: bool`` so the UI can render a critical banner
    # when production is somehow serving MOCK_TEST_ONLY data.
    mode: ProviderMode = "REAL"
    # ``last_successful_call_at`` is an alias of ``last_call_ts``; we keep
    # both so legacy consumers don't break. ``last_failed_call_at`` is new.
    last_successful_call_at: datetime | None = None
    last_failed_call_at: datetime | None = None
    # ``last_error_sanitized`` is the redacted short message (e.g.
    # "HTTPStatusError"). ``note`` is the same for back-compat.
    last_error_sanitized: str | None = None
    # Token cache state — ``token_cached: bool`` was binary; this is the
    # actionable enum the dashboard renders.
    token_status: TokenStatus = "UNKNOWN"
    # Composite flag: True when ``mode=REAL`` and ``status_code=CONNECTED``.
    production_ready: bool = False


# ── Phase 2 chart module ────────────────────────────────────────────────────


class Candle(BaseModel):
    """Normalised candle for the Phase 2 chart module.

    Returned by ``/market/candles/{symbol}`` and embedded in
    ``SymbolDetail``. ``OHLCVBar`` is the legacy shape used by older routes
    and the scanner — we keep both so existing tests don't drift.
    """

    symbol: str
    timeframe: CandleTimeframe
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    value: float | None = None
    source: str = "SSI"
    is_realtime: bool = False
    is_stale: bool = False


class LatestQuote(BaseModel):
    """Enriched quote for the Phase 2 chart module.

    Includes ceiling/floor (which SSI already returns on
    ``DailyStockPrice``) and a separate ``received_at`` so the UI can show
    "as of HH:MM:SS" without re-deriving from the provider timestamp.
    ``Quote`` (legacy) stays for the SSE / scanner paths.
    """

    symbol: str
    last_price: float
    change: float | None = None
    change_pct: float | None = None
    reference_price: float | None = None
    ceiling_price: float | None = None
    floor_price: float | None = None
    volume: float | None = None
    value: float | None = None
    bid: float | None = None
    ask: float | None = None
    provider_timestamp: datetime
    received_at: datetime
    is_stale: bool = False
    source: str = "SSI"


class DataFreshness(BaseModel):
    """Per-section freshness so the UI can label which slice is stale."""

    quote_age_seconds: float | None = None
    intraday_last_ts: datetime | None = None
    daily_last_ts: datetime | None = None


class SymbolDetail(BaseModel):
    """Aggregator response for ``/market/symbol-detail/{symbol}``.

    A single backend round-trip populates the symbol detail drawer used
    from Market, Watchlist, Portfolio, and Recommendations.
    """

    security: Security
    quote: LatestQuote | None = None
    intraday: list[Candle] = Field(default_factory=list)
    daily: list[Candle] = Field(default_factory=list)
    provider_status: ProviderStatus
    freshness: DataFreshness
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Research dashboard · Market data via SSI FastConnect · "
        "Not financial advice · No orders placed."
    )
