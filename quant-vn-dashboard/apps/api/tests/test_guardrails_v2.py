"""Tests for the Phase 2.B strict 3-layer guardrail pipeline."""

from __future__ import annotations

import pytest

from schemas.fundamentals import Fundamentals
from services.guardrails_v2 import (
    CONSECUTIVE_CEILINGS_MAX_NON_VN100,
    GuardrailEvidenceV2,
    MIN_LIQUIDITY_VND,
    MIN_MARKET_CAP,
    MIN_ROE_PCT,
    R1_LOW_LIQUIDITY,
    R1_MARKET_CAP_BELOW_THRESHOLD,
    R1_MISSING_AVG_VALUE_20D,
    R1_MISSING_MARKET_CAP,
    R2_INSUFFICIENT_ROE,
    R2_MISSING_AUDIT_OPINION,
    R2_MISSING_FUNDAMENTAL_DATA,
    R2_MISSING_NET_PROFIT,
    R2_MISSING_ROE,
    R2_NEGATIVE_QUARTERLY_PROFIT,
    R2_UNCLEAN_AUDIT_OPINION,
    R3_MISSING_VOL_COV,
    R3_POTENTIAL_WASH_TRADING,
    R3_UNBACKED_EXTREME_PUMP,
    VOL_COV_MIN,
    evaluate,
)


def _clean_fundamentals(**overrides) -> Fundamentals:
    base = {
        "symbol": "TEST",
        "market_cap": MIN_MARKET_CAP * 2,
        "roe": 20.0,
        "net_profit_last_4_quarters": [1e9, 1.1e9, 1.2e9, 1.3e9],
        "audit_opinion": "UNQUALIFIED",
        "is_vn100": False,
    }
    base.update(overrides)
    return Fundamentals(**base)


def _clean_evidence(**overrides) -> GuardrailEvidenceV2:
    base: dict = {
        "symbol": "TEST",
        "mode": "strict",
        "avg_value_20d": MIN_LIQUIDITY_VND * 2,
        "market_cap": MIN_MARKET_CAP * 2,
        "last_price": 25_000.0,
        "fundamentals": _clean_fundamentals(),
        "vol_cov_20d": 0.5,
        "consecutive_ceilings": 0,
        "is_vn100": False,
        "ceiling_price": 26_750.0,
        "floor_price": 23_250.0,
        "ma200": 22_000.0,
        "bars_count": 260,
    }
    base.update(overrides)
    return GuardrailEvidenceV2(**base)


# ── Layer 1 ────────────────────────────────────────────────────────────────


def test_layer1_rejects_low_liquidity() -> None:
    ev = _clean_evidence(avg_value_20d=MIN_LIQUIDITY_VND - 1)
    report = evaluate(ev)
    assert report.is_rejected()
    assert R1_LOW_LIQUIDITY in report.rejection_reasons


def test_layer1_rejects_market_cap_below_threshold() -> None:
    ev = _clean_evidence(
        market_cap=MIN_MARKET_CAP - 1,
        fundamentals=_clean_fundamentals(market_cap=MIN_MARKET_CAP - 1),
    )
    report = evaluate(ev)
    assert report.is_rejected()
    assert R1_MARKET_CAP_BELOW_THRESHOLD in report.rejection_reasons


def test_layer1_rejects_missing_avg_value_20d_in_strict() -> None:
    ev = _clean_evidence(avg_value_20d=None)
    report = evaluate(ev)
    assert report.is_rejected()
    assert R1_MISSING_AVG_VALUE_20D in report.rejection_reasons


def test_layer1_warns_missing_avg_value_20d_in_relaxed() -> None:
    ev = _clean_evidence(avg_value_20d=None, mode="relaxed")
    report = evaluate(ev)
    # Layer 1 itself should PASS (warning only); other layers may still
    # reject so we don't assert overall status here, just the layer.
    layer1 = next(l for l in report.layers if l.layer == "size_liquidity")
    assert layer1.status == "PASS"
    assert R1_MISSING_AVG_VALUE_20D in layer1.warnings


def test_layer1_rejects_missing_market_cap_in_strict() -> None:
    ev = _clean_evidence(
        market_cap=None,
        fundamentals=_clean_fundamentals(market_cap=None),
    )
    report = evaluate(ev)
    assert R1_MISSING_MARKET_CAP in report.rejection_reasons


# ── Layer 2 ────────────────────────────────────────────────────────────────


def test_layer2_rejects_insufficient_roe() -> None:
    ev = _clean_evidence(
        fundamentals=_clean_fundamentals(roe=MIN_ROE_PCT - 0.1)
    )
    report = evaluate(ev)
    assert R2_INSUFFICIENT_ROE in report.rejection_reasons


def test_layer2_rejects_negative_quarterly_profit() -> None:
    ev = _clean_evidence(
        fundamentals=_clean_fundamentals(
            net_profit_last_4_quarters=[1e9, -1e8, 1.2e9, 1.3e9]
        )
    )
    report = evaluate(ev)
    assert R2_NEGATIVE_QUARTERLY_PROFIT in report.rejection_reasons


def test_layer2_rejects_unclean_audit_opinion() -> None:
    ev = _clean_evidence(
        fundamentals=_clean_fundamentals(audit_opinion="QUALIFIED")
    )
    report = evaluate(ev)
    assert R2_UNCLEAN_AUDIT_OPINION in report.rejection_reasons


