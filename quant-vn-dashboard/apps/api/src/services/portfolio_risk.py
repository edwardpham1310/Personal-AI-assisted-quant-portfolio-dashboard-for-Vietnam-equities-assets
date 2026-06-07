"""Pure portfolio risk-score model (read-only analytics).

This is NOT trading risk (see ``risk_guardrails`` / ``guardrails_v2`` /
``auto_trade_risk`` for the order-gating guardrails). It produces an
explainable 0–100 portfolio risk score from data the dashboard already has:

  * concentration  — Herfindahl index of position market-value weights
  * cash_buffer    — how far cash is below a target buffer
  * regime         — equity exposure × market-regime risk factor
  * drawdown       — max peak-to-trough of NAV snapshots
  * volatility     — annualized stdev of NAV daily returns
  * liquidity      — UNAVAILABLE (needs an ADV baseline; TODO(adv-baseline))

Partial-aware: the overall score is the weighted mean of the AVAILABLE
components only (weights renormalized). Nothing is fabricated — a component
that lacks data reports ``available=False`` with a ``reason``. All thresholds
are injected via ``RiskParams`` (from config), never hardcoded here.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from schemas.portfolio import RiskComponent, RiskScoreResult

# Market-regime → risk factor (0 = calm, 1 = max). NO_DATA/unknown → component
# is treated as unavailable rather than guessed.
_REGIME_RISK: dict[str, float] = {
    "UPTREND": 0.3,
    "MIXED": 0.6,
    "DOWNTREND": 1.0,
}

# Score-band cut points (bucket labels only — not financial constants).
_BANDS = ((25.0, "low"), (50.0, "moderate"), (75.0, "elevated"))


@dataclass(frozen=True)
class RiskParams:
    w_concentration: float
    w_cash_buffer: float
    w_regime: float
    w_drawdown: float
    w_volatility: float
    target_cash_ratio: float
    drawdown_cap: float
    volatility_cap: float
    min_history_points: int
    trading_days_per_year: int


def _band(score: float) -> str:
    for cutoff, label in _BANDS:
        if score < cutoff:
            return label
    return "high"


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _concentration(weights: list[float], params: RiskParams) -> RiskComponent:
    priced = [w for w in weights if w and w > 0]
    if not priced:
        return RiskComponent(
            key="concentration", label="Concentration", available=False,
            weight=params.w_concentration, reason="no_priced_positions",
        )
    hhi = sum(w * w for w in priced)  # 1/N (diversified) .. 1 (single name)
    return RiskComponent(
        key="concentration", label="Concentration", available=True,
        score=round(_clamp01(hhi) * 100, 1), weight=params.w_concentration,
        detail=f"HHI {hhi:.2f} across {len(priced)} priced position(s)",
    )


def _cash_buffer(cash: float, total_equity: float, params: RiskParams) -> RiskComponent:
    if total_equity <= 0:
        return RiskComponent(
            key="cash_buffer", label="Cash buffer", available=False,
            weight=params.w_cash_buffer, reason="no_equity",
        )
    cash_ratio = max(0.0, cash / total_equity)
    target = params.target_cash_ratio if params.target_cash_ratio > 0 else 1.0
    # Less cash than target → more risk.
    score = (1.0 - _clamp01(cash_ratio / target)) * 100
    return RiskComponent(
        key="cash_buffer", label="Cash buffer", available=True,
        score=round(score, 1), weight=params.w_cash_buffer,
        detail=f"{cash_ratio * 100:.1f}% cash vs {target * 100:.0f}% target",
    )


def _regime(
    total_market_value: float, total_equity: float, regime_label: str | None,
    params: RiskParams,
) -> RiskComponent:
    factor = _REGIME_RISK.get((regime_label or "").upper()) if regime_label else None
    if factor is None or total_equity <= 0:
        return RiskComponent(
            key="regime", label="Regime exposure", available=False,
            weight=params.w_regime,
            reason="regime_unavailable" if factor is None else "no_equity",
        )
    exposure = _clamp01(total_market_value / total_equity)
    return RiskComponent(
        key="regime", label="Regime exposure", available=True,
        score=round(exposure * factor * 100, 1), weight=params.w_regime,
        detail=f"{exposure * 100:.0f}% equity exposure in {regime_label} regime",
    )


def _drawdown(nav: list[float], params: RiskParams) -> RiskComponent:
    if len(nav) < params.min_history_points:
        return RiskComponent(
            key="drawdown", label="Drawdown", available=False,
            weight=params.w_drawdown, reason="insufficient_history",
        )
    peak = nav[0]
    max_dd = 0.0
    for v in nav:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)
    cap = params.drawdown_cap if params.drawdown_cap > 0 else 1.0
    return RiskComponent(
        key="drawdown", label="Drawdown", available=True,
        score=round(_clamp01(max_dd / cap) * 100, 1), weight=params.w_drawdown,
        detail=f"max drawdown {max_dd * 100:.1f}% over {len(nav)} snapshots",
    )


def _volatility(nav: list[float], params: RiskParams) -> RiskComponent:
    if len(nav) < params.min_history_points:
        return RiskComponent(
            key="volatility", label="Volatility", available=False,
            weight=params.w_volatility, reason="insufficient_history",
        )
    returns = [
        (nav[i] / nav[i - 1] - 1.0)
        for i in range(1, len(nav))
        if nav[i - 1] > 0
    ]
    if len(returns) < 2:
        return RiskComponent(
            key="volatility", label="Volatility", available=False,
            weight=params.w_volatility, reason="insufficient_history",
        )
    ann_vol = statistics.stdev(returns) * math.sqrt(params.trading_days_per_year)
    cap = params.volatility_cap if params.volatility_cap > 0 else 1.0
    return RiskComponent(
        key="volatility", label="Volatility", available=True,
        score=round(_clamp01(ann_vol / cap) * 100, 1), weight=params.w_volatility,
        detail=f"annualized volatility {ann_vol * 100:.1f}%",
    )


def _liquidity(params: RiskParams) -> RiskComponent:
    # No Average-Daily-Volume baseline is reachable yet (see Phase 2.4).
    return RiskComponent(
        key="liquidity", label="Liquidity", available=False,
        reason="no_adv_baseline",
    )


def compute_risk_score(
    *,
    position_weights: list[float],
    total_market_value: float,
    cash: float,
    total_equity: float,
    regime_label: str | None,
    nav_history: list[float],
    as_of: str | None,
    params: RiskParams,
) -> RiskScoreResult:
    """Build the explainable, partial-aware risk score from real inputs."""
    components = [
        _concentration(position_weights, params),
        _cash_buffer(cash, total_equity, params),
        _regime(total_market_value, total_equity, regime_label, params),
        _drawdown(nav_history, params),
        _volatility(nav_history, params),
        _liquidity(params),
    ]

    available = [c for c in components if c.available and c.score is not None]
    weight_sum = sum(c.weight for c in available)
    if not available or weight_sum <= 0:
        return RiskScoreResult(
            score=None, band="unavailable", components=components,
            available_count=len(available), total_count=len(components), as_of=as_of,
        )

    overall = sum((c.score or 0.0) * c.weight for c in available) / weight_sum
    overall = round(overall, 1)
    return RiskScoreResult(
        score=overall, band=_band(overall), components=components,
        available_count=len(available), total_count=len(components), as_of=as_of,
    )
