"""
Broker fee models for Vietnam stock market.

Brokerage commission in Vietnam:
    - Applied on BOTH buy and sell sides.
    - Calculated on the matched transaction value = price × quantity.
    - Subject to 10% VAT (handled by costs/vat.py, not here).
    - Minimum fee per order varies by broker.

Tiered fee structure (VNDIRECT DBA as example):
    - Rate depends on cumulative daily matched value (NOT marginal brackets).
    - The tier rate applies to the FULL order notional once the daily threshold
      is reached — it is NOT an income-tax-style marginal calculation.

DISCLAIMER: Published fee schedules change. Verify your exact rate with your
broker account documentation before running any backtest.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BrokerageResult:
    """Result of a brokerage fee calculation (before VAT)."""
    notional: float           # VND — the transaction value the fee is based on
    base_fee: float           # VND — fee before VAT
    min_fee_applied: bool     # True if minimum fee overrode the rate-based amount
    rate_used: float          # the per-unit rate actually applied


@dataclass(frozen=True)
class FeeTier:
    """A single tier in a tiered fee schedule."""
    min_daily_value: float    # VND — cumulative daily value threshold
    fee_rate: float           # decimal, e.g. 0.0015 = 0.15%


class BrokerFeeModel(ABC):
    @abstractmethod
    def calculate(
        self,
        notional: float,
        cumulative_daily_notional: float = 0.0,
    ) -> BrokerageResult: ...


@dataclass
class FlatFeeModel(BrokerFeeModel):
    """
    Flat-rate brokerage fee.

    Formula:
        base_fee = max(notional * rate, min_fee_vnd)

    Args:
        rate: Per-transaction rate as decimal (e.g. 0.0015 = 0.15%).
        min_fee_vnd: Minimum fee in VND per order.
    """
    rate: float = 0.0015           # 0.15% — SSI ACTIVE online retail default
    min_fee_vnd: float = 0.0

    def calculate(
        self,
        notional: float,
        cumulative_daily_notional: float = 0.0,
    ) -> BrokerageResult:
        if notional < 0:
            raise ValueError(f"notional must be non-negative, got {notional}")
        raw_fee = notional * self.rate
        base_fee = max(raw_fee, self.min_fee_vnd)
        return BrokerageResult(
            notional=notional,
            base_fee=base_fee,
            min_fee_applied=(base_fee == self.min_fee_vnd and self.min_fee_vnd > 0 and raw_fee < self.min_fee_vnd),
            rate_used=self.rate,
        )


@dataclass
class TieredFeeModel(BrokerFeeModel):
    """
    Tiered brokerage fee by cumulative daily traded value.

    The tier rate applies to the FULL order notional — NOT to the amount above
    the threshold (this is NOT a marginal/bracket system).

    Tiers must be provided sorted descending by ``min_daily_value`` (highest
    first). The first tier whose ``min_daily_value <= cumulative_daily_notional``
    is applied.

    Args:
        tiers: List of FeeTier objects, sorted descending by min_daily_value.
        min_fee_vnd: Minimum fee in VND per order.

    Example (VNDIRECT DBA broker-assisted):
        tiers = [
            FeeTier(800_000_000, 0.0015),
            FeeTier(400_000_000, 0.0020),
            FeeTier(250_000_000, 0.0025),
            FeeTier( 80_000_000, 0.0030),
            FeeTier(          0, 0.0035),
        ]
    """
    tiers: list[FeeTier] = field(default_factory=list)
    min_fee_vnd: float = 0.0

    def __post_init__(self) -> None:
        if self.tiers:
            # Ensure tiers are sorted descending by min_daily_value
            self.tiers = sorted(self.tiers, key=lambda t: t.min_daily_value, reverse=True)

    def _rate_for(self, cumulative: float) -> float:
        """Return the applicable rate given cumulative daily traded value."""
        for tier in self.tiers:
            if cumulative >= tier.min_daily_value:
                return tier.fee_rate
        # Fallback to last tier (lowest threshold) if none match
        return self.tiers[-1].fee_rate if self.tiers else 0.0

    def calculate(
        self,
        notional: float,
        cumulative_daily_notional: float = 0.0,
    ) -> BrokerageResult:
        if notional < 0:
            raise ValueError(f"notional must be non-negative, got {notional}")
        if not self.tiers:
            raise ValueError("TieredFeeModel has no tiers configured.")

        rate = self._rate_for(cumulative_daily_notional)
        raw_fee = notional * rate
        base_fee = max(raw_fee, self.min_fee_vnd)
        return BrokerageResult(
            notional=notional,
            base_fee=base_fee,
            min_fee_applied=(base_fee == self.min_fee_vnd and self.min_fee_vnd > 0 and raw_fee < self.min_fee_vnd),
            rate_used=rate,
        )


@dataclass
class BrokerFeeProfile:
    """
    Named broker fee configuration.

    VAT is handled separately (see costs/vat.py). This class only returns the
    brokerage commission before VAT.

    Args:
        broker_name: Broker identifier (SSI, VNDIRECT, CUSTOM, etc.).
        account_type: Account package (ACTIVE, DTA, DBA, CUSTOM, etc.).
        channel: Trading channel (online, broker_assisted, call_center).
        fee_model: The fee calculation model to use.
        fee_includes_vat: Whether the published rate already embeds VAT.
            Pass this flag to VATModel to prevent double-counting.
    """
    broker_name: str
    account_type: str
    channel: str
    fee_model: BrokerFeeModel
    fee_includes_vat: bool | None = None   # None = unknown / must be verified

    def calculate_fee(
        self,
        notional: float,
        cumulative_daily_notional: float = 0.0,
    ) -> BrokerageResult:
        return self.fee_model.calculate(notional, cumulative_daily_notional)

    # ---- Factory methods for common profiles ---------------------------------

    @classmethod
    def ssi_active_online(cls) -> "BrokerFeeProfile":
        """SSI ACTIVE account, online channel — flat 0.15%, min fee 0 VND.

        VERIFY: Confirm with your actual SSI account fee schedule.
        fee_includes_vat is None — must be verified manually.
        """
        return cls(
            broker_name="SSI",
            account_type="ACTIVE",
            channel="online",
            fee_model=FlatFeeModel(rate=0.0015, min_fee_vnd=0.0),
            fee_includes_vat=None,
        )

    @classmethod
    def vndirect_dta_online(cls) -> "BrokerFeeProfile":
        """VNDIRECT DTA account, online channel — flat 0.1%, min fee 0 VND.

        VERIFY: Confirm with your actual VNDIRECT account fee schedule.
        fee_includes_vat is None — must be verified manually.
        """
        return cls(
            broker_name="VNDIRECT",
            account_type="DTA",
            channel="online",
            fee_model=FlatFeeModel(rate=0.001, min_fee_vnd=0.0),
            fee_includes_vat=None,
        )

    @classmethod
    def vndirect_dba_broker_assisted(cls) -> "BrokerFeeProfile":
        """VNDIRECT DBA account, broker-assisted channel — tiered fee schedule.

        VERIFY: Confirm with your actual VNDIRECT account fee schedule.
        """
        tiers = [
            FeeTier(min_daily_value=800_000_000, fee_rate=0.0015),
            FeeTier(min_daily_value=400_000_000, fee_rate=0.0020),
            FeeTier(min_daily_value=250_000_000, fee_rate=0.0025),
            FeeTier(min_daily_value= 80_000_000, fee_rate=0.0030),
            FeeTier(min_daily_value=          0, fee_rate=0.0035),
        ]
        return cls(
            broker_name="VNDIRECT",
            account_type="DBA",
            channel="broker_assisted",
            fee_model=TieredFeeModel(tiers=tiers, min_fee_vnd=0.0),
            fee_includes_vat=None,
        )

    @classmethod
    def custom(
        cls,
        rate: float = 0.0015,
        min_fee_vnd: float = 0.0,
        fee_includes_vat: bool = False,
    ) -> "BrokerFeeProfile":
        """Generic custom profile — set rate to your actual broker rate."""
        return cls(
            broker_name="CUSTOM",
            account_type="CUSTOM",
            channel="online",
            fee_model=FlatFeeModel(rate=rate, min_fee_vnd=min_fee_vnd),
            fee_includes_vat=fee_includes_vat,
        )

    @classmethod
    def flat_default(cls) -> "BrokerFeeProfile":
        """Backward-compatible flat 0.1% profile matching old TransactionCosts defaults."""
        return cls(
            broker_name="CUSTOM",
            account_type="DEFAULT",
            channel="online",
            fee_model=FlatFeeModel(rate=0.001, min_fee_vnd=0.0),
            fee_includes_vat=False,
        )
