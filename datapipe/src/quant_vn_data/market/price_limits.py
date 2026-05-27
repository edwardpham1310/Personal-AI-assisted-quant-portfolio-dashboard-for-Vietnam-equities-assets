"""Vietnam price limit (ceiling/floor) computation.

HOSE:  ±7% from reference price
HNX:   ±10% from reference price
UPCoM: ±15% from reference price
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

_LIMIT_PCT: dict[str, float] = {
    "HOSE": 0.07,
    "HNX": 0.10,
    "UPCOM": 0.15,
}

_DEFAULT_TICK = 100  # smallest price unit in VND


def compute_price_limits(
    reference_price: float,
    exchange: str,
    tick_size: float = _DEFAULT_TICK,
) -> tuple[float, float]:
    """Return (ceiling, floor) for a given reference price and exchange.

    Raises ValueError for unknown exchange codes to avoid silently applying
    the wrong price limit to a symbol.
    """
    key = exchange.upper()
    if key not in _LIMIT_PCT:
        raise ValueError(
            f"Unknown exchange '{exchange}'. Expected one of: {sorted(_LIMIT_PCT)}. "
            "Cannot compute price limits without knowing the correct daily limit percentage."
        )
    pct = _LIMIT_PCT[key]
    ceiling = _round_to_tick(reference_price * (1 + pct), tick_size)
    floor = _round_to_tick(reference_price * (1 - pct), tick_size)
    return ceiling, floor


def enrich_price_limits(df: pd.DataFrame) -> pd.DataFrame:
    """Add ceiling_price and floor_price columns where reference_price and exchange are known."""
    if df.empty:
        return df
    df = df.copy()
    if "reference_price" not in df.columns or "exchange" not in df.columns:
        return df

    mask = df["reference_price"].notna() & df["exchange"].notna()
    if mask.sum() == 0:
        return df

    def _limits(row: pd.Series) -> pd.Series:
        try:
            c, f = compute_price_limits(float(row["reference_price"]), str(row["exchange"]))
        except ValueError as exc:
            logger.warning("enrich_price_limits: %s", exc)
            return pd.Series({"ceiling_price": None, "floor_price": None})
        return pd.Series({"ceiling_price": c, "floor_price": f})

    computed = df[mask].apply(_limits, axis=1)
    df.loc[mask, "ceiling_price"] = computed["ceiling_price"]
    df.loc[mask, "floor_price"] = computed["floor_price"]
    return df


def _round_to_tick(price: float, tick: float) -> float:
    return round(round(price / tick) * tick, 2)
