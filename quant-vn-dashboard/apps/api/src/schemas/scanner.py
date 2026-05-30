"""DTOs for the Signal Scanner.

All labels emitted here (``trend``, ``signals``, ``status``) are
**research signals, not financial advice or order recommendations**.
The dashboard treats them as informational only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Trend = Literal["UPTREND", "DOWNTREND", "SIDEWAYS", "UNKNOWN"]
Status = Literal["BUY_CANDIDATE", "WATCH", "HOLD", "AVOID"]

# Names of the signal flags the scanner may emit. Kept as a Literal so the
# OpenAPI spec lists the closed set and the frontend can autocomplete them.
SignalName = Literal[
    "MA20_ABOVE_MA50",
    "PRICE_ABOVE_MA20",
    "VOLUME_SPIKE",
    "BREAKOUT_20D",
    "BREAKOUT_55D",
    "RSI_OVERBOUGHT",
    "RSI_OVERSOLD",
    "LOW_LIQUIDITY",
]


class ScannerIndicators(BaseModel):
    """Raw indicator values (or null when there is not enough history)."""

    ma20: float | None = None
    ma50: float | None = None
    rsi14: float | None = None
    atr14: float | None = None
    volume_ratio_20d: float | None = None
    high_20d: float | None = None
    high_55d: float | None = None
    avg_value_20d: float | None = None


class ScannerScores(BaseModel):
    """Heuristic 0..100 sub-scores. See ``services/scanner.py`` for the math."""

    trend: int = Field(ge=0, le=100)
    momentum: int = Field(ge=0, le=100)
    volume: int = Field(ge=0, le=100)
    liquidity: int = Field(ge=0, le=100)
    risk: int = Field(ge=0, le=100)


class ScannerResult(BaseModel):
    """Per-symbol scanner output.

    ``status`` is a research label only. It is NOT an order recommendation.
    """

    symbol: str
    last_price: float | None = None
    trend: Trend
    signals: list[SignalName] = []
    scores: ScannerScores
    status: Status
    warnings: list[str] = []
    as_of: str
    indicators: ScannerIndicators
