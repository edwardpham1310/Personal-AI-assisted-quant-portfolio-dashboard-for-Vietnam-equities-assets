"""Signal Scanner — pure indicator math + heuristic scoring.

All labels emitted by this module (``trend``, ``signals``, ``status``) are
**research signals, not financial advice or order recommendations**. The
status field is informational; downstream consumers must surface it as
research output only.

Public surface
--------------
* ``compute_indicators(bars)`` — MA20/MA50/RSI14/ATR14/volume ratio/highs/avg value.
* ``derive_signals(indicators, last_close)`` — boolean signal flags.
* ``compute_scores(indicators, signals)`` — five 0..100 sub-scores.
* ``classify_trend(indicators, last_close)`` — UPTREND/DOWNTREND/SIDEWAYS/UNKNOWN.
* ``decide_status(scores, signals, trend)`` — BUY_CANDIDATE/WATCH/HOLD/AVOID.
* ``scan_symbol(symbol, bars, latest_quote=None)`` — end-to-end pipeline.

Everything is sync + pure (no I/O, no network) so it can be unit-tested by
feeding lists of ``OHLCVBar`` directly. The API route is the only place
that mixes in provider calls and the cache.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from schemas.market import OHLCVBar, Quote
from schemas.scanner import (
    ScannerIndicators,
    ScannerResult,
    ScannerScores,
)

# ── Thresholds ──────────────────────────────────────────────────────────────
# Pulled out so the test file can reference them and so they aren't smuggled
# into multiple helpers as magic numbers.

MA_SHORT_WINDOW = 20
MA_LONG_WINDOW = 50
RSI_WINDOW = 14
ATR_WINDOW = 14
VOLUME_LOOKBACK = 20
BREAKOUT_SHORT_WINDOW = 20
BREAKOUT_LONG_WINDOW = 55
AVG_VALUE_WINDOW = 20

RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0
VOLUME_SPIKE_RATIO = 2.0
LOW_LIQUIDITY_THRESHOLD = 1_000_000_000.0  # 1 billion VND


# ── Indicator math ──────────────────────────────────────────────────────────


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _sma(closes: list[float], window: int) -> float | None:
    """Simple moving average over the last ``window`` closes."""
    if len(closes) < window:
        return None
    return _mean(closes[-window:])


def _rsi_wilder(closes: list[float], window: int = RSI_WINDOW) -> float | None:
    """Wilder-smoothed RSI. Needs ``window + 1`` closes to produce a value."""
    if len(closes) < window + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    # Seed with the simple average of the first ``window`` deltas, then apply
    # Wilder smoothing for the remaining bars.
    avg_gain = _mean(gains[:window])
    avg_loss = _mean(losses[:window])
    for i in range(window, len(gains)):
        avg_gain = (avg_gain * (window - 1) + gains[i]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i]) / window
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr_wilder(bars: list[OHLCVBar], window: int = ATR_WINDOW) -> float | None:
    """Wilder ATR over true ranges. Needs ``window + 1`` bars."""
    if len(bars) < window + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(bars)):
        high = bars[i].high
        low = bars[i].low
        prev_close = bars[i - 1].close
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    atr = _mean(trs[:window])
    for i in range(window, len(trs)):
        atr = (atr * (window - 1) + trs[i]) / window
    return atr


def _volume_ratio(volumes: list[float], window: int = VOLUME_LOOKBACK) -> float | None:
    """today / mean(previous ``window`` volumes). Today is excluded from the avg."""
    if len(volumes) < window + 1:
        return None
    prior = volumes[-(window + 1) : -1]
    avg = _mean(prior)
    if avg <= 0:
        return None
    return volumes[-1] / avg


def _prior_high(closes: list[float], window: int) -> float | None:
    """Max close over the prior ``window`` bars (excluding today)."""
    if len(closes) < window + 1:
        return None
    return max(closes[-(window + 1) : -1])


def _avg_value(bars: list[OHLCVBar], window: int = AVG_VALUE_WINDOW) -> float | None:
    """Mean trading value over the last ``window`` bars. Falls back to close*volume."""
    if len(bars) < window:
        return None
    recent = bars[-window:]
    values: list[float] = []
    for bar in recent:
        if bar.value is not None:
            values.append(bar.value)
        else:
            values.append(bar.close * bar.volume)
    return _mean(values)


def compute_indicators(bars: list[OHLCVBar]) -> ScannerIndicators:
    """Compute all indicators from a daily, ascending list of ``OHLCVBar``.

    Missing values are returned as ``None`` rather than zero so the route
    layer can attach an ``insufficient_history`` warning without ambiguity.
    """
    if not bars:
        return ScannerIndicators()
    closes = [b.close for b in bars]
    volumes = [b.volume for b in bars]
    return ScannerIndicators(
        ma20=_sma(closes, MA_SHORT_WINDOW),
        ma50=_sma(closes, MA_LONG_WINDOW),
        rsi14=_rsi_wilder(closes, RSI_WINDOW),
        atr14=_atr_wilder(bars, ATR_WINDOW),
        volume_ratio_20d=_volume_ratio(volumes, VOLUME_LOOKBACK),
        high_20d=_prior_high(closes, BREAKOUT_SHORT_WINDOW),
        high_55d=_prior_high(closes, BREAKOUT_LONG_WINDOW),
        avg_value_20d=_avg_value(bars, AVG_VALUE_WINDOW),
    )


# ── Signals / trend / scores / status ───────────────────────────────────────


def derive_signals(
    indicators: ScannerIndicators, last_close: float | None
) -> list[str]:
    """Boolean signal flags. Order is stable and documented."""
    out: list[str] = []
    ma20 = indicators.ma20
    ma50 = indicators.ma50

    if ma20 is not None and ma50 is not None and ma20 > ma50:
        out.append("MA20_ABOVE_MA50")
    if ma20 is not None and last_close is not None and last_close > ma20:
        out.append("PRICE_ABOVE_MA20")
    if (
        indicators.volume_ratio_20d is not None
        and indicators.volume_ratio_20d >= VOLUME_SPIKE_RATIO
    ):
        out.append("VOLUME_SPIKE")
    if (
        indicators.high_20d is not None
        and last_close is not None
        and last_close > indicators.high_20d
    ):
        out.append("BREAKOUT_20D")
    if (
        indicators.high_55d is not None
        and last_close is not None
        and last_close > indicators.high_55d
    ):
        out.append("BREAKOUT_55D")
    if indicators.rsi14 is not None and indicators.rsi14 >= RSI_OVERBOUGHT:
        out.append("RSI_OVERBOUGHT")
    if indicators.rsi14 is not None and indicators.rsi14 <= RSI_OVERSOLD:
        out.append("RSI_OVERSOLD")
    if (
        indicators.avg_value_20d is not None
        and indicators.avg_value_20d < LOW_LIQUIDITY_THRESHOLD
    ):
        out.append("LOW_LIQUIDITY")
    return out


def classify_trend(
    indicators: ScannerIndicators, last_close: float | None
) -> str:
    """UPTREND / DOWNTREND / SIDEWAYS when both MAs exist; UNKNOWN otherwise."""
    ma20 = indicators.ma20
    ma50 = indicators.ma50
    if ma20 is None or ma50 is None or last_close is None:
        return "UNKNOWN"
    if ma20 > ma50 and last_close > ma20:
        return "UPTREND"
    if ma20 < ma50 and last_close < ma20:
        return "DOWNTREND"
    return "SIDEWAYS"


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    return int(round(max(lo, min(hi, value))))


def compute_scores(
    indicators: ScannerIndicators,
    signals: list[str],
    *,
    last_close: float | None = None,
) -> ScannerScores:
    """Five 0..100 heuristic sub-scores.

    * ``trend``: 50 base. +25 if MA20>MA50, +25 if PRICE_ABOVE_MA20.
      -25 if price<MA20 *and* MA20<MA50.
    * ``momentum``: linear map RSI 30→0, 50→50, 70→100; +10 on BREAKOUT_20D
      (capped at 100). Defaults to 50 when RSI is null.
    * ``volume``: ``min(100, volume_ratio_20d * 40)``; 0 when null.
    * ``liquidity``: ``log10(avg_value_20d)`` scaled so 1e9 VND → 50,
      1e10 → 75, 1e11 → 100. Returns 0 when null (warning is attached by
      the route layer).
    * ``risk``: ATR/last_close as a volatility pct. 1% → 20, 3% → 50,
      5%+ → 80+. Higher == riskier. Defaults to 50 when null.
    """
    # ── trend ──
    trend_raw = 50.0
    if "MA20_ABOVE_MA50" in signals:
        trend_raw += 25.0
    if "PRICE_ABOVE_MA20" in signals:
        trend_raw += 25.0
    if (
        "PRICE_ABOVE_MA20" not in signals
        and "MA20_ABOVE_MA50" not in signals
        and indicators.ma20 is not None
        and indicators.ma50 is not None
    ):
        trend_raw -= 25.0
    trend_score = _clamp(trend_raw)

    # ── momentum ──
    if indicators.rsi14 is None:
        momentum_raw = 50.0
    else:
        # Linear map 30→0, 70→100; values outside that range still clamp.
        momentum_raw = (indicators.rsi14 - 30.0) * (100.0 / 40.0)
    if "BREAKOUT_20D" in signals:
        momentum_raw += 10.0
    momentum_score = _clamp(momentum_raw)

    # ── volume ──
    if indicators.volume_ratio_20d is None:
        volume_score = 0
    else:
        volume_score = _clamp(indicators.volume_ratio_20d * 40.0)

    # ── liquidity ──
    if indicators.avg_value_20d is None or indicators.avg_value_20d <= 0:
        liquidity_score = 0
    else:
        # log10(1e8)=8 → 25; log10(1e9)=9 → 50; log10(1e10)=10 → 75; log10(1e11)=11 → 100.
        liquidity_raw = (math.log10(indicators.avg_value_20d) - 7.0) * 25.0
        liquidity_score = _clamp(liquidity_raw)

    risk_score = _risk_score_with_close(indicators.atr14, last_close)

    return ScannerScores(
        trend=trend_score,
        momentum=momentum_score,
        volume=volume_score,
        liquidity=liquidity_score,
        risk=risk_score,
    )


def _risk_score_with_close(atr14: float | None, last_close: float | None) -> int:
    if atr14 is None or last_close is None or last_close <= 0 or atr14 <= 0:
        return 50
    vol_pct = (atr14 / last_close) * 100.0  # in percent
    # 1% → 20, 3% → 50, 5% → 80. Linear segment 1..5; clamp at edges.
    if vol_pct <= 1.0:
        raw = max(0.0, vol_pct * 20.0)  # 0..20
    elif vol_pct <= 5.0:
        raw = 20.0 + (vol_pct - 1.0) * 15.0  # 20..80
    else:
        raw = 80.0 + (vol_pct - 5.0) * 5.0  # 80..100+
    return _clamp(raw)


def decide_status(
    scores: ScannerScores, signals: list[str], trend: str
) -> str:
    """AVOID > BUY_CANDIDATE > WATCH > HOLD.

    Decision order matters — AVOID gates always run first.
    """
    if (
        "LOW_LIQUIDITY" in signals
        or scores.risk >= 80
        or trend == "DOWNTREND"
    ):
        return "AVOID"
    if (
        trend == "UPTREND"
        and scores.momentum >= 60
        and ("BREAKOUT_20D" in signals or "VOLUME_SPIKE" in signals)
        and "LOW_LIQUIDITY" not in signals
        and scores.risk < 70
    ):
        return "BUY_CANDIDATE"
    if trend in {"UPTREND", "SIDEWAYS"} and scores.momentum >= 40:
        return "WATCH"
    return "HOLD"


# ── End-to-end scan ─────────────────────────────────────────────────────────


def _warnings(
    bars: list[OHLCVBar],
    indicators: ScannerIndicators,
    latest_quote: Quote | None,
) -> list[str]:
    out: list[str] = []
    if (
        indicators.rsi14 is None
        or indicators.atr14 is None
        or indicators.ma50 is None
    ):
        out.append("insufficient_history")
    if indicators.avg_value_20d is None:
        # Don't double-warn if we already flagged insufficient history.
        if "insufficient_history" not in out:
            out.append("insufficient_liquidity_history")
    if latest_quote is not None and latest_quote.stale:
        out.append("stale_data")
    if not bars:
        out.append("no_bars")
    return out


def scan_symbol(
    symbol: str,
    bars: list[OHLCVBar],
    *,
    latest_quote: Quote | None = None,
) -> ScannerResult:
    """Run the full scanner pipeline for a single symbol.

    ``bars`` MUST be daily, sorted ascending by ``ts``. The caller (the API
    route) handles caching and provider failures; this function is pure.
    """
    indicators = compute_indicators(bars)
    last_close = bars[-1].close if bars else None
    last_price = (
        latest_quote.price if latest_quote is not None else last_close
    )
    signals = derive_signals(indicators, last_close)
    scores = compute_scores(indicators, signals, last_close=last_close)
    trend = classify_trend(indicators, last_close)
    status = decide_status(scores, signals, trend)
    warnings = _warnings(bars, indicators, latest_quote)
    as_of_dt = (
        latest_quote.ts
        if latest_quote is not None
        else (bars[-1].ts if bars else datetime.now(UTC))
    )
    return ScannerResult(
        symbol=symbol.upper(),
        last_price=last_price,
        trend=trend,  # type: ignore[arg-type]
        signals=signals,  # type: ignore[arg-type]
        scores=scores,
        status=status,  # type: ignore[arg-type]
        warnings=warnings,
        as_of=as_of_dt.isoformat() if isinstance(as_of_dt, datetime) else str(as_of_dt),
        indicators=indicators,
    )


def result_to_dict(result: ScannerResult) -> dict[str, Any]:
    """JSON-safe dict — used by the cache layer to avoid re-validating later."""
    return result.model_dump(mode="json")
