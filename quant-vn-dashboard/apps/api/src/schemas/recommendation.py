"""DTOs for the recommendation engine.

Every label emitted from here is a **research signal · not financial advice ·
no orders placed**. The dashboard surfaces them as informational only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ── Profile / horizon / action / status vocabularies ─────────────────────────


RecommendationProfile = Literal["short_aggressive", "long_conservative"]


# 7 codes from the methodology spec + 3 legacy intraday/EOD codes kept on the
# table CHECK so older snapshots stay readable.
RecommendationHorizon = Literal[
    "SHORT_T3",
    "SHORT_1W",
    "SHORT_2W",
    "SHORT_1M",
    "LONG_3M",
    "LONG_6M",
    "LONG_12M",
    "INTRADAY_5M",
    "INTRADAY_15M",
    "EOD",
]


# 7 engine outputs. ``REJECTED`` is reserved for guardrail veto.
RecommendationAction = Literal[
    "BUY_CANDIDATE",
    "WATCH",
    "HOLD",
    "REDUCE",
    "SELL_CANDIDATE",
    "AVOID",
    "REJECTED",
]


RecommendationStatus = Literal["VALID", "WARNING", "REJECTED"]


GuardrailSeverity = Literal["REJECT", "WARN", "INFO"]


# Phase 2 chart module: tells the UI whether the data backing this
# recommendation is trustworthy. Drives the freshness badge.
DataStatus = Literal[
    "FRESH",              # quote + bars present, quote within stale window
    "STALE",              # quote present but older than stale window
    "DATA_UNAVAILABLE",   # quote or bars missing → recommendation downgraded
    "PROVIDER_ERROR",     # provider returned an error (AUTH_FAILED / etc.)
]


# ── Building blocks ──────────────────────────────────────────────────────────


class RecommendationScores(BaseModel):
    """Component 0..100 scores feeding the weighted final_score."""

    trend: int = Field(ge=0, le=100)
    momentum: int = Field(ge=0, le=100)
    volume: int = Field(ge=0, le=100)
    liquidity: int = Field(ge=0, le=100)
    risk: int = Field(ge=0, le=100)
    # risk_inverse = 100 - risk; surfaced so the UI can render it directly.
    risk_inverse: int = Field(ge=0, le=100)
    market_regime: int = Field(ge=0, le=100)
    portfolio_fit: int = Field(ge=0, le=100)
    # ML probability is optional in Phase 1; weight contributes 0 when null.
    ml_probability: float | None = Field(default=None, ge=0.0, le=1.0)


class GuardrailHit(BaseModel):
    code: str
    severity: GuardrailSeverity
    message: str


class ChartContext(BaseModel):
    """Compact technical snapshot embedded on every recommendation.

    The UI uses this to render a thumbnail/badge row beside the action
    without having to call ``/market/symbol-detail`` separately. Numbers
    here are the SAME indicators used to derive the action, so the chart
    and the recommendation can never disagree.
    """

    timeframe: str = "1d"
    last_candle_time: str | None = None     # ISO timestamp of newest bar
    trend: str = "UNKNOWN"
    ma20: float | None = None
    ma50: float | None = None
    rsi: float | None = None
    volume_ratio_20d: float | None = None
    atr14: float | None = None


class RecommendationResult(BaseModel):
    """Full engine output for one symbol/profile/horizon combination."""

    symbol: str
    profile: RecommendationProfile
    horizon: RecommendationHorizon
    action: RecommendationAction
    status: RecommendationStatus = "VALID"
    confidence: float = Field(ge=0.0, le=1.0)
    final_score: int = Field(ge=0, le=100)
    scores: RecommendationScores

    last_price: float | None = None
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    stop_loss: float | None = None
    take_profit_1: float | None = None
    take_profit_2: float | None = None
    position_size_vnd: int | None = None
    estimated_quantity: int | None = None
    estimated_total_cost: int | None = None

    trend: str = "UNKNOWN"
    signals: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    as_of: str

    # Phase 2 chart module — every recommendation now carries the inputs
    # operators need to verify the call without leaving the page.
    data_status: DataStatus = "FRESH"
    latest_quote: dict | None = None       # serialised LatestQuote, or None
    chart_context: ChartContext | None = None
    chart_url: str = ""                    # set by the route layer

    # Surfaced so the route layer can run guardrails without re-computing
    # scanner indicators. Phase 1 review found the route was calling
    # ``scanner_service.compute_indicators(bars)`` a second time purely to
    # read this value — now the engine emits it directly.
    avg_value_20d: float | None = None

    # Phase 2.B guardrail upgrade — additional indicator surface so the
    # frontend can render the guardrail panel without re-fetching scanner.
    vol_cov_20d: float | None = None
    consecutive_ceilings: int | None = None
    ma200: float | None = None
    price_above_ma200: bool | None = None

    # Phase 2.B guardrail report (3-layer pipeline outcome). All fields
    # default to backwards-compatible "no guardrail run" values so old
    # callers that don't pass fundamentals still get a sensible payload.
    guardrail_status: Literal["PASS", "REJECTED", "NOT_RUN"] = "NOT_RUN"
    guardrail_layer_results: list[dict] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    fundamental_data_status: Literal[
        "FUNDAMENTAL_DATA_AVAILABLE",
        "FUNDAMENTAL_DATA_MISSING",
        "FUNDAMENTAL_DATA_PARTIAL",
        "NOT_EVALUATED",
    ] = "NOT_EVALUATED"
    action_threshold_used: int = 0

    disclaimer: str = "research signal · not financial advice · no orders placed"


class RecommendationPreviewRequest(BaseModel):
    """Body for POST /recommendations/preview — runs engine without persisting."""

    symbol: str = Field(min_length=1, max_length=20)
    profile: RecommendationProfile = "short_aggressive"
    horizon: RecommendationHorizon | None = None
    total_equity: float | None = Field(default=None, ge=0.0)
