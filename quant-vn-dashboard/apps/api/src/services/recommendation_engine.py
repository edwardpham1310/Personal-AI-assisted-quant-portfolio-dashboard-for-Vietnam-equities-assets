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

from schemas.fundamentals import Fundamentals
from schemas.market import OHLCVBar, Quote
from schemas.recommendation import (
    ChartContext,
    DataStatus,
    RecommendationAction,
    RecommendationHorizon,
    RecommendationProfile,
    RecommendationResult,
    RecommendationScores,
)
from services import scanner as scanner_service
from services.guardrails_v2 import (
    GuardrailEvidenceV2,
    GuardrailMode,
)
from services.guardrails_v2 import (
    evaluate as evaluate_v2,
)

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
# Phase 2.B: BUY threshold raised from 70 → 75 to align with the new
# strict guardrail pipeline. Increases precision at the cost of recall.
ACTION_BUY_THRESHOLD = 75           # >=75 + UPTREND + supporting signal => BUY_CANDIDATE
ACTION_WATCH_THRESHOLD = 55         # >=55 in UPTREND/SIDEWAYS => WATCH
ACTION_REDUCE_THRESHOLD = 40        # <40 while held => REDUCE
ACTION_SELL_THRESHOLD = 30          # <30 while held + DOWNTREND => SELL_CANDIDATE

# Phase 2.B: MA200 trend insurance + minimum history for BUY_CANDIDATE.
REQUIRE_PRICE_ABOVE_MA200_FOR_BUY = True
MIN_BARS_FOR_BUY_CANDIDATE = 250

