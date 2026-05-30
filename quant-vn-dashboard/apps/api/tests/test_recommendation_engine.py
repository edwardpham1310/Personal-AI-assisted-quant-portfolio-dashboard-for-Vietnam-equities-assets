"""Unit tests for the pure recommendation engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from schemas.market import OHLCVBar, Quote
from services import recommendation_engine as engine


def _bar(ts: datetime, close: float, volume: float = 100_000.0) -> OHLCVBar:
    return OHLCVBar(
        symbol="TST",
        ts=ts,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=volume,
        value=close * volume,
    )


def _bull_bars(n: int = 80, start: float = 100.0, step: float = 0.6) -> list[OHLCVBar]:
    """A clean uptrend with stable volume so all bull signals fire."""
    today = datetime.now(UTC)
    return [
        _bar(today - timedelta(days=n - i - 1), start + i * step, volume=200_000.0)
        for i in range(n)
    ]


def _flat_bars(n: int = 80, price: float = 100.0) -> list[OHLCVBar]:
    today = datetime.now(UTC)
    return [_bar(today - timedelta(days=n - i - 1), price) for i in range(n)]


def _bear_bars(n: int = 80, start: float = 200.0, step: float = 0.8) -> list[OHLCVBar]:
    today = datetime.now(UTC)
    return [
        _bar(today - timedelta(days=n - i - 1), max(1.0, start - i * step))
        for i in range(n)
    ]


# ── compute_final_score ──────────────────────────────────────────────────────


def test_final_score_clamps_to_0_100() -> None:
    scores = {k: 100 for k in [
        "trend", "momentum", "volume", "liquidity",
        "risk_inverse", "market_regime", "portfolio_fit",
    ]}
    scores["ml_probability"] = None
    w = engine.PROFILE_WEIGHTS["short_aggressive"]
    out = engine.compute_final_score(scores, w)
    # ml_probability is None → 0.10 weight contributes 0 → max = 90.
    assert 80 <= out <= 100


def test_final_score_ml_none_does_not_renormalize() -> None:
    scores = {"trend": 100, "momentum": 100, "volume": 100, "liquidity": 100,
              "risk_inverse": 100, "market_regime": 100, "portfolio_fit": 100,
              "ml_probability": None}
    w = engine.PROFILE_WEIGHTS["short_aggressive"]
    out = engine.compute_final_score(scores, w)
    # Sum of non-ml weights == 0.90 → score == 90.
    assert out == 90


def test_final_score_zero_input() -> None:
    scores = dict.fromkeys(
        ["trend", "momentum", "volume", "liquidity",
         "risk_inverse", "market_regime", "portfolio_fit"],
        0,
    )
    scores["ml_probability"] = None
    assert engine.compute_final_score(scores, engine.PROFILE_WEIGHTS["short_aggressive"]) == 0


# ── derive_action ────────────────────────────────────────────────────────────


def test_derive_action_buy_candidate_when_uptrend_strong_and_signal() -> None:
    action = engine.derive_action(
        profile="short_aggressive",
        horizon="SHORT_2W",
        final_score=80,
        trend_label="UPTREND",
        momentum_score=70,
        signals=["BREAKOUT_20D", "PRICE_ABOVE_MA20"],
        portfolio_weight_pct=None,
    )
    assert action == "BUY_CANDIDATE"


def test_derive_action_avoid_on_low_liquidity() -> None:
    action = engine.derive_action(
        profile="short_aggressive",
        horizon="SHORT_2W",
        final_score=85,
        trend_label="UPTREND",
        momentum_score=70,
        signals=["LOW_LIQUIDITY"],
        portfolio_weight_pct=None,
    )
    assert action == "AVOID"


def test_derive_action_sell_candidate_when_downtrend_low_score_held() -> None:
    action = engine.derive_action(
        profile="short_aggressive",
        horizon="SHORT_2W",
        final_score=20,
        trend_label="DOWNTREND",
        momentum_score=20,
        signals=[],
        portfolio_weight_pct=8.0,
    )
    assert action == "SELL_CANDIDATE"


def test_derive_action_hold_default() -> None:
    action = engine.derive_action(
        profile="short_aggressive",
        horizon="SHORT_2W",
        final_score=50,
        trend_label="SIDEWAYS",
        momentum_score=45,
        signals=[],
        portfolio_weight_pct=None,
    )
    assert action == "HOLD"


# ── trade-plan helpers ──────────────────────────────────────────────────────


def test_entry_zone_band_widens_with_long_horizon() -> None:
    short = engine.compute_entry_zone(100.0, "SHORT_2W")
    long = engine.compute_entry_zone(100.0, "LONG_6M")
    assert short is not None and long is not None
    assert (long[1] - long[0]) > (short[1] - short[0])


def test_stop_loss_pct_fallback_when_atr_null() -> None:
    short_stop = engine.compute_stop_loss(100.0, atr14=None, horizon="SHORT_2W")
    long_stop = engine.compute_stop_loss(100.0, atr14=None, horizon="LONG_6M")
    assert short_stop == 95.0  # 5% pct stop
    assert long_stop == 90.0   # 10% pct stop


def test_position_sizing_rounds_down_to_lot() -> None:
    out = engine.compute_position_sizing(
        last_price=15_250.0,
        total_equity=1_000_000_000.0,
        avg_value_20d=50_000_000_000.0,
    )
    assert out["estimated_quantity"] is not None
    assert out["estimated_quantity"] % engine.LOT_SIZE == 0


def test_position_sizing_returns_none_when_price_missing() -> None:
    out = engine.compute_position_sizing(
        last_price=None, total_equity=None, avg_value_20d=None
    )
    assert out == {
        "position_size_vnd": None,
        "estimated_quantity": None,
        "estimated_total_cost": None,
    }


# ── generate_recommendation ─────────────────────────────────────────────────


def test_generate_recommendation_full_path_bull() -> None:
    bars = _bull_bars()
    quote = Quote(
        symbol="TST",
        exchange="HOSE",
        price=bars[-1].close,
        ts=datetime.now(UTC),
        source="mock",
    )
    rec = engine.generate_recommendation(
        symbol="tst",
        profile="short_aggressive",
        horizon="SHORT_2W",
        bars=bars,
        latest_quote=quote,
    )
    assert rec.symbol == "TST"
    assert 0.0 <= rec.confidence <= 1.0
    assert rec.final_score >= 0
    assert rec.action in {
        "BUY_CANDIDATE", "WATCH", "HOLD", "REDUCE",
        "SELL_CANDIDATE", "AVOID", "REJECTED",
    }
    assert len(rec.reasons) >= 3
    assert rec.disclaimer.startswith("research signal")


def test_generate_recommendation_bear_does_not_buy() -> None:
    bars = _bear_bars()
    rec = engine.generate_recommendation(
        symbol="TST",
        profile="short_aggressive",
        horizon="SHORT_2W",
        bars=bars,
        latest_quote=None,
    )
    assert rec.action != "BUY_CANDIDATE"


def test_generate_recommendation_emits_disclaimer_and_reasons() -> None:
    bars = _flat_bars()
    rec = engine.generate_recommendation(
        symbol="TST",
        profile="long_conservative",
        horizon="LONG_6M",
        bars=bars,
        latest_quote=None,
    )
    assert rec.disclaimer
    assert isinstance(rec.reasons, list) and len(rec.reasons) >= 3
    assert isinstance(rec.warnings, list)


# ── confidence ──────────────────────────────────────────────────────────────


def test_confidence_in_unit_interval() -> None:
    bars = _bull_bars()
    rec = engine.generate_recommendation(
        symbol="TST",
        profile="short_aggressive",
        horizon="SHORT_2W",
        bars=bars,
        latest_quote=None,
    )
    assert 0.0 <= rec.confidence <= 1.0


# ── market regime ───────────────────────────────────────────────────────────


def test_market_regime_neutral_when_bars_short() -> None:
    assert engine.compute_market_regime(None) == 50
    short = [_bar(datetime.now(UTC) - timedelta(days=i), 100.0) for i in range(10)]
    assert engine.compute_market_regime(short) == 50


def test_market_regime_bullish_with_uptrend_bars() -> None:
    bars = _bull_bars(n=80, start=900.0, step=1.5)
    assert engine.compute_market_regime(bars) in {60, 80}


# ── portfolio fit ──────────────────────────────────────────────────────────


def test_portfolio_fit_unheld_is_100() -> None:
    assert engine.compute_portfolio_fit("FPT", None) == 100
    assert engine.compute_portfolio_fit("FPT", []) == 100


def test_portfolio_fit_heavy_holding_is_zero() -> None:
    positions = [{"symbol": "FPT", "weight": 0.20}]
    assert engine.compute_portfolio_fit("FPT", positions) == 0


def test_recommendation_codebase_contains_no_financial_advice_wording() -> None:
    """Regression: recommendation engine, guardrails, schema, routes, and the
    /recommendations UI must never contain marketing-style wording.

    The user-facing language must stay in research-signal territory:
    ``research signal``, ``candidate``, ``warning``, ``rejected``. Phrases
    that imply guaranteed outcomes or imperative orders fail this test.
    """
    import pathlib
    import re

    api_root = pathlib.Path(__file__).resolve().parents[1] / "src"
    web_root = (
        pathlib.Path(__file__).resolve().parents[3]
        / "apps"
        / "web"
        / "src"
    )

    targets: list[pathlib.Path] = [
        api_root / "services" / "recommendation_engine.py",
        api_root / "services" / "risk_guardrails.py",
        api_root / "schemas" / "recommendation.py",
        api_root / "api" / "routes" / "recommendations.py",
        web_root / "app" / "(dash)" / "recommendations" / "page.tsx",
        web_root / "hooks" / "useRecommendations.ts",
    ]
    rec_components = web_root / "components" / "recommendations"
    if rec_components.exists():
        targets.extend(rec_components.glob("*.tsx"))
        targets.extend(rec_components.glob("*.ts"))

    # Phrases that have NO place in a Phase 1 research engine.
    forbidden = [
        r"guaranteed\s+profit",
        r"guaranteed\s+return",
        r"guarantee\s+returns?",
        r"must\s+buy",
        r"must\s+sell",
        r"sure\s+win",
        r"sure\s+bet",
        r"risk[\-\s]?free",
        r"can[' ]?t\s+lose",
        r"hot\s+tip",
        r"insider\s+tip",
        r"this\s+will\s+(go|move)\s+up",
    ]
    pattern = re.compile("|".join(forbidden), re.IGNORECASE)

    offenders: list[str] = []
    for path in targets:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        match = pattern.search(text)
        if match:
            offenders.append(f"{path.name}: {match.group(0)!r}")

    assert offenders == [], (
        "Recommendation code/UI contains forbidden financial-advice "
        f"language: {offenders}"
    )
