"""Recommendation engine — pure, no I/O, no HTTP, no DB.

Reuses ``services.scanner`` for indicator math + base scoring so we do not
re-derive MA/RSI/ATR logic here. This module adds three things on top:

1. Market-regime + portfolio-fit scoring (the two dimensions scanner does not
   know about).
2. A weighted ``final_score`` that varies by ``profile``.
3. A decision matrix that maps (profile, horizon, scores, signals, trend,
   portfolio weight) onto one of the seven Phase-1 actions.

Guardrails live in ``services.risk_guardrails``. Persistence and provider
fan-out live in the route layer. Every label emitted here is a **research
signal · not financial advice · no orders placed**.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from schemas.market import OHLCVBar, Quote
from schemas.recommendation import (
    RecommendationAction,
    RecommendationHorizon,
    RecommendationProfile,
    RecommendationResult,
    RecommendationScores,
)
from services import scanner as scanner_service


# ── Constants ───────────────────────────────────────────────────────────────


# Profile weight maps. Sum to 1.0 (ml_probability sums in too — when None it
# contributes 0 and the rest do NOT renormalize). Short profile leans on
# momentum/volume; long profile leans on trend/liquidity/regime.
PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
    "short_aggressive": {
        "trend": 0.20,
        "momentum": 0.25,
        "volume": 0.15,
        "liquidity": 0.05,
        "risk_inverse": 0.10,
        "market_regime": 0.10,
        "portfolio_fit": 0.05,
        "ml_probability": 0.10,
    },
    "long_conservative": {
        "trend": 0.25,
        "momentum": 0.10,
        "volume": 0.05,
        "liquidity": 0.15,
        "risk_inverse": 0.15,
        "market_regime": 0.15,
        "portfolio_fit": 0.05,
        "ml_probability": 0.10,
    },
}

# Action thresholds applied AFTER final_score is computed.
ACTION_BUY_THRESHOLD = 70           # >=70 + UPTREND + supporting signal => BUY_CANDIDATE
ACTION_WATCH_THRESHOLD = 55         # >=55 in UPTREND/SIDEWAYS => WATCH
ACTION_REDUCE_THRESHOLD = 40        # <40 while held => REDUCE
ACTION_SELL_THRESHOLD = 30          # <30 while held + DOWNTREND => SELL_CANDIDATE

# Position sizing defaults — keep symmetric with risk_guardrails constants.
BROKERAGE_RATE = 0.0015             # 15 bps SSI all-in
SLIPPAGE_RATE = 0.0010              # 10 bps modelled slippage
MAX_POSITION_VND = 50_000_000       # hard cap per recommendation in VND
EQUITY_PCT_PER_RECO = 0.05          # 5% of total equity per recommendation
MAX_ADV_PCT = 0.005                 # 0.5% of avg 20d trading value
LOT_SIZE = 100                      # HOSE/HNX standard lot

# Stop-loss / take-profit fall-back percentages when ATR14 is null.
STOP_PCT_SHORT = 0.05               # 5% stop when ATR unavailable, short horizons
STOP_PCT_LONG = 0.10                # 10% stop when ATR unavailable, long horizons

# ATR multipliers for stops and targets keyed by horizon bucket.
HORIZON_GROUP_SHORT = {
    "SHORT_T3",
    "SHORT_1W",
    "SHORT_2W",
    "SHORT_1M",
    "INTRADAY_5M",
    "INTRADAY_15M",
    "EOD",
}
HORIZON_GROUP_LONG = {"LONG_3M", "LONG_6M", "LONG_12M"}

# Entry-zone half-widths by horizon — used when last_price is known but the
# engine wants to avoid recommending chasing far above the close.
ENTRY_BAND_PCT = {
    "SHORT_T3": 0.010,
    "SHORT_1W": 0.015,
    "SHORT_2W": 0.020,
    "SHORT_1M": 0.025,
    "INTRADAY_5M": 0.005,
    "INTRADAY_15M": 0.010,
    "EOD": 0.015,
    "LONG_3M": 0.030,
    "LONG_6M": 0.040,
    "LONG_12M": 0.050,
}

# Cache TTL hint for downstream callers (route layer reads this).
CACHE_TTL_SECONDS = 60


# ── Helpers ─────────────────────────────────────────────────────────────────


def _clamp_int(value: float, lo: int = 0, hi: int = 100) -> int:
    return int(round(max(lo, min(hi, value))))


def _slope(values: list[float]) -> float:
    """Simple linear-regression slope of ``values`` against index. None safe."""
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    num = sum((xs[i] - mean_x) * (values[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n))
    if den == 0:
        return 0.0
    return num / den


def _is_short_horizon(horizon: str) -> bool:
    return horizon in HORIZON_GROUP_SHORT


# ── Component scores ────────────────────────────────────────────────────────


def compute_market_regime(vnindex_bars: list[OHLCVBar] | None) -> int:
    """0..100 market-regime score from VNINDEX daily bars.

    Phase-1 heuristic — strictly deterministic:
        * neutral (50) when bars are missing or too short
        * 80 when last close > 50DMA AND 50DMA slope over last 10 bars > 0
        * 60 when exactly one of those holds
        * 30 when neither holds
    """
    if not vnindex_bars or len(vnindex_bars) < 60:
        return 50

    closes = [b.close for b in vnindex_bars]
    last_close = closes[-1]
    ma50 = sum(closes[-50:]) / 50
    above_ma50 = last_close > ma50

    # 50DMA slope over the last 10 bars — rebuild 50DMA point-by-point so the
    # slope reflects the moving-average trajectory, not the raw price slope.
    if len(closes) < 60:
        return 50
    ma50_series = [
        sum(closes[i - 50 + 1 : i + 1]) / 50 for i in range(len(closes) - 10, len(closes))
    ]
    slope_positive = _slope(ma50_series) > 0

    if above_ma50 and slope_positive:
        return 80
    if above_ma50 or slope_positive:
        return 60
    return 30


def compute_portfolio_fit(
    symbol: str,
    portfolio_positions: list[Any] | None,
) -> int:
    """100 when the symbol isn't held; lower as the held weight rises.

    ``portfolio_positions`` is whatever the route layer hands us — typically
    a list of ``EnrichedPosition``. The function only reads ``symbol`` and
    ``weight`` so it tolerates plain dicts too.
    """
    if portfolio_positions is None:
        return 100

    target = symbol.upper()
    for pos in portfolio_positions:
        pos_symbol = (
            getattr(pos, "symbol", None)
            or (pos.get("symbol") if isinstance(pos, dict) else None)
            or ""
        )
        if str(pos_symbol).upper() != target:
            continue
        weight = (
            getattr(pos, "weight", None)
            if not isinstance(pos, dict)
            else pos.get("weight")
        )
        if weight is None:
            # Held but weight unknown — assume small.
            return 50
        # ``weight`` is a fraction (0.05 == 5%).
        if weight < 0.05:
            return 50
        return 0
    return 100


def compute_final_score(
    scores: dict[str, float | int | None],
    weights: dict[str, float],
) -> int:
    """Weighted sum, clamped to 0..100.

    When ``ml_probability`` is None its weight contributes 0 — the spec
    explicitly says DO NOT redistribute. Probability values are in [0,1] so
    we scale to 0..100 before weighting.
    """
    total = 0.0
    for key, weight in weights.items():
        if weight <= 0:
            continue
        raw = scores.get(key)
        if raw is None:
            continue
        if key == "ml_probability":
            # ml_probability is in [0,1]; map to 0..100 for the weighted sum.
            value = float(raw) * 100.0
        else:
            value = float(raw)
        total += weight * value
    return _clamp_int(total)


def derive_action(
    profile: str,
    horizon: str,
    final_score: int,
    trend_label: str,
    momentum_score: int,
    signals: list[str],
    portfolio_weight_pct: float | None,
) -> RecommendationAction:
    """Decision matrix — order matters.

    AVOID > BUY_CANDIDATE > REDUCE/SELL_CANDIDATE > WATCH > HOLD.

    * AVOID — low liquidity flagged or strongly negative score.
    * BUY_CANDIDATE — UPTREND + score >= 70 + supporting signal.
    * SELL_CANDIDATE — DOWNTREND + score < 30 + currently held.
    * REDUCE — score < 40 + currently held.
    * WATCH — score >= 55 + UPTREND/SIDEWAYS.
    * HOLD — everything else.
    """
    held = portfolio_weight_pct is not None and portfolio_weight_pct > 0

    if "LOW_LIQUIDITY" in signals:
        return "AVOID"
    if final_score < 20:
        return "AVOID"

    supporting = (
        "BREAKOUT_20D" in signals
        or "VOLUME_SPIKE" in signals
        or "PRICE_ABOVE_MA20" in signals
    )

    if (
        trend_label == "UPTREND"
        and final_score >= ACTION_BUY_THRESHOLD
        and momentum_score >= 55
        and supporting
    ):
        return "BUY_CANDIDATE"

    if held and trend_label == "DOWNTREND" and final_score < ACTION_SELL_THRESHOLD:
        return "SELL_CANDIDATE"

    if held and final_score < ACTION_REDUCE_THRESHOLD:
        return "REDUCE"

    if (
        trend_label in {"UPTREND", "SIDEWAYS"}
        and final_score >= ACTION_WATCH_THRESHOLD
    ):
        return "WATCH"

    return "HOLD"


# ── Trade plan helpers ──────────────────────────────────────────────────────


def compute_entry_zone(
    last_price: float | None, horizon: str
) -> tuple[float, float] | None:
    """Symmetric band around ``last_price`` keyed by horizon."""
    if last_price is None or last_price <= 0:
        return None
    band = ENTRY_BAND_PCT.get(horizon, 0.015)
    low = last_price * (1 - band)
    high = last_price * (1 + band)
    return (round(low, 4), round(high, 4))


def compute_stop_loss(
    last_price: float | None, atr14: float | None, horizon: str
) -> float | None:
    """ATR-based stop with pct fallback when ATR is unavailable.

    * short horizons: 1.5 × ATR or 5% pct fallback
    * long horizons: 2.5 × ATR or 10% pct fallback
    """
    if last_price is None or last_price <= 0:
        return None
    is_short = _is_short_horizon(horizon)
    if atr14 is not None and atr14 > 0:
        multiplier = 1.5 if is_short else 2.5
        stop = last_price - multiplier * atr14
    else:
        pct = STOP_PCT_SHORT if is_short else STOP_PCT_LONG
        stop = last_price * (1 - pct)
    return round(max(stop, 0.0), 4)


def compute_take_profit(
    last_price: float | None, atr14: float | None, horizon: str
) -> tuple[float, float] | None:
    """Two-stage targets. ATR-based when available, else pct multiples of stop."""
    if last_price is None or last_price <= 0:
        return None
    is_short = _is_short_horizon(horizon)
    if atr14 is not None and atr14 > 0:
        m1 = 2.0 if is_short else 3.0
        m2 = 3.5 if is_short else 5.0
        tp1 = last_price + m1 * atr14
        tp2 = last_price + m2 * atr14
    else:
        pct1 = 0.07 if is_short else 0.15
        pct2 = 0.12 if is_short else 0.25
        tp1 = last_price * (1 + pct1)
        tp2 = last_price * (1 + pct2)
    return (round(tp1, 4), round(tp2, 4))


def compute_position_sizing(
    last_price: float | None,
    total_equity: float | None,
    avg_value_20d: float | None,
) -> dict[str, int | None]:
    """Pick the lower of: equity%, max VND cap, ADV-cap.

    Quantity rounds DOWN to ``LOT_SIZE`` (100). Total cost includes
    brokerage + estimated slippage.
    """
    if last_price is None or last_price <= 0:
        return {
            "position_size_vnd": None,
            "estimated_quantity": None,
            "estimated_total_cost": None,
        }

    caps: list[float] = [float(MAX_POSITION_VND)]
    if total_equity is not None and total_equity > 0:
        caps.append(total_equity * EQUITY_PCT_PER_RECO)
    if avg_value_20d is not None and avg_value_20d > 0:
        caps.append(avg_value_20d * MAX_ADV_PCT)

    position_size_vnd = min(caps)
    if position_size_vnd <= 0:
        return {
            "position_size_vnd": 0,
            "estimated_quantity": 0,
            "estimated_total_cost": 0,
        }

    raw_qty = position_size_vnd / last_price
    # Round DOWN to whole lots to avoid odd-lot rejections.
    quantity = int(math.floor(raw_qty / LOT_SIZE) * LOT_SIZE)
    actual_notional = quantity * last_price
    total_cost = actual_notional * (1 + BROKERAGE_RATE + SLIPPAGE_RATE)

    return {
        "position_size_vnd": int(round(position_size_vnd)),
        "estimated_quantity": quantity,
        "estimated_total_cost": int(round(total_cost)),
    }


def build_reasons(
    scores: RecommendationScores | dict[str, Any],
    trend_label: str,
    signals: list[str],
    action: RecommendationAction,
) -> list[str]:
    """At least three codes — top-2 dominant scores + one confirming signal.

    Codes are stable strings the frontend can localise.
    """
    if isinstance(scores, dict):
        score_map = {k: v for k, v in scores.items() if isinstance(v, (int, float))}
    else:
        score_map = {
            "trend": scores.trend,
            "momentum": scores.momentum,
            "volume": scores.volume,
            "liquidity": scores.liquidity,
            "risk_inverse": scores.risk_inverse,
            "market_regime": scores.market_regime,
            "portfolio_fit": scores.portfolio_fit,
        }

    reasons: list[str] = []
    ranked = sorted(score_map.items(), key=lambda kv: kv[1], reverse=True)
    for name, value in ranked[:2]:
        reasons.append(f"{name.upper()}_SCORE_{int(round(value))}")

    if trend_label == "UPTREND":
        reasons.append("TREND_UPTREND_CONFIRMED")
    elif trend_label == "DOWNTREND":
        reasons.append("TREND_DOWNTREND_CONFIRMED")
    elif trend_label == "SIDEWAYS":
        reasons.append("TREND_SIDEWAYS")

    for sig in signals:
        if sig in {"BREAKOUT_20D", "VOLUME_SPIKE", "PRICE_ABOVE_MA20", "MA20_ABOVE_MA50"}:
            reasons.append(f"SIGNAL_{sig}")
            break

    reasons.append(f"ACTION_{action}")
    return reasons


# ── Main entrypoint ─────────────────────────────────────────────────────────


def _confidence_from_score(final_score: int) -> float:
    """Map 0..100 → 0..1. Linear for Phase 1."""
    return round(max(0.0, min(1.0, final_score / 100.0)), 4)


def _resolve_held_weight(
    symbol: str, portfolio_positions: list[Any] | None
) -> float | None:
    """Return the held weight (as a fraction) if symbol is in the portfolio."""
    if not portfolio_positions:
        return None
    target = symbol.upper()
    for pos in portfolio_positions:
        sym = (
            getattr(pos, "symbol", None)
            or (pos.get("symbol") if isinstance(pos, dict) else None)
            or ""
        )
        if str(sym).upper() != target:
            continue
        weight = (
            getattr(pos, "weight", None)
            if not isinstance(pos, dict)
            else pos.get("weight")
        )
        return float(weight) if weight is not None else 0.0
    return None


def generate_recommendation(
    symbol: str,
    profile: RecommendationProfile,
    horizon: RecommendationHorizon,
    bars: list[OHLCVBar],
    latest_quote: Quote | None,
    vnindex_bars: list[OHLCVBar] | None = None,
    portfolio_positions: list[Any] | None = None,
    total_equity: float | None = None,
) -> RecommendationResult:
    """End-to-end engine orchestration. Pure; guardrails applied separately."""

    indicators = scanner_service.compute_indicators(bars)
    last_close = bars[-1].close if bars else None
    last_price = (
        latest_quote.price if latest_quote is not None else last_close
    )
    signals = scanner_service.derive_signals(indicators, last_close)
    base_scores = scanner_service.compute_scores(
        indicators, signals, last_close=last_close
    )
    trend_label = scanner_service.classify_trend(indicators, last_close)

    market_regime = compute_market_regime(vnindex_bars)
    portfolio_fit = compute_portfolio_fit(symbol, portfolio_positions)
    held_weight = _resolve_held_weight(symbol, portfolio_positions)
    held_weight_pct = held_weight * 100.0 if held_weight is not None else None

    scores_dict: dict[str, float | int | None] = {
        "trend": base_scores.trend,
        "momentum": base_scores.momentum,
        "volume": base_scores.volume,
        "liquidity": base_scores.liquidity,
        "risk_inverse": 100 - base_scores.risk,
        "market_regime": market_regime,
        "portfolio_fit": portfolio_fit,
        "ml_probability": None,  # Phase 1: ML disabled
    }

    weights = PROFILE_WEIGHTS.get(profile, PROFILE_WEIGHTS["short_aggressive"])
    final_score = compute_final_score(scores_dict, weights)

    action = derive_action(
        profile=profile,
        horizon=horizon,
        final_score=final_score,
        trend_label=trend_label,
        momentum_score=base_scores.momentum,
        signals=signals,
        portfolio_weight_pct=held_weight_pct,
    )

    entry = compute_entry_zone(last_price, horizon)
    stop = compute_stop_loss(last_price, indicators.atr14, horizon)
    tps = compute_take_profit(last_price, indicators.atr14, horizon)
    sizing = compute_position_sizing(
        last_price=last_price,
        total_equity=total_equity,
        avg_value_20d=indicators.avg_value_20d,
    )

    scores_model = RecommendationScores(
        trend=base_scores.trend,
        momentum=base_scores.momentum,
        volume=base_scores.volume,
        liquidity=base_scores.liquidity,
        risk=base_scores.risk,
        risk_inverse=100 - base_scores.risk,
        market_regime=market_regime,
        portfolio_fit=portfolio_fit,
        ml_probability=None,
    )

    reasons = build_reasons(scores_model, trend_label, signals, action)

    warnings: list[str] = []
    if not bars:
        warnings.append("no_bars")
    if indicators.atr14 is None:
        warnings.append("atr_unavailable_pct_stops_used")
    if latest_quote is not None and latest_quote.stale:
        warnings.append("stale_quote")

    if latest_quote is not None and isinstance(latest_quote.ts, datetime):
        as_of = latest_quote.ts
    elif bars and isinstance(bars[-1].ts, datetime):
        as_of = bars[-1].ts
    else:
        as_of = datetime.now(UTC)

    return RecommendationResult(
        symbol=symbol.upper(),
        profile=profile,
        horizon=horizon,
        action=action,
        status="VALID",
        confidence=_confidence_from_score(final_score),
        final_score=final_score,
        scores=scores_model,
        last_price=last_price,
        entry_zone_low=entry[0] if entry else None,
        entry_zone_high=entry[1] if entry else None,
        stop_loss=stop,
        take_profit_1=tps[0] if tps else None,
        take_profit_2=tps[1] if tps else None,
        position_size_vnd=sizing["position_size_vnd"],
        estimated_quantity=sizing["estimated_quantity"],
        estimated_total_cost=sizing["estimated_total_cost"],
        trend=trend_label,
        signals=signals,
        reasons=reasons,
        warnings=warnings,
        as_of=as_of.isoformat() if isinstance(as_of, datetime) else str(as_of),
        avg_value_20d=indicators.avg_value_20d,
    )