# Position sizing defaults — keep symmetric with risk_guardrails constants.
BROKERAGE_RATE = 0.0015             # 15 bps SSI all-in
SLIPPAGE_RATE = 0.0010              # 10 bps modelled slippage
MAX_POSITION_VND = 50_000_000       # hard cap per recommendation in VND
EQUITY_PCT_PER_RECO = 0.05          # 5% of total equity per recommendation
MAX_ADV_PCT = 0.005                 # 0.5% of avg 20d trading value
LOT_SIZE = 100                      # HOSE/HNX standard lot
# TODO(cost-model): BROKERAGE_RATE / SLIPPAGE_RATE / LOT_SIZE are duplicated
#   from services.order_preview (canonical name there: DEFAULT_LOT_SIZE). Values
#   currently match; do NOT consolidate without a refactor that verifies no
#   scoring drift (a fee-schedule change in order_preview must not silently move
#   recommendation scores). order_preview also defines VAT_RATE (10% on
#   brokerage) and SELL_TAX_RATE (0.1% sell-side) that this engine does NOT apply
#   — its cost model understates SELL round-trip cost by ~0.11%.
# TODO(vn-assumptions): settlement T+2, the VN trading calendar/holidays
#   (services.vn_holidays), and corporate-action (div/split/rights) price
#   adjustment are not modelled here. Wire these in before using price-level
#   features for live P&L reconciliation; until then treat outputs as research
#   signals only.

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


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    *,
    price_above_ma200: bool | None = None,
    bars_count: int = 0,
    strict_mode: bool = False,
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

    # Phase 2.B trend insurance: a BUY_CANDIDATE must sit above MA200.
    # When MA200 is unavailable AND strict mode is on, no BUY_CANDIDATE.
    # In relaxed mode (default), unknown MA200 still allows the action
    # because the route layer downgrades when bars_count < 250 (the
    # caller decides — engine just honors what it's told).
    ma200_ok = True
    if REQUIRE_PRICE_ABOVE_MA200_FOR_BUY:
        if price_above_ma200 is False or price_above_ma200 is None and strict_mode:
            ma200_ok = False
    if strict_mode and bars_count < MIN_BARS_FOR_BUY_CANDIDATE:
        ma200_ok = False

    if (
        trend_label == "UPTREND"
        and final_score >= ACTION_BUY_THRESHOLD
        and momentum_score >= 55
        and supporting
        and ma200_ok
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


# Held-position weight (% within holdings) at/above which we flag concentration.
CONCENTRATION_WARN_PCT = 15.0


def _pos_field(pos: Any, key: str) -> Any:
    """Read a field off an EnrichedPosition (attr) or a plain dict."""
    if isinstance(pos, dict):
        return pos.get(key)
    return getattr(pos, key, None)


def _find_position(symbol: str, portfolio_positions: list[Any] | None) -> Any | None:
    if not portfolio_positions:
        return None
    target = symbol.upper()
    for pos in portfolio_positions:
        if str(_pos_field(pos, "symbol") or "").upper() == target:
            return pos
    return None


def _resolve_held_weight(
    symbol: str, portfolio_positions: list[Any] | None
) -> float | None:
    """Return the held weight (as a fraction) if symbol is in the portfolio."""
    pos = _find_position(symbol, portfolio_positions)
    if pos is None:
        return None
    weight = _pos_field(pos, "weight")
    return float(weight) if weight is not None else 0.0


def generate_recommendation(
    symbol: str,
    profile: RecommendationProfile,
    horizon: RecommendationHorizon,
    bars: list[OHLCVBar],
    latest_quote: Quote | None,
    vnindex_bars: list[OHLCVBar] | None = None,
    portfolio_positions: list[Any] | None = None,
    total_equity: float | None = None,
    *,
    strict_mode: bool = False,
) -> RecommendationResult:
    """End-to-end engine orchestration. Pure; guardrails applied separately.

    ``strict_mode`` (Phase 2.B): when True, the engine refuses
    BUY_CANDIDATE without MA200 evidence (bars_count >= 250 AND
    price_above_ma200). The 3-layer guardrail pipeline is run by the
    route layer via ``apply_v2_guardrails`` AFTER this function returns —
    the engine doesn't read fundamentals.
    """

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

    # Feature 7: resolve the actual holding so the result can surface
    # portfolio-aware facts (held quantity / avg cost / weight) to the UI.
    held_position = _find_position(symbol, portfolio_positions)
    is_held = held_position is not None
    held_quantity = _to_float(_pos_field(held_position, "quantity")) if is_held else None
    held_avg_cost = _to_float(_pos_field(held_position, "avg_cost")) if is_held else None
    held_unrealized_pct = (
        _to_float(_pos_field(held_position, "unrealized_pnl_pct")) if is_held else None
    )
    portfolio_note: str | None = None
    if is_held:
        if held_weight_pct is not None and held_weight_pct >= CONCENTRATION_WARN_PCT:
            portfolio_note = (
                f"Already {held_weight_pct:.1f}% of holdings — concentration risk."
            )
        elif held_weight_pct is not None:
            portfolio_note = f"Already held ({held_weight_pct:.1f}% of holdings)."
        else:
            portfolio_note = "Already held."

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
        price_above_ma200=indicators.price_above_ma200,
        bars_count=indicators.bars_count,
        strict_mode=strict_mode,
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
    if indicators.ma200 is None:
        warnings.append("insufficient_history_for_ma200")
    if (
        indicators.price_above_ma200 is False
        and indicators.ma200 is not None
    ):
        warnings.append("price_below_ma200")
    if (
        is_held
        and held_weight_pct is not None
        and held_weight_pct >= CONCENTRATION_WARN_PCT
    ):
        warnings.append("portfolio_concentration")

    if latest_quote is not None and isinstance(latest_quote.ts, datetime):
        as_of = latest_quote.ts
    elif bars and isinstance(bars[-1].ts, datetime):
        as_of = bars[-1].ts
    else:
        as_of = datetime.now(UTC)

    # Phase 2: compute data_status + chart_context so every recommendation
    # carries enough info for the operator to verify the call inline.
    data_status: DataStatus = "FRESH"
    if not bars:
        data_status = "DATA_UNAVAILABLE"
    elif latest_quote is None:
        data_status = "STALE"  # bars are real but no live quote
    elif latest_quote.stale:
        data_status = "STALE"

    chart_ctx = ChartContext(
        timeframe="1d",
        last_candle_time=(
            bars[-1].ts.isoformat()
            if bars and isinstance(bars[-1].ts, datetime)
            else None
        ),
        trend=trend_label,
        ma20=indicators.ma20,
        ma50=indicators.ma50,
        rsi=indicators.rsi14,
        volume_ratio_20d=indicators.volume_ratio_20d,
        atr14=indicators.atr14,
    )

    # Serialise the latest quote for the UI. We use the existing Quote
    # shape (with the optional ceiling/floor/value fields populated by
    # the SSI parser since Phase 2A).
    latest_quote_payload: dict | None = None
    if latest_quote is not None:
        latest_quote_payload = latest_quote.model_dump(mode="json")

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
        vol_cov_20d=indicators.vol_cov_20d,
        consecutive_ceilings=indicators.consecutive_ceilings,
        ma200=indicators.ma200,
        price_above_ma200=indicators.price_above_ma200,
        action_threshold_used=ACTION_BUY_THRESHOLD,
        is_held=is_held,
        held_weight_pct=held_weight_pct,
        held_quantity=held_quantity,
        held_avg_cost=held_avg_cost,
        held_unrealized_pct=held_unrealized_pct,
        portfolio_note=portfolio_note,
        data_status=data_status,
        latest_quote=latest_quote_payload,
        chart_context=chart_ctx,
        # chart_url is set by the route layer (frontend-aware base path).
    )


