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

    # Surfaced so the route layer can run guardrails without re-computing
    # scanner indicators. Phase 1 review found the route was calling
    # ``scanner_service.compute_indicators(bars)`` a second time purely to
    # read this value — now the engine emits it directly.
    avg_value_20d: float | None = None

    disclaimer: str = "research signal · not financial advice · no orders placed"


class RecommendationPreviewRequest(BaseModel):
    """Body for POST /recommendations/preview — runs engine without persisting."""

    symbol: str = Field(min_length=1, max_length=20)
    profile: RecommendationProfile = "short_aggressive"
    horizon: RecommendationHorizon | None = None
    total_equity: float | None = Field(default=None, ge=0.0)
