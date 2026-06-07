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

    # Phase 2.7 (Feature 7) portfolio-aware enrichment. All optional so a
    # recommendation generated without portfolio context stays valid.
    # ``held_weight_pct`` is the position's weight WITHIN current holdings (%),
    # not a % of total equity.
    is_held: bool = False
    held_weight_pct: float | None = None
    held_quantity: float | None = None
    held_avg_cost: float | None = None
    held_unrealized_pct: float | None = None
    portfolio_note: str | None = None

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


# ── Top Picks (Feature 2) ─────────────────────────────────────────────────────

RecommendationStrength = Literal["Weak", "Neutral", "Strong"]

# Safer, non-advice signal vocabulary (no "buy"/"guaranteed" wording).
RecommendationSignal = Literal[
    "Watch", "Actionable", "Accumulate", "Wait", "Avoid", "Risky", "Take Profit"
]


class TopPick(BaseModel):
    """One ranked quant pick. Research signal — decision support, not advice."""

    symbol: str
    company_name: str | None = None
    exchange: str | None = None
    sector: str | None = None  # no source yet (securities master has no sector)
    price: float | None = None
    change_pct: float | None = None
    volume: float | None = None
    value: float | None = None
    quant_score: int = Field(ge=0, le=100, default=0)
    strength: RecommendationStrength
    signal: RecommendationSignal
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    last_updated: str | None = None


class TopPicksResponse(BaseModel):
    picks: list[TopPick] = Field(default_factory=list)
    coverage: str = "tracked_universe"  # full_market only when a full scan exists
    universe_size: int = 0
    as_of: str | None = None
    disclaimer: str = (
        "Research signals — decision support only, not financial advice. "
        "No orders placed."
    )


# ── Explainability (Feature 4) ────────────────────────────────────────────────


class ScoreContribution(BaseModel):
    """One component's contribution to the weighted ``final_score``.

    ``contribution = weight * score`` (points out of 100). Lets the UI show
    *why* a final score is what it is, not just the raw component scores.
    """

    component: str                       # engine key, e.g. "momentum"
    label: str                           # display label, e.g. "Momentum"
    score: int | None = None             # 0..100 component score (None = N/A)
    weight: float = Field(ge=0.0, le=1.0)
    contribution: float                  # weight * score, points toward final


class RecommendationExplanation(BaseModel):
    """Structured 'why' for one symbol — derived from a RecommendationResult.

    Read-only view: it never writes a snapshot and adds no new signal. The
    summary stays in research-signal language (no advice wording).
    """

    symbol: str
    profile: RecommendationProfile
    horizon: RecommendationHorizon
    action: RecommendationAction
    strength: RecommendationStrength
    signal: RecommendationSignal
    final_score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    action_threshold_used: int = 0
    contributions: list[ScoreContribution] = Field(default_factory=list)
    summary: str = ""
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    data_status: DataStatus = "FRESH"
    as_of: str
    disclaimer: str = "research signal · not financial advice · no orders placed"


# ── History + Performance (Feature 5) ─────────────────────────────────────────


class RecommendationHistoryItem(BaseModel):
    """One persisted snapshot, mapped to the display vocabulary.

    ``final_score`` is recomputed from the stored component ``scores`` with the
    snapshot's profile weights — the same math the live engine uses — so old
    rows render consistently without storing a redundant column.
    """

    id: str | None = None
    symbol: str
    profile: str | None = None
    horizon: str
    action: str                          # stored vocab incl. legacy BUY/SELL
    signal: RecommendationSignal
    strength: RecommendationStrength
    final_score: int = Field(ge=0, le=100, default=0)
    confidence: float | None = None
    status: str = "OPEN"
    reference_price: float | None = None
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: str | None = None
    as_of: str | None = None


class RecommendationHistoryResponse(BaseModel):
    items: list[RecommendationHistoryItem] = Field(default_factory=list)
    count: int = 0
    range: str = "ALL"
    as_of: str | None = None
    disclaimer: str = "research signal · not financial advice · no orders placed"


class RecommendationPerformanceItem(BaseModel):
    """Hypothetical mark-to-market for one snapshot.

    ``return_pct = (current_price - reference_price) / reference_price``. This
    is NOT an executed-trade P&L — it measures the signal's reference price
    against the latest quote, for research review only.
    """

    id: str | None = None
    symbol: str
    horizon: str
    action: str
    signal: RecommendationSignal
    reference_price: float
    current_price: float
    return_pct: float
    stale: bool = False
    created_at: str | None = None
    priced_as_of: str | None = None


class RecommendationPerformanceResponse(BaseModel):
    items: list[RecommendationPerformanceItem] = Field(default_factory=list)
    total: int = 0                       # snapshots in range
    evaluated: int = 0                   # had reference_price AND a current quote
    skipped_no_reference: int = 0
    skipped_no_quote: int = 0
    win_rate: float | None = None        # share of evaluated with return_pct > 0
    avg_return_pct: float | None = None
    best: RecommendationPerformanceItem | None = None
    worst: RecommendationPerformanceItem | None = None
    range: str = "ALL"
    as_of: str | None = None
    basis: str = "hypothetical_from_reference_price"
    disclaimer: str = (
        "Hypothetical return from the mark price at signal time to the latest "
        "quote — not an executed trade. Research signal, not financial advice."
    )