def test_layer2_strict_rejects_missing_fundamentals() -> None:
    ev = _clean_evidence(fundamentals=None)
    report = evaluate(ev)
    assert R2_MISSING_FUNDAMENTAL_DATA in report.rejection_reasons


def test_layer2_relaxed_warns_missing_fundamentals() -> None:
    # relaxed mode is the only one that treats missing data as WARN.
    ev = _clean_evidence(mode="relaxed", fundamentals=None)
    report = evaluate(ev)
    layer2 = next(l for l in report.layers if l.layer == "fundamentals")
    assert layer2.status == "PASS"
    assert R2_MISSING_FUNDAMENTAL_DATA in layer2.warnings


def test_layer2_strict_rejects_missing_roe_specifically() -> None:
    ev = _clean_evidence(fundamentals=_clean_fundamentals(roe=None))
    report = evaluate(ev)
    assert R2_MISSING_ROE in report.rejection_reasons


def test_layer2_strict_rejects_missing_net_profit() -> None:
    ev = _clean_evidence(
        fundamentals=_clean_fundamentals(net_profit_last_4_quarters=None)
    )
    report = evaluate(ev)
    assert R2_MISSING_NET_PROFIT in report.rejection_reasons


def test_layer2_strict_rejects_missing_audit_opinion() -> None:
    ev = _clean_evidence(
        fundamentals=_clean_fundamentals(audit_opinion=None)
    )
    report = evaluate(ev)
    assert R2_MISSING_AUDIT_OPINION in report.rejection_reasons


# ── Layer 3 ────────────────────────────────────────────────────────────────


def test_layer3_rejects_low_vol_cov_as_potential_wash_trading() -> None:
    ev = _clean_evidence(vol_cov_20d=VOL_COV_MIN - 0.001)
    report = evaluate(ev)
    assert R3_POTENTIAL_WASH_TRADING in report.rejection_reasons


def test_layer3_warns_missing_vol_cov() -> None:
    ev = _clean_evidence(vol_cov_20d=None)
    report = evaluate(ev)
    layer3 = next(l for l in report.layers if l.layer == "anti_manipulation")
    assert R3_MISSING_VOL_COV in layer3.warnings


def test_layer3_strict_rejects_unbacked_extreme_pump_non_vn100() -> None:
    ev = _clean_evidence(
        consecutive_ceilings=CONSECUTIVE_CEILINGS_MAX_NON_VN100 + 1,
        is_vn100=False,
    )
    report = evaluate(ev)
    assert R3_UNBACKED_EXTREME_PUMP in report.rejection_reasons


def test_layer3_balanced_warns_instead_of_rejects_unbacked_pump() -> None:
    ev = _clean_evidence(
        mode="balanced",
        consecutive_ceilings=CONSECUTIVE_CEILINGS_MAX_NON_VN100 + 1,
        is_vn100=False,
    )
    report = evaluate(ev)
    layer3 = next(l for l in report.layers if l.layer == "anti_manipulation")
    assert R3_UNBACKED_EXTREME_PUMP in layer3.warnings
    assert layer3.status == "PASS"


def test_layer3_vn100_immune_to_extreme_pump_reject() -> None:
    """VN100 components get the unbacked-pump rule turned off because
    institutional flow can sustain multi-day ceilings."""
    ev = _clean_evidence(
        consecutive_ceilings=CONSECUTIVE_CEILINGS_MAX_NON_VN100 + 5,
        is_vn100=True,
    )
    report = evaluate(ev)
    layer3 = next(l for l in report.layers if l.layer == "anti_manipulation")
    # No unbacked-pump REJECT
    assert R3_UNBACKED_EXTREME_PUMP not in layer3.rejection_reasons


# ── End-to-end orchestration ───────────────────────────────────────────────


def test_clean_path_passes_all_three_layers() -> None:
    report = evaluate(_clean_evidence())
    assert not report.is_rejected()
    assert report.fundamental_data_status == "FUNDAMENTAL_DATA_AVAILABLE"
    assert all(l.status == "PASS" for l in report.layers)


def test_reject_in_layer1_still_runs_layer2_and_layer3() -> None:
    """Spec: diagnostics from downstream layers are surfaced even after
    an upstream REJECT."""
    ev = _clean_evidence(
        avg_value_20d=1_000.0,                # layer 1 REJECT
        fundamentals=_clean_fundamentals(roe=5.0),  # layer 2 REJECT too
        vol_cov_20d=0.01,                      # layer 3 REJECT too
    )
    report = evaluate(ev)
    assert report.is_rejected()
    assert R1_LOW_LIQUIDITY in report.rejection_reasons
    assert R2_INSUFFICIENT_ROE in report.rejection_reasons
    assert R3_POTENTIAL_WASH_TRADING in report.rejection_reasons


def test_fundamental_data_status_partial() -> None:
    ev = _clean_evidence(
        mode="relaxed",
        fundamentals=Fundamentals(symbol="X", roe=20.0, audit_opinion=None),
    )
    report = evaluate(ev)
    assert report.fundamental_data_status == "FUNDAMENTAL_DATA_PARTIAL"
