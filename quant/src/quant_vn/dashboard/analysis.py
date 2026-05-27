"""Explainable technical dashboard signals for Vietnam equity research."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant_vn.indicators.momentum import rsi
from quant_vn.indicators.trend import sma
from quant_vn.indicators.volume import volume_ratio
from quant_vn.indicators.volatility import atr


@dataclass(frozen=True)
class DashboardSignal:
    """Current technical state and recommendation for one symbol."""

    symbol: str
    label: str
    score: int
    confidence: str
    last_date: str
    close: float
    sma20: float | None
    sma50: float | None
    rsi14: float | None
    volume_ratio20: float | None
    atr_pct14: float | None
    return_20d_pct: float | None
    return_60d_pct: float | None
    drawdown_pct: float | None
    reasons: list[str]
    risks: list[str]


def analyze_universe(price_map: dict[str, pd.DataFrame]) -> list[DashboardSignal]:
    """Analyze a dict of symbol -> OHLCV DataFrame."""
    signals = []
    for symbol, prices in price_map.items():
        if prices is None or prices.empty:
            continue
        signals.append(analyze_symbol(symbol, prices))
    return sorted(signals, key=lambda item: (item.score, item.confidence), reverse=True)


def analyze_symbol(symbol: str, prices: pd.DataFrame) -> DashboardSignal:
    """Compute an explainable technical recommendation for one symbol."""
    df = _prepare_prices(prices)
    if df.empty:
        raise ValueError(f"No usable price data for {symbol}")

    close = df["close"]
    volume = df.get("volume", pd.Series(index=df.index, dtype=float))

    df["sma20"] = sma(close, 20)
    df["sma50"] = sma(close, 50)
    df["rsi14"] = rsi(close, 14)
    df["volume_ratio20"] = volume_ratio(volume, 20)
    df["atr14"] = atr(df, 14)
    df["return_20d_pct"] = close.pct_change(20) * 100
    df["return_60d_pct"] = close.pct_change(60) * 100
    df["drawdown_pct"] = (close / close.cummax() - 1) * 100

    last = df.iloc[-1]
    latest_close = float(last["close"])
    score = 0
    reasons: list[str] = []
    risks: list[str] = []

    latest_sma20 = _maybe_float(last.get("sma20"))
    latest_sma50 = _maybe_float(last.get("sma50"))
    latest_rsi = _maybe_float(last.get("rsi14"))
    latest_volume_ratio = _maybe_float(last.get("volume_ratio20"))
    latest_atr_pct = _safe_pct(last.get("atr14"), latest_close)
    latest_ret20 = _maybe_float(last.get("return_20d_pct"))
    latest_ret60 = _maybe_float(last.get("return_60d_pct"))
    latest_drawdown = _maybe_float(last.get("drawdown_pct"))

    if latest_sma20 is not None:
        if latest_close > latest_sma20:
            score += 1
            reasons.append("Close is above SMA20, showing short-term trend support.")
        else:
            score -= 1
            risks.append("Close is below SMA20, indicating weak short-term trend.")

    if latest_sma20 is not None and latest_sma50 is not None:
        if latest_sma20 > latest_sma50:
            score += 1
            reasons.append("SMA20 is above SMA50, confirming medium-term trend alignment.")
        else:
            score -= 1
            risks.append("SMA20 is below SMA50, so trend confirmation is not present.")

    if latest_rsi is not None:
        if 45 <= latest_rsi <= 65:
            score += 1
            reasons.append("RSI14 is in a healthy momentum zone.")
        elif 30 <= latest_rsi < 45:
            reasons.append("RSI14 is recovering but not yet strongly bullish.")
        elif latest_rsi < 30:
            score += 1
            reasons.append("RSI14 is oversold; this can support a tactical watchlist bounce.")
            risks.append("Oversold stocks can remain weak without trend confirmation.")
        elif latest_rsi > 75:
            score -= 1
            risks.append("RSI14 is extended, increasing pullback risk.")

    if latest_ret20 is not None:
        if latest_ret20 > 3:
            score += 1
            reasons.append("20-day return is positive enough to confirm recent momentum.")
        elif latest_ret20 < -3:
            score -= 1
            risks.append("20-day return is negative, signaling recent weakness.")

    if latest_ret60 is not None and latest_ret60 > 8:
        score += 1
        reasons.append("60-day return shows constructive intermediate momentum.")
    elif latest_ret60 is not None and latest_ret60 < -8:
        score -= 1
        risks.append("60-day return shows meaningful intermediate weakness.")

    if latest_volume_ratio is not None and latest_volume_ratio >= 1.5:
        if latest_ret20 is not None and latest_ret20 >= 0:
            score += 1
            reasons.append("Volume is elevated while price momentum is positive.")
        else:
            score -= 1
            risks.append("Volume is elevated during weak price action.")

    if latest_atr_pct is not None:
        if latest_atr_pct > 6:
            score -= 1
            risks.append("ATR14 percent is high, so position risk may be elevated.")
        elif latest_atr_pct < 3:
            reasons.append("ATR14 percent is moderate, supporting cleaner risk control.")

    if latest_drawdown is not None and latest_drawdown < -15:
        score -= 1
        risks.append("Current close is more than 15% below its period high.")

    if len(df) < 60:
        score -= 1
        risks.append("Less than 60 bars are available; confidence is limited.")

    label = _label_from_score(score)
    confidence = _confidence_from_inputs(df, latest_sma50, latest_rsi, latest_volume_ratio)

    if not reasons:
        reasons.append("No strong positive technical evidence is present yet.")
    if not risks:
        risks.append("No major technical risk flag from the current rule set.")

    return DashboardSignal(
        symbol=symbol.upper(),
        label=label,
        score=score,
        confidence=confidence,
        last_date=str(df.index[-1].date()),
        close=latest_close,
        sma20=latest_sma20,
        sma50=latest_sma50,
        rsi14=latest_rsi,
        volume_ratio20=latest_volume_ratio,
        atr_pct14=latest_atr_pct,
        return_20d_pct=latest_ret20,
        return_60d_pct=latest_ret60,
        drawdown_pct=latest_drawdown,
        reasons=reasons,
        risks=risks,
    )


def _prepare_prices(prices: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"Price data missing columns: {missing}")

    df = prices.copy()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    return df.dropna(subset=list(required))


def _label_from_score(score: int) -> str:
    if score >= 4:
        return "Strong Buy"
    if score >= 2:
        return "Buy"
    if score >= 0:
        return "Hold / Watch"
    return "Reduce / Avoid"


def _confidence_from_inputs(
    df: pd.DataFrame,
    latest_sma50: float | None,
    latest_rsi: float | None,
    latest_volume_ratio: float | None,
) -> str:
    available = sum(value is not None for value in [latest_sma50, latest_rsi, latest_volume_ratio])
    if len(df) >= 120 and available == 3:
        return "High"
    if len(df) >= 60 and available >= 2:
        return "Medium"
    return "Low"


def _maybe_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _safe_pct(value, base: float) -> float | None:
    raw = _maybe_float(value)
    if raw is None or base == 0:
        return None
    return raw / base * 100