# ── Phase 2.B: 3-layer guardrail integration ────────────────────────────────


def apply_v2_guardrails(
    rec: RecommendationResult,
    *,
    fundamentals: Fundamentals | None,
    mode: GuardrailMode = "strict",
    min_price_threshold: float | None = None,
) -> RecommendationResult:
    """Run the 3-layer guardrail pipeline and downgrade ``rec`` in place
    if any layer rejects.

    Side effects on the returned result (copy of ``rec``):
      * If REJECTED: ``action='REJECTED'``, ``status='REJECTED'``,
        ``confidence=0.0``, rejection_reasons populated, warnings
        extended, ``guardrail_status='REJECTED'``.
      * If PASS: ``guardrail_status='PASS'`` and the layer breakdown is
        still surfaced for operator visibility.

    Also enforces strict-mode BUY_CANDIDATE downgrade when bars_count
    is < 250 or price is not above MA200 — even if Layer 3 didn't
    reject. This is the "MA200 trend insurance" rule.
    """
    latest_quote_payload = rec.latest_quote or {}
    ceiling_price = latest_quote_payload.get("ceiling_price")
    floor_price = latest_quote_payload.get("floor_price")
    is_vn100 = fundamentals.is_vn100 if fundamentals is not None else None

    # Derive market_cap if we have listed_share + last_price and the
    # fundamentals provider didn't supply it directly.
    derived_market_cap: float | None = None
    if (
        fundamentals is not None
        and fundamentals.market_cap is None
        and fundamentals.listed_share is not None
        and rec.last_price is not None
    ):
        derived_market_cap = float(fundamentals.listed_share) * float(rec.last_price)
    market_cap = (
        fundamentals.market_cap
        if (fundamentals is not None and fundamentals.market_cap is not None)
        else derived_market_cap
    )

    ev = GuardrailEvidenceV2(
        symbol=rec.symbol,
        mode=mode,
        avg_value_20d=rec.avg_value_20d,
        market_cap=market_cap,
        last_price=rec.last_price,
        min_price_threshold=min_price_threshold,
        fundamentals=fundamentals,
        vol_cov_20d=rec.vol_cov_20d,
        consecutive_ceilings=rec.consecutive_ceilings,
        is_vn100=is_vn100,
        ceiling_price=ceiling_price,
        floor_price=floor_price,
        ma200=rec.ma200,
        # bars_count is consumed by ``derive_action`` upstream; the
        # 3-layer pipeline only reads ``ma200`` for its WARN code so 0
        # here is correct and harmless.
        bars_count=0,
    )

    report = evaluate_v2(ev)

    layer_payload = [
        {
            "layer": layer.layer,
            "status": layer.status,
            "rejection_reasons": list(layer.rejection_reasons),
            "warnings": list(layer.warnings),
        }
        for layer in report.layers
    ]

    new_warnings = list(rec.warnings)
    for w in report.warnings:
        if w not in new_warnings:
            new_warnings.append(w)

    new_reasons = list(rec.reasons)
    rejection_reasons = list(report.rejection_reasons)

    if report.is_rejected():
        for r in rejection_reasons:
            tag = f"GUARDRAIL_REJECT_{r.upper()}"
            if tag not in new_reasons:
                new_reasons.append(tag)
        return rec.model_copy(
            update={
                "action": "REJECTED",
                "status": "REJECTED",
                "confidence": 0.0,
                "warnings": new_warnings,
                "reasons": new_reasons,
                "rejection_reasons": rejection_reasons,
                "guardrail_status": "REJECTED",
                "guardrail_layer_results": layer_payload,
                "fundamental_data_status": report.fundamental_data_status,
            }
        )

    # PASS — but the layer 3 warnings still appear in the output for
    # operator visibility (e.g. "missing_consecutive_ceilings").
    return rec.model_copy(
        update={
            "warnings": new_warnings,
            "rejection_reasons": [],
            "guardrail_status": "PASS",
            "guardrail_layer_results": layer_payload,
            "fundamental_data_status": report.fundamental_data_status,
        }
    )
