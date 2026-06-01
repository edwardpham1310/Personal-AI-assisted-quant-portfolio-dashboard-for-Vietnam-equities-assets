"""Phase 2.B strict 3-layer risk guardrail pipeline.

Coexists with ``services.risk_guardrails`` (the Phase-1 flat pipeline);
the recommendation engine calls this module when the new fundamentals +
anti-manipulation gates are wired in. Every check is a pure function;
no I/O.

Pipeline order is load-bearing:

  Layer 1 — Anti-Penny / Size & Liquidity Gate
  Layer 2 — Fundamental Quality Gate
  Layer 3 — Anti-Manipulation / Anomaly Gate

A REJECT in any layer marks the final status REJECTED. Downstream
layers still run for diagnostic visibility but cannot lift a REJECT.

Every label is a **research signal · not financial advice · no orders
placed**. Anti-manipulation wording avoids accusatory phrasing —
"potential abnormal volume pattern" rather than "wash trading
confirmed".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from schemas.fundamentals import (
    Fundamentals,
    FundamentalDataStatus,
    compute_data_status,
)


# ── Thresholds ──────────────────────────────────────────────────────────────


MIN_LIQUIDITY_VND = 20_000_000_000           # 20B VND avg 20d trading value
MIN_MARKET_CAP = 3_000_000_000_000           # 3T VND market cap
MIN_ROE_PCT = 12.0                            # ROE % (e.g. 12.0 means 12 %)
VOL_COV_MIN = 0.1                             # below = potential abnormal pattern
CONSECUTIVE_CEILINGS_MAX_NON_VN100 = 3        # > 3 + not VN100 = unbacked pump
MIN_BARS_FOR_BUY_CANDIDATE = 250
MA200_MIN_BARS = 200                          # MA200 needs ≥200 completed bars


GuardrailMode = Literal["strict", "balanced", "relaxed"]

# ── Reason code registry ───────────────────────────────────────────────────
#
# Single source of truth so tests + frontend + audit log can never drift.

# Layer 1
R1_MISSING_AVG_VALUE_20D = "missing_avg_value_20d"
R1_LOW_LIQUIDITY = "low_liquidity"
R1_MISSING_MARKET_CAP = "missing_market_cap"
R1_MARKET_CAP_BELOW_THRESHOLD = "market_cap_below_threshold"
R1_MIN_PRICE = "min_price_below_threshold"

# Layer 2
R2_MISSING_ROE = "missing_roe"
R2_INSUFFICIENT_ROE = "insufficient_roe"
R2_MISSING_NET_PROFIT = "missing_net_profit_last_4_quarters"
R2_NEGATIVE_QUARTERLY_PROFIT = "negative_quarterly_profit"
R2_MISSING_AUDIT_OPINION = "missing_audit_opinion"
R2_UNCLEAN_AUDIT_OPINION = "unclean_audit_opinion"
R2_MISSING_FUNDAMENTAL_DATA = "missing_fundamental_data"

# Layer 3
R3_MISSING_VOL_COV = "missing_vol_cov_20d"
R3_POTENTIAL_WASH_TRADING = "potential_wash_trading"
R3_MISSING_CONSECUTIVE_CEILINGS = "missing_consecutive_ceilings"
R3_UNBACKED_EXTREME_PUMP = "unbacked_extreme_pump"
R3_MISSING_PRICE_BAND = "missing_price_band_data"
R3_PRICE_OUTSIDE_TRADING_BAND = "price_outside_trading_band"
R3_INSUFFICIENT_HISTORY_FOR_MA200 = "insufficient_history_for_ma200"
R3_PRICE_BELOW_MA200 = "price_below_ma200"


CLEAN_AUDIT_OPINIONS: frozenset[str] = frozenset({"UNQUALIFIED"})


# ── Data shape ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GuardrailEvidenceV2:
    """All inputs the 3-layer pipeline needs. Assembled by the route
    layer from scanner indicators + fundamentals provider + latest
    quote. Every field is optional so the pipeline can still run on
    partial data — the gate codes communicate what was missing."""

    symbol: str
    mode: GuardrailMode = "strict"

    # Layer 1 inputs
    avg_value_20d: float | None = None
    market_cap: float | None = None
    last_price: float | None = None
    min_price_threshold: float | None = None  # operator-configurable

    # Layer 2 inputs
    fundamentals: Fundamentals | None = None

    # Layer 3 inputs
    vol_cov_20d: float | None = None
    consecutive_ceilings: int | None = None
    is_vn100: bool | None = None
    ceiling_price: float | None = None
    floor_price: float | None = None

    # MA200 cross-cutting (used by recommendation engine, not Layer 3
    # rejection, but surfaced as a warning code).
    ma200: float | None = None
    bars_count: int = 0


@dataclass
class LayerResult:
    """Per-layer outcome surfaced in the recommendation response."""

    layer: str
    status: Literal["PASS", "REJECTED"]
    rejection_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class GuardrailReport:
    """Aggregate outcome of the 3-layer pipeline."""

    status: Literal["PASS", "REJECTED"]
    layers: list[LayerResult]
    rejection_reasons: list[str]
    warnings: list[str]
    fundamental_data_status: FundamentalDataStatus
    mode: GuardrailMode

    def is_rejected(self) -> bool:
        return self.status == "REJECTED"


# ── Layer implementations ──────────────────────────────────────────────────


def evaluate_layer1_size_liquidity(ev: GuardrailEvidenceV2) -> LayerResult:
    """Anti-Penny / Size & Liquidity Gate."""
    rejects: list[str] = []
    warns: list[str] = []

    if ev.avg_value_20d is None:
        if ev.mode == "strict":
            rejects.append(R1_MISSING_AVG_VALUE_20D)
        else:
            warns.append(R1_MISSING_AVG_VALUE_20D)
    elif ev.avg_value_20d < MIN_LIQUIDITY_VND:
        rejects.append(R1_LOW_LIQUIDITY)

    if ev.market_cap is None:
        if ev.mode == "strict":
            rejects.append(R1_MISSING_MARKET_CAP)
        else:
            warns.append(R1_MISSING_MARKET_CAP)
    elif ev.market_cap < MIN_MARKET_CAP:
        rejects.append(R1_MARKET_CAP_BELOW_THRESHOLD)

    if ev.min_price_threshold is not None and ev.last_price is not None:
        if ev.last_price < ev.min_price_threshold:
            rejects.append(R1_MIN_PRICE)

    return LayerResult(
        layer="size_liquidity",
        status="REJECTED" if rejects else "PASS",
        rejection_reasons=rejects,
        warnings=warns,
    )


def evaluate_layer2_fundamentals(ev: GuardrailEvidenceV2) -> LayerResult:
    """Fundamental Quality Gate.

    Reads ROE, net_profit_last_4_quarters, audit_opinion off the
    ``Fundamentals`` row. Each missing field rejects in strict mode and
    warns in relaxed mode. ``balanced`` behaves like ``strict`` for
    fundamentals because half-known fundamentals are worse than no
    fundamentals (cherry-picking risk).
    """
    rejects: list[str] = []
    warns: list[str] = []

    f = ev.fundamentals
    strict = ev.mode in ("strict", "balanced")

    if f is None:
        # No fundamentals row at all.
        if strict:
            rejects.append(R2_MISSING_FUNDAMENTAL_DATA)
        else:
            warns.append(R2_MISSING_FUNDAMENTAL_DATA)
        return LayerResult(
            layer="fundamentals",
            status="REJECTED" if rejects else "PASS",
            rejection_reasons=rejects,
            warnings=warns,
        )

    # ROE
    if f.roe is None:
        if strict:
            rejects.append(R2_MISSING_ROE)
        else:
            warns.append(R2_MISSING_ROE)
    elif f.roe < MIN_ROE_PCT:
        rejects.append(R2_INSUFFICIENT_ROE)

    # Net profit last 4 quarters
    npq = f.net_profit_last_4_quarters
    if npq is None or len(npq) < 4:
        if strict:
            rejects.append(R2_MISSING_NET_PROFIT)
        else:
            warns.append(R2_MISSING_NET_PROFIT)
    else:
        if any(v <= 0 for v in npq):
            rejects.append(R2_NEGATIVE_QUARTERLY_PROFIT)

    # Audit opinion
    if f.audit_opinion is None:
        if strict:
            rejects.append(R2_MISSING_AUDIT_OPINION)
        else:
            warns.append(R2_MISSING_AUDIT_OPINION)
    elif f.audit_opinion not in CLEAN_AUDIT_OPINIONS:
        rejects.append(R2_UNCLEAN_AUDIT_OPINION)

    return LayerResult(
        layer="fundamentals",
        status="REJECTED" if rejects else "PASS",
        rejection_reasons=rejects,
        warnings=warns,
    )


def evaluate_layer3_anti_manipulation(ev: GuardrailEvidenceV2) -> LayerResult:
    """Anti-Manipulation / Anomaly Gate.

    Heuristic — codes describe what was observed, not a manipulation
    accusation. The dashboard surfaces wording like "potential
    abnormal volume pattern".
    """
    rejects: list[str] = []
    warns: list[str] = []

    # 1. Volume CoV → wash-trading-style heuristic.
    if ev.vol_cov_20d is None:
        warns.append(R3_MISSING_VOL_COV)
    elif ev.vol_cov_20d < VOL_COV_MIN:
        rejects.append(R3_POTENTIAL_WASH_TRADING)

    # 2. Consecutive ceilings → unbacked extreme pump.
    if ev.consecutive_ceilings is None:
        warns.append(R3_MISSING_CONSECUTIVE_CEILINGS)
    elif (
        ev.consecutive_ceilings > CONSECUTIVE_CEILINGS_MAX_NON_VN100
        and ev.is_vn100 is not True
    ):
        # In balanced mode, this is a WARN; strict rejects.
        if ev.mode == "strict":
            rejects.append(R3_UNBACKED_EXTREME_PUMP)
        else:
            warns.append(R3_UNBACKED_EXTREME_PUMP)

    # 3. Price band check.
    if ev.ceiling_price is None and ev.floor_price is None:
        warns.append(R3_MISSING_PRICE_BAND)
    elif ev.last_price is not None:
        if (
            ev.ceiling_price is not None
            and ev.last_price > ev.ceiling_price * 1.0001
        ):
            rejects.append(R3_PRICE_OUTSIDE_TRADING_BAND)
        elif (
            ev.floor_price is not None
            and ev.last_price < ev.floor_price * 0.9999
        ):
            rejects.append(R3_PRICE_OUTSIDE_TRADING_BAND)

    # 4. MA200 history availability surfaces as a WARN here (not a
    #    Layer-3 REJECT — the recommendation engine downgrades the
    #    action separately).
    if ev.ma200 is None:
        warns.append(R3_INSUFFICIENT_HISTORY_FOR_MA200)

    return LayerResult(
        layer="anti_manipulation",
        status="REJECTED" if rejects else "PASS",
        rejection_reasons=rejects,
        warnings=warns,
    )


# ── Orchestration ──────────────────────────────────────────────────────────


def evaluate(ev: GuardrailEvidenceV2) -> GuardrailReport:
    """Run all three layers in order and aggregate the report.

    Downstream layers still run after an upstream REJECT so the
    operator sees the full diagnostic picture, but the final status
    stays REJECTED.
    """
    l1 = evaluate_layer1_size_liquidity(ev)
    l2 = evaluate_layer2_fundamentals(ev)
    l3 = evaluate_layer3_anti_manipulation(ev)

    layers = [l1, l2, l3]
    rejection_reasons: list[str] = []
    warnings: list[str] = []
    for layer in layers:
        rejection_reasons.extend(layer.rejection_reasons)
        warnings.extend(layer.warnings)
    status: Literal["PASS", "REJECTED"] = (
        "REJECTED" if any(l.status == "REJECTED" for l in layers) else "PASS"
    )
    return GuardrailReport(
        status=status,
        layers=layers,
        rejection_reasons=rejection_reasons,
        warnings=warnings,
        fundamental_data_status=compute_data_status(ev.fundamentals),
        mode=ev.mode,
    )
