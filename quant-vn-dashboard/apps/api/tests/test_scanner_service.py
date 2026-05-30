"""Pure-math tests for the Signal Scanner service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from schemas.market import OHLCVBar
from services.scanner import (
    LOW_LIQUIDITY_THRESHOLD,
    classify_trend,
    compute_indicators,
    compute_scores,
    decide_status,
    derive_signals,
    scan_symbol,
)


def _bar(
    *,
    day: int,
    close: float,
    volume: float = 100_000.0,
    value: float | None = None,
    high: float | None = None,
    low: float | None = None,
) -> OHLCVBar:
    ts = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
    return OHLCVBar(
        symbol="TEST",
        ts=ts,
        open=close,
        high=high if high is not None else close * 1.01,
        low=low if low is not None else close * 0.99,
        close=close,
        volume=volume,
        value=value if value is not None else close * volume,
    )


def _flat_series(n: int, close: float = 100.0, volume: float = 100_000.0) -> list[OHLCVBar]:
    return [_bar(day=i, close=close, volume=volume) for i in range(n)]


def _rising_series(
    n: int, start: float = 100.0, step: float = 1.0, volume: float = 100_000.0
) -> list[OHLCVBar]:
    return [_bar(day=i, close=start + i * step, volume=volume) for i in range(n)]


# ── Indicators ──────────────────────────────────────────────────────────────


def test_ma20_ma50_on_known_series() -> None:
    bars = _rising_series(60, start=100.0, step=1.0)
    ind = compute_indicators(bars)
    closes = [b.close for b in bars]
    assert ind.ma20 is not None and abs(ind.ma20 - sum(closes[-20:]) / 20) < 1e-6
    assert ind.ma50 is not None and abs(ind.ma50 - sum(closes[-50:]) / 50) < 1e-6


def test_rsi_null_when_under_15_bars() -> None:
    bars = _flat_series(10)
    ind = compute_indicators(bars)
    assert ind.rsi14 is None

    result = scan_symbol("TEST", bars)
    assert "insufficient_history" in result.warnings
    assert result.indicators.rsi14 is None


def test_rsi_returns_value_with_enough_history() -> None:
    bars = _rising_series(30, step=0.5)
    ind = compute_indicators(bars)
    assert ind.rsi14 is not None
    assert 0.0 <= ind.rsi14 <= 100.0


def test_breakout_20d_triggers_above_prior_high() -> None:
    bars = _flat_series(25, close=100.0)
    bars.append(_bar(day=25, close=120.0))  # last close exceeds prior-20 max
    ind = compute_indicators(bars)
    signals = derive_signals(ind, last_close=bars[-1].close)
    assert "BREAKOUT_20D" in signals


def test_breakout_20d_does_not_trigger_inside_range() -> None:
    bars = _flat_series(25, close=100.0)
    bars.append(_bar(day=25, close=99.0))
    ind = compute_indicators(bars)
    signals = derive_signals(ind, last_close=bars[-1].close)
    assert "BREAKOUT_20D" not in signals


def test_volume_spike_triggers_above_2x() -> None:
    bars = _flat_series(25, close=100.0, volume=100_000.0)
    bars.append(_bar(day=25, close=100.0, volume=300_000.0))
    ind = compute_indicators(bars)
    signals = derive_signals(ind, last_close=bars[-1].close)
    assert "VOLUME_SPIKE" in signals


# ── Scores ─────────────────────────────────────────────────────────────────


def test_score_boundaries_clamp_to_0_and_100() -> None:
    # No indicators → safe defaults, all scores in range.
    bars = _flat_series(5)
    ind = compute_indicators(bars)
    scores = compute_scores(ind, signals=[], last_close=bars[-1].close)
    for field in ("trend", "momentum", "volume", "liquidity", "risk"):
        val = getattr(scores, field)
        assert 0 <= val <= 100, f"{field} out of range: {val}"


def test_volume_score_clamps_at_100() -> None:
    bars = _flat_series(25, close=100.0, volume=100_000.0)
    # 10x volume → raw score 400 → clamped to 100.
    bars.append(_bar(day=25, close=100.0, volume=1_000_000.0))
    ind = compute_indicators(bars)
    scores = compute_scores(ind, signals=[], last_close=bars[-1].close)
    assert scores.volume == 100


def test_low_liquidity_signal_below_threshold() -> None:
    # close*volume = 100 * 100 = 10_000 VND per bar → far under 1B.
    bars = _flat_series(25, close=100.0, volume=100.0)
    ind = compute_indicators(bars)
    assert ind.avg_value_20d is not None
    assert ind.avg_value_20d < LOW_LIQUIDITY_THRESHOLD
    signals = derive_signals(ind, last_close=bars[-1].close)
    assert "LOW_LIQUIDITY" in signals


def test_high_liquidity_does_not_trigger_low_liquidity() -> None:
    # close*volume = 100_000 * 100_000 = 1e10 → above 1B threshold.
    bars = _flat_series(25, close=100_000.0, volume=100_000.0)
    ind = compute_indicators(bars)
    signals = derive_signals(ind, last_close=bars[-1].close)
    assert "LOW_LIQUIDITY" not in signals


# ── Status decision matrix ──────────────────────────────────────────────────


def test_status_avoid_when_low_liquidity() -> None:
    bars = _flat_series(25, close=100.0, volume=100.0)
    result = scan_symbol("TEST", bars)
    assert "LOW_LIQUIDITY" in result.signals
    assert result.status == "AVOID"


def test_status_buy_candidate_on_uptrend_breakout() -> None:
    # Build an obvious uptrend then a breakout day with a volume spike.
    # Use a high price + high volume so avg_value_20d clears the 1B liquidity floor.
    bars = _rising_series(55, start=100_000.0, step=1_000.0, volume=200_000.0)
    last_ts_day = 55
    last_close = 250_000.0  # well above ma20/ma50 and prior 20d high
    bars.append(
        _bar(
            day=last_ts_day,
            close=last_close,
            volume=10_000_000.0,  # big spike
            value=last_close * 10_000_000.0,
        )
    )
    result = scan_symbol("TEST", bars)
    assert result.trend == "UPTREND"
    assert "BREAKOUT_20D" in result.signals
    assert "VOLUME_SPIKE" in result.signals
    assert "LOW_LIQUIDITY" not in result.signals
    assert result.status == "BUY_CANDIDATE"


def test_status_hold_on_low_momentum_sideways() -> None:
    # Liquid + SIDEWAYS but with momentum<40 should land on HOLD.
    # A gently declining series keeps RSI low; we still avoid DOWNTREND by
    # ending at a level above the MA20 in the very last bar.
    from schemas.scanner import ScannerScores

    scores = ScannerScores(trend=50, momentum=30, volume=20, liquidity=80, risk=40)
    decision = decide_status(scores, signals=[], trend="SIDEWAYS")
    assert decision == "HOLD"


def test_status_watch_on_flat_liquid_series() -> None:
    # Flat liquid series → RSI≈50 → momentum=50 → WATCH (per the WATCH bucket
    # rule: SIDEWAYS + momentum>=40).
    bars = _flat_series(60, close=100_000.0, volume=200_000.0)
    result = scan_symbol("TEST", bars)
    assert "LOW_LIQUIDITY" not in result.signals
    assert result.status == "WATCH"


def test_classify_trend_sideways_when_neither_condition_holds() -> None:
    bars = _flat_series(60, close=100_000.0, volume=200_000.0)
    ind = compute_indicators(bars)
    trend = classify_trend(ind, last_close=bars[-1].close)
    assert trend == "SIDEWAYS"


def test_decide_status_avoid_overrides_other_conditions() -> None:
    # Manually craft an UPTREND + momentum but force AVOID via risk=85.
    from schemas.scanner import ScannerScores

    scores = ScannerScores(trend=100, momentum=80, volume=80, liquidity=80, risk=85)
    status = decide_status(scores, signals=["BREAKOUT_20D"], trend="UPTREND")
    assert status == "AVOID"


def test_scanner_codebase_contains_no_financial_advice_wording() -> None:
    """Regression: scanner code, schemas, route comments, and frontend UI
    must never contain marketing-style "guaranteed profit / must buy / sure
    bet / risk-free" phrasing. Research-signal wording only.

    This sweep covers:
      * apps/api/src/services/scanner.py
      * apps/api/src/schemas/scanner.py
      * apps/api/src/api/routes/scanner.py
      * apps/web/src/components/scanner/  (all .tsx)
      * apps/web/src/app/(dash)/watchlist/page.tsx
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
        api_root / "services" / "scanner.py",
        api_root / "schemas" / "scanner.py",
        api_root / "api" / "routes" / "scanner.py",
        web_root / "app" / "(dash)" / "watchlist" / "page.tsx",
    ]
    scanner_components = web_root / "components" / "scanner"
    if scanner_components.exists():
        targets.extend(scanner_components.glob("*.tsx"))
        targets.extend(scanner_components.glob("*.ts"))

    # Phrases that have NO place in a research dashboard.
    # Each is matched case-insensitive, with flexible whitespace/punct.
    forbidden = [
        r"guaranteed\s+profit",
        r"guaranteed\s+return",
        r"must\s+buy",
        r"must\s+sell",
        r"sure\s+bet",
        r"risk[\-\s]?free",
        r"can[' ]?t\s+lose",
        r"hot\s+tip",
        r"insider\s+tip",
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
        "Scanner code/UI contains forbidden financial-advice language: "
        f"{offenders}"
    )
