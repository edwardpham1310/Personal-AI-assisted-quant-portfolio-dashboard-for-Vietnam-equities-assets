"""DTOs returned by the market data gateway."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Exchange = Literal["HOSE", "HNX", "UPCOM"]
Interval = Literal["1m", "5m", "15m", "30m", "1h"]


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


class Quote(BaseModel):
    symbol: str
    exchange: Exchange | None = None
    price: float
    reference_price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    volume: float | None = None
    ts: datetime  # provider timestamp (UTC)
    stale: bool = False
    source: str  # 'ssi' | 'mock' | 'cache'


# Phase 2 data-policy status codes. The dashboard renders these directly so
# operators can distinguish "we haven't been told the credentials" from "the
# credentials are wrong" from "the upstream is briefly flaky".
ProviderStatusCode = Literal[
    "READY",            # creds present + last call succeeded recently
    "CONFIG_MISSING",   # SSI_CONSUMER_ID or SSI_CONSUMER_SECRET is blank
    "AUTH_FAILED",      # creds present but provider rejected (401/403)
    "PROVIDER_ERROR",   # last call failed for a non-auth reason
    "STALE",            # last successful call older than freshness window
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
    # back-compat (``ready == status_code == "READY"``).
    status_code: ProviderStatusCode = "READY"
