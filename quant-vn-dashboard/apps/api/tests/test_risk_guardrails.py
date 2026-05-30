"""Risk-guardrail unit tests."""

from __future__ import annotations

from datetime import UTC, datetime

from schemas.recommendation import (
    RecommendationResult,
    RecommendationScores,
)
from services import risk_guardrails as guards


def _rec(**overrides) -> RecommendationResult:
    scores = RecommendationScores(
        trend=70, momentum=60, volume=50, liquidity=80,
        risk=40, risk_inverse=60, market_regime=60, portfolio_fit=100,
        ml_probability=None,
    )
    base = {
        "symbol": "TST",
        "profile": "short_aggressive",
        "horizon": "SHORT_2W",
        "action": "BUY_CANDIDATE",
        "status": "VALID",
        "confidence": 0.7,
        "final_score": 70,
        "scores": scores,
        "last_price": 25_000.0,
        "position_size_vnd": 50_000_000,
        "reasons": ["TREND_UPTREND_CONFIRMED"],
        "warnings": [],
        "as_of": datetime.now(UTC).isoformat(),
    }
    base.update(overrides)
    return RecommendationResult(**base)


# ── REJECT cases ────────────────────────────────────────────────────────────


def test_low_liquidity_rejects() -> None:
    ev = guards.GuardrailEvidence(
        avg_value_20d=500_000_000, position_size_vnd=50_000_000
    )
    hits = guards.evaluate(ev)
    codes = {h.code for h in hits}
    assert "low_liquidity" in codes
    rec = _rec()
    action, status, warnings, reasons = guards.apply_guardrails(rec, ev)
    assert action == "REJECTED"
    assert status == "REJECTED"
    assert "low_liquidity" in warnings
    assert any(r.startswith("GUARDRAIL_REJECT_LOW_LIQUIDITY") for r in reasons)


def test_adv_cap_rejects() -> None:
    # 0.5% of 100B = 500M. Position 1B exceeds.
    ev = guards.GuardrailEvidence(
        avg_value_20d=100_000_000_000, position_size_vnd=1_000_000_000
    )
    rec = _rec()
    action, status, _, _ = guards.apply_guardrails(rec, ev)
    assert action == "REJECTED"
    assert status == "REJECTED"


def test_portfolio_weight_too_high_rejects() -> None:
    # currently 10%, adding 8% would put us at 18% > 15% cap.
    ev = guards.GuardrailEvidence(
        avg_value_20d=10_000_000_000,
        position_size_vnd=80_000_000,
        total_equity=1_000_000_000,
        current_position_weight_pct=0.10,
    )
    rec = _rec()
    action, status, _, _ = guards.apply_guardrails(rec, ev)
    assert action == "REJECTED"
    assert status == "REJECTED"


def test_data_quality_critical_rejects() -> None:
    ev = guards.GuardrailEvidence(data_quality_critical=True)
    rec = _rec()
    action, status, _, _ = guards.apply_guardrails(rec, ev)
    assert action == "REJECTED"
    assert status == "REJECTED"


# ── WARN cases ──────────────────────────────────────────────────────────────


def test_data_stale_warns_does_not_override_action() -> None:
    ev = guards.GuardrailEvidence(
        avg_value_20d=20_000_000_000,
        position_size_vnd=50_000_000,
        quote_stale=True,
    )
    rec = _rec()
    action, status, warnings, _ = guards.apply_guardrails(rec, ev)
    assert action == rec.action
    assert status == "WARNING"
    assert "data_stale" in warnings


def test_avg_value_in_warn_band_emits_warning() -> None:
    ev = guards.GuardrailEvidence(
        avg_value_20d=2_500_000_000,  # 1B–5B → WARN
        position_size_vnd=1_000_000,   # tiny so ADV cap is fine
    )
    rec = _rec()
    action, status, warnings, _ = guards.apply_guardrails(rec, ev)
    assert action == rec.action
    assert status == "WARNING"
    assert "avg_value_20d_below_threshold" in warnings


def test_insufficient_settled_cash_warns() -> None:
    ev = guards.GuardrailEvidence(
        avg_value_20d=20_000_000_000,
        position_size_vnd=50_000_000,
        total_equity=100_000_000,
        settled_cash=10_000_000,
    )
    rec = _rec()
    action, status, warnings, _ = guards.apply_guardrails(rec, ev)
    assert action == rec.action
    assert status == "WARNING"
    assert "insufficient_settled_cash" in warnings


def test_missing_fee_tax_profile_warns() -> None:
    ev = guards.GuardrailEvidence(
        avg_value_20d=20_000_000_000,
        position_size_vnd=50_000_000,
        has_cash_balance_row=False,
    )
    rec = _rec()
    action, status, warnings, _ = guards.apply_guardrails(rec, ev)
    assert action == rec.action
    assert status == "WARNING"
    assert "missing_fee_tax_profile" in warnings


def test_pending_cash_requires_advance_warns() -> None:
    ev = guards.GuardrailEvidence(
        avg_value_20d=20_000_000_000,
        position_size_vnd=50_000_000,
        settled_cash=10_000_000,
        pending_cash=40_000_000,
    )
    rec = _rec()
    _, status, warnings, _ = guards.apply_guardrails(rec, ev)
    assert status == "WARNING"
    assert "pending_cash_requires_advance" in warnings


# ── VALID + INFO cases ─────────────────────────────────────────────────────


def test_clean_evidence_is_valid() -> None:
    ev = guards.GuardrailEvidence(
        avg_value_20d=20_000_000_000,
        position_size_vnd=10_000_000,
        total_equity=500_000_000,
        settled_cash=200_000_000,
        pending_cash=0,
        has_cash_balance_row=True,
    )
    rec = _rec()
    action, status, warnings, _ = guards.apply_guardrails(rec, ev)
    assert action == rec.action
    assert status == "VALID"
    assert warnings == []


def test_ceiling_floor_unavailable_is_info_not_warn() -> None:
    ev = guards.GuardrailEvidence(
        avg_value_20d=20_000_000_000,
        position_size_vnd=10_000_000,
    )
    hits = guards.evaluate(ev)
    codes = {h.code: h.severity for h in hits}
    assert codes.get("ceiling_floor_unavailable") == "INFO"
    # INFO must not bump status.
    rec = _rec()
    _, status, _, _ = guards.apply_guardrails(rec, ev)
    assert status == "VALID"


# ── reject-trumps-warn ordering ────────────────────────────────────────────


def test_reject_trumps_warn() -> None:
    ev = guards.GuardrailEvidence(
        avg_value_20d=500_000_000,  # REJECT (low_liquidity)
        position_size_vnd=10_000_000,
        quote_stale=True,           # WARN (data_stale)
    )
    rec = _rec()
    action, status, warnings, _ = guards.apply_guardrails(rec, ev)
    assert action == "REJECTED"
    assert status == "REJECTED"
    assert "low_liquidity" in warnings
    assert "data_stale" in warnings
