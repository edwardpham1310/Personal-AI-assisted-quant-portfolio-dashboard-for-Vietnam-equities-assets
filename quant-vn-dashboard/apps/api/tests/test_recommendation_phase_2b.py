"""Tests for the Phase 2.B recommendation engine changes:

* ACTION_BUY_THRESHOLD raised to 75.
* MA200 trend insurance + strict-mode minimum bars.
* ``apply_v2_guardrails`` produces the hard-override REJECTED action
  and surfaces the layer breakdown.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from schemas.fundamentals import Fundamentals
from schemas.market import OHLCVBar, Quote
from services import recommendation_engine
from services.recommendation_engine import (
    ACTION_BUY_THRESHOLD,
    apply_v2_guardrails,
    generate_recommendation,
)


def _bars(closes: list[float], *, volumes: list[float] | None = None) -> list[OHLCVBar]:
    """Synthetic bars sized to clear the Phase 2.B 20B-VND liquidity gate
    AND the 0.1 volume-CoV floor (so Layer 3 doesn't flag healthy
    fixtures as potential wash trading).

    Default daily value ≈ close × 3e9 with ±33% bar-to-bar variance
    (CoV around 0.3) — well above the 0.1 anomaly floor.
    """
    start = datetime(2025, 1, 2, tzinfo=timezone.utc)
    if volumes is None:
        base = 3_000_000_000.0
        # Multiplier cycle gives population std/mean ≈ 0.3 over any 20-bar window.
        vols = [
            base * (1.0 + 0.45 * ((i % 5) - 2) / 2.0) for i in range(len(closes))
        ]
    else:
        vols = volumes
    return [
        OHLCVBar(
            symbol="TEST",
            ts=start + timedelta(days=i),
            open=c,
            high=c * 1.02,
            low=c * 0.98,
            close=c,
            volume=vols[i],
            value=c * vols[i],
        )
        for i, c in enumerate(closes)
    ]


def _quote(price: float, *, stale: bool = False) -> Quote:
    return Quote(
        symbol="TEST",
        price=price,
        ts=datetime(2025, 12, 31, tzinfo=timezone.utc),
        stale=stale,
        source="ssi",
        ceiling_price=price * 1.07,
        floor_price=price * 0.93,
    )


def _uptrend_bars(n: int = 260, start: float = 10.0) -> list[OHLCVBar]:
    """Smooth uptrend so the engine's trend classifier returns UPTREND
    and final_score is comfortably above the BUY threshold."""
    return _bars([start + i * 0.05 for i in range(n)])


def _strong_uptrend_quote() -> Quote:
    return _quote(10.0 + 259 * 0.05)


# ── ACTION_BUY_THRESHOLD = 75 ─────────────────────────────────────────────


def test_action_buy_threshold_is_75() -> None:
    assert ACTION_BUY_THRESHOLD == 75


def test_engine_emits_action_threshold_in_result() -> None:
    rec = generate_recommendation(
        symbol="TEST",
        profile="short_aggressive",
        horizon="SHORT_1W",
        bars=_uptrend_bars(),
        latest_quote=_strong_uptrend_quote(),
    )
    assert rec.action_threshold_used == 75


# ── MA200 trend insurance ──────────────────────────────────────────────────


def test_no_buy_candidate_when_price_below_ma200() -> None:
    """Build bars where the latest close is BELOW the MA200 average.
    Even with a strong score, derive_action must refuse BUY_CANDIDATE."""
    closes = [100.0] * 200 + [50.0]  # MA200 ~ 100 → close 50 is below
    bars = _bars(closes)
    quote = _quote(50.0)
    rec = generate_recommendation(
        symbol="TEST",
        profile="short_aggressive",
        horizon="SHORT_1W",
        bars=bars,
        latest_quote=quote,
    )
    assert rec.action != "BUY_CANDIDATE"
    assert "price_below_ma200" in rec.warnings


def test_strict_mode_blocks_buy_when_bars_lt_250() -> None:
    """Strict mode: <250 bars → no BUY_CANDIDATE even with strong score
    and price above MA200."""
    bars = _uptrend_bars(n=240)  # MA200 computable; bars < 250
    rec = generate_recommendation(
        symbol="TEST",
        profile="short_aggressive",
        horizon="SHORT_1W",
        bars=bars,
        latest_quote=_quote(10.0 + 239 * 0.05),
        strict_mode=True,
    )
    assert rec.action != "BUY_CANDIDATE"


def test_strict_mode_blocks_buy_when_ma200_unavailable() -> None:
    """Strict mode: MA200 None (bars < 200) → no BUY_CANDIDATE."""
    bars = _uptrend_bars(n=150)
    rec = generate_recommendation(
        symbol="TEST",
        profile="short_aggressive",
        horizon="SHORT_1W",
        bars=bars,
        latest_quote=_quote(10.0 + 149 * 0.05),
        strict_mode=True,
    )
    assert rec.action != "BUY_CANDIDATE"
    assert "insufficient_history_for_ma200" in rec.warnings


def test_engine_surfaces_ma200_and_price_above_ma200() -> None:
    rec = generate_recommendation(
        symbol="TEST",
        profile="short_aggressive",
        horizon="SHORT_1W",
        bars=_uptrend_bars(),
        latest_quote=_strong_uptrend_quote(),
    )
    assert rec.ma200 is not None
    assert rec.price_above_ma200 is True


# ── apply_v2_guardrails — hard override ────────────────────────────────────


def _clean_fundamentals() -> Fundamentals:
    return Fundamentals(
        symbol="TEST",
        market_cap=5_000_000_000_000,
        roe=18.0,
        net_profit_last_4_quarters=[1e9, 1.1e9, 1.2e9, 1.3e9],
        audit_opinion="UNQUALIFIED",
        is_vn100=True,  # avoid pump-rule edge cases
    )


def _baseline_rec():
    return generate_recommendation(
        symbol="TEST",
        profile="short_aggressive",
        horizon="SHORT_1W",
        bars=_uptrend_bars(),
        latest_quote=_strong_uptrend_quote(),
    )


def test_apply_v2_guardrails_pass_clean_data() -> None:
    rec = _baseline_rec()
    out = apply_v2_guardrails(rec, fundamentals=_clean_fundamentals(), mode="strict")
    assert out.guardrail_status == "PASS"
    assert out.action == rec.action  # unchanged
    assert out.fundamental_data_status == "FUNDAMENTAL_DATA_AVAILABLE"
    assert len(out.guardrail_layer_results) == 3


def test_apply_v2_guardrails_reject_low_liquidity() -> None:
    rec = _baseline_rec().model_copy(update={"avg_value_20d": 1_000.0})
    out = apply_v2_guardrails(rec, fundamentals=_clean_fundamentals(), mode="strict")
    assert out.guardrail_status == "REJECTED"
    assert out.action == "REJECTED"
    assert out.status == "REJECTED"
    assert out.confidence == 0.0
    assert "low_liquidity" in out.rejection_reasons


def test_apply_v2_guardrails_reject_insufficient_roe() -> None:
    rec = _baseline_rec()
    weak = _clean_fundamentals().model_copy(update={"roe": 5.0})
    out = apply_v2_guardrails(rec, fundamentals=weak, mode="strict")
    assert out.guardrail_status == "REJECTED"
    assert "insufficient_roe" in out.rejection_reasons


def test_apply_v2_guardrails_reject_missing_fundamentals_strict() -> None:
    rec = _baseline_rec()
    out = apply_v2_guardrails(rec, fundamentals=None, mode="strict")
    assert out.guardrail_status == "REJECTED"
    assert "missing_fundamental_data" in out.rejection_reasons


def test_apply_v2_guardrails_relaxed_missing_fundamentals_no_buy() -> None:
    """Relaxed mode: missing fundamentals WARN but Layer 2 still PASSes
    and downstream layers run. The original action is preserved (the
    spec says: relaxed mode allows WATCH only, not BUY — the engine's
    own strict_mode flag enforces that; here we just check that the
    guardrail report itself doesn't reject."""
    rec = _baseline_rec()
    out = apply_v2_guardrails(rec, fundamentals=None, mode="relaxed")
    assert out.guardrail_status == "PASS"
    assert "missing_fundamental_data" in out.warnings


def test_apply_v2_guardrails_includes_layer_breakdown() -> None:
    rec = _baseline_rec()
    out = apply_v2_guardrails(rec, fundamentals=_clean_fundamentals(), mode="strict")
    labels = {l["layer"] for l in out.guardrail_layer_results}
    assert labels == {"size_liquidity", "fundamentals", "anti_manipulation"}


def test_apply_v2_derives_market_cap_when_only_listed_share_present() -> None:
    rec = _baseline_rec()
    # Last price on the baseline fixture is ~22.95; pick a share count
    # that pushes derived market_cap above the 3T threshold (need
    # ≥130.7B shares at this price).
    f = Fundamentals(
        symbol="TEST",
        market_cap=None,
        listed_share=200_000_000_000,
        roe=18.0,
        net_profit_last_4_quarters=[1e9, 1.1e9, 1.2e9, 1.3e9],
        audit_opinion="UNQUALIFIED",
        is_vn100=True,
    )
    out = apply_v2_guardrails(rec, fundamentals=f, mode="strict")
    # 22.95 × 200B = 4.59T > 3T threshold → no market_cap REJECT
    assert "market_cap_below_threshold" not in out.rejection_reasons
    assert "missing_market_cap" not in out.rejection_reasons
