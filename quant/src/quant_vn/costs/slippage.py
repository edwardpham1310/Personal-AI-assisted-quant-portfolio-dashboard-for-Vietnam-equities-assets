"""
Slippage models for Vietnam stock market execution.

Slippage represents the cost of market impact and bid-ask spread when executing
an order at market prices. It is modeled separately from brokerage fees.

Buy side:  effective_price = reference_price * (1 + slippage_rate)
Sell side: effective_price = reference_price * (1 - slippage_rate)

slippage_cost = |effective_price - reference_price| * quantity
              = reference_price * slippage_rate * quantity
              = notional * slippage_rate

Models:
    FixedBpsSlippageModel       — constant bps for all stocks (default)
    LiquidityBucketSlippageModel — different bps tiers by ADV bucket
    ParticipationRateSlippageModel — placeholder; not calibrated for Vietnam

DISCLAIMER: Slippage is highly variable and depends on order size, time of
day, market conditions, and stock liquidity. Fixed-bps models underestimate
impact for illiquid stocks and large orders. For research use only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class SlippageResult:
    """Result of slippage calculation for one order."""
    reference_price: float
    effective_price: float      # price after slippage
    slippage_cost: float        # VND cost = notional * slippage_rate
    slippage_rate: float        # as a decimal (e.g. 0.001 = 10 bps)
    side: Side


class SlippageModel(ABC):
    @abstractmethod
    def calculate(
        self,
        reference_price: float,
        quantity: float,
        side: Side,
        avg_daily_volume_vnd: float | None = None,
    ) -> SlippageResult: ...


@dataclass
class FixedBpsSlippageModel(SlippageModel):
    """
    Constant basis-point slippage applied symmetrically to all orders.

    Assumption: All stocks experience the same slippage regardless of size or
    liquidity. This underestimates impact for illiquid names and large orders.

    Args:
        bps: Slippage in basis points (e.g. 10 = 0.10% = 10 bps).
    """
    bps: float = 10.0

    @property
    def rate(self) -> float:
        return self.bps / 10_000

    def calculate(
        self,
        reference_price: float,
        quantity: float,
        side: Side,
        avg_daily_volume_vnd: float | None = None,
    ) -> SlippageResult:
        if reference_price <= 0:
            raise ValueError(f"reference_price must be positive, got {reference_price}")
        if quantity < 0:
            raise ValueError(f"quantity must be non-negative, got {quantity}")

        if side == Side.BUY:
            effective_price = reference_price * (1.0 + self.rate)
        else:
            effective_price = reference_price * (1.0 - self.rate)

        slippage_cost = abs(effective_price - reference_price) * quantity

        return SlippageResult(
            reference_price=reference_price,
            effective_price=effective_price,
            slippage_cost=slippage_cost,
            slippage_rate=self.rate,
            side=side,
        )


@dataclass
class LiquidityBucketSlippageModel(SlippageModel):
    """
    Tiered slippage based on stock liquidity (Average Daily Value).

    Stocks are bucketed into HIGH / MEDIUM / LOW liquidity categories
    based on avg_daily_volume_vnd thresholds. Each bucket applies a
    different basis-point slippage.

    Args:
        high_liquidity_bps:       bps for avg_value_20d >= high_threshold
        medium_liquidity_bps:     bps for low_threshold <= avg_value_20d < high_threshold
        low_liquidity_bps:        bps for avg_value_20d < low_threshold
        high_threshold_vnd:       ADV threshold (VND) for HIGH bucket
        low_threshold_vnd:        ADV threshold (VND) below which LOW bucket applies
        fallback_bps:             bps when ADV data is unavailable
    """
    high_liquidity_bps: float = 10.0
    medium_liquidity_bps: float = 25.0
    low_liquidity_bps: float = 50.0
    high_threshold_vnd: float = 50_000_000_000.0    # 50B VND
    low_threshold_vnd: float = 5_000_000_000.0      # 5B VND
    fallback_bps: float = 25.0                       # when ADV unknown

    def _bps_for(self, avg_daily_volume_vnd: float | None) -> float:
        if avg_daily_volume_vnd is None:
            return self.fallback_bps
        if avg_daily_volume_vnd >= self.high_threshold_vnd:
            return self.high_liquidity_bps
        if avg_daily_volume_vnd >= self.low_threshold_vnd:
            return self.medium_liquidity_bps
        return self.low_liquidity_bps

    def calculate(
        self,
        reference_price: float,
        quantity: float,
        side: Side,
        avg_daily_volume_vnd: float | None = None,
    ) -> SlippageResult:
        if reference_price <= 0:
            raise ValueError(f"reference_price must be positive, got {reference_price}")
        if quantity < 0:
            raise ValueError(f"quantity must be non-negative, got {quantity}")

        bps = self._bps_for(avg_daily_volume_vnd)
        rate = bps / 10_000

        if side == Side.BUY:
            effective_price = reference_price * (1.0 + rate)
        else:
            effective_price = reference_price * (1.0 - rate)

        slippage_cost = abs(effective_price - reference_price) * quantity

        return SlippageResult(
            reference_price=reference_price,
            effective_price=effective_price,
            slippage_cost=slippage_cost,
            slippage_rate=rate,
            side=side,
        )


class ParticipationRateSlippageModel(SlippageModel):
    """
    Placeholder: slippage proportional to order size relative to ADV.

    Not calibrated for Vietnam market data. Returns FixedBpsSlippageModel
    result with a warning. Implement after calibration with real tick data.
    """

    def calculate(
        self,
        reference_price: float,
        quantity: float,
        side: Side,
        avg_daily_volume_vnd: float | None = None,
    ) -> SlippageResult:
        raise NotImplementedError(
            "ParticipationRateSlippageModel is not calibrated for Vietnam market data. "
            "Use FixedBpsSlippageModel or LiquidityBucketSlippageModel instead."
        )
