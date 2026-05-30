"""
TransactionCostModel — facade composing all Vietnam cost components.

This module is the single integration point for the backtest engine and
recommendation validator. It composes:
    brokerage fee  (BrokerFeeProfile)
    VAT            (VATModel)
    sell tax       (SellTaxModel)
    slippage       (SlippageModel)

Backward compatibility:
    TransactionCosts = TransactionCostModel  (alias exported from costs/__init__.py)
    DEFAULT_COSTS = TransactionCostModel.from_legacy()

All existing tests that construct TransactionCosts(commission_rate=...) continue
to work via from_legacy(), which reproduces the old arithmetic exactly (no VAT,
flat commission, combined sell tax).

Formulas:
    Buy side:
        gross_buy_value     = price * quantity
        brokerage_fee       = max(gross_buy_value * rate, min_fee)
        vat                 = brokerage_fee * vat_rate  (if not included and enabled)
        slippage_cost       = gross_buy_value * slippage_rate
        total_buy_cost      = brokerage_fee + vat + slippage_cost
        total_cash_required = gross_buy_value + total_buy_cost

    Sell side:
        gross_sell_value    = price * quantity
        brokerage_fee       = max(gross_sell_value * rate, min_fee)
        vat                 = brokerage_fee * vat_rate  (if not included and enabled)
        sell_tax            = gross_sell_value * sell_tax_rate  [on GROSS, not net]
        slippage_cost       = gross_sell_value * slippage_rate
        total_sell_cost     = brokerage_fee + vat + sell_tax + slippage_cost
        net_sell_proceeds   = gross_sell_value - total_sell_cost

    Realized PnL:
        cost_basis    = buy_price * qty + buy_brokerage_fee + buy_vat
        realized_pnl  = net_sell_proceeds - cost_basis
        net_return    = realized_pnl / cost_basis
"""

from __future__ import annotations

from dataclasses import dataclass

from .brokerage import BrokerFeeProfile, FlatFeeModel
from .taxes import SellTaxModel, TaxProfile
from .vat import VATModel
from .slippage import SlippageModel, FixedBpsSlippageModel, Side


@dataclass(frozen=True)
class TransactionCostBreakdown:
    """Full cost breakdown for one order side (buy or sell)."""
    side: str                        # "buy" or "sell"
    notional: float                  # VND — price * quantity
    brokerage_fee: float             # VND — before VAT
    vat_amount: float                # VND — VAT on brokerage fee
    sell_tax: float                  # VND — 0 for buy; 0.1% of notional for sell
    slippage_cost: float             # VND — market impact estimate
    total_cost: float                # VND — sum of all above cost components
    effective_price: float           # VND/share after slippage

    @property
    def total_rate(self) -> float:
        """Total cost as a fraction of notional (e.g. 0.003 = 0.3%)."""
        return self.total_cost / self.notional if self.notional > 0 else 0.0

    @property
    def net_proceeds(self) -> float:
        """For sell side: cash received after all deductions."""
        if self.side == "sell":
            return self.notional - self.total_cost
        return 0.0  # not meaningful for buy side

    @property
    def total_cash_required(self) -> float:
        """For buy side: total cash outflow including asset cost + all fees."""
        if self.side == "buy":
            return self.notional + self.total_cost
        return 0.0  # not meaningful for sell side

    def describe(self) -> dict:
        return {
            "side": self.side,
            "notional_vnd": f"{self.notional:,.0f}",
            "brokerage_fee_vnd": f"{self.brokerage_fee:,.0f}",
            "vat_vnd": f"{self.vat_amount:,.0f}",
            "sell_tax_vnd": f"{self.sell_tax:,.0f}",
            "slippage_cost_vnd": f"{self.slippage_cost:,.0f}",
            "total_cost_vnd": f"{self.total_cost:,.0f}",
            "total_cost_rate": f"{self.total_rate*100:.4f}%",
        }


class TransactionCostModel:
    """
    Full-featured Vietnam transaction cost model.

    Composes brokerage, VAT, taxes, and slippage into one model.
    The backtest engine calls buy_cost() and sell_cost() and reads
    .total_cost from the returned breakdown.

    Backward compatibility:
        buy_cost(notional) and sell_cost(notional) accept a scalar notional and
        return a TransactionCostBreakdown. Old code reading .total_cost still works.
    """

    def __init__(
        self,
        broker_profile: BrokerFeeProfile | None = None,
        tax_profile: TaxProfile | None = None,
        vat_model: VATModel | None = None,
        slippage_model: SlippageModel | None = None,
    ) -> None:
        import warnings
        self.broker_profile = broker_profile or BrokerFeeProfile.flat_default()
        self.tax_profile = tax_profile or TaxProfile()

        # H4 guard: warn explicitly when fee_includes_vat is unverified (None).
        # Silently defaulting to False can systematically inflate cost estimates
        # by 10% if the broker actually quotes VAT-inclusive rates.
        if vat_model is None:
            fee_vat_status = self.broker_profile.fee_includes_vat
            if fee_vat_status is None:
                warnings.warn(
                    f"Broker profile {self.broker_profile.broker_name!r} has "
                    f"fee_includes_vat=None (unverified). Assuming False (VAT will be "
                    f"added on top of the brokerage rate). Verify with your broker "
                    f"and set fee_includes_vat explicitly to silence this warning.",
                    UserWarning,
                    stacklevel=2,
                )
                fee_vat_status = False
            self.vat_model = VATModel(
                enabled=True,
                rate=0.10,
                fee_includes_vat=fee_vat_status,
            )
        else:
            self.vat_model = vat_model
        self.slippage_model = slippage_model or FixedBpsSlippageModel(bps=10.0)

    def buy_cost(
        self,
        notional: float,
        quantity: float = 1.0,
        price: float | None = None,
        cumulative_daily_notional: float = 0.0,
        avg_daily_volume_vnd: float | None = None,
    ) -> TransactionCostBreakdown:
        """
        Compute all costs for a buy order.

        Args:
            notional:                   price * quantity in VND
            quantity:                   number of shares (for slippage calculation)
            price:                      reference price per share (for slippage)
            cumulative_daily_notional:  total VND traded today (for tiered fee models)
            avg_daily_volume_vnd:       ADV for liquidity-bucket slippage
        """
        ref_price = price if price is not None else (notional / quantity if quantity > 0 else notional)

        brokerage = self.broker_profile.calculate_fee(notional, cumulative_daily_notional)
        vat_result = self.vat_model.calculate(brokerage.base_fee)
        slip = self.slippage_model.calculate(ref_price, quantity, Side.BUY, avg_daily_volume_vnd)

        total_cost = brokerage.base_fee + vat_result.vat_amount + slip.slippage_cost

        return TransactionCostBreakdown(
            side="buy",
            notional=notional,
            brokerage_fee=brokerage.base_fee,
            vat_amount=vat_result.vat_amount,
            sell_tax=0.0,
            slippage_cost=slip.slippage_cost,
            total_cost=total_cost,
            effective_price=slip.effective_price,
        )

    def sell_cost(
        self,
        notional: float,
        quantity: float = 1.0,
        price: float | None = None,
        cumulative_daily_notional: float = 0.0,
        avg_daily_volume_vnd: float | None = None,
    ) -> TransactionCostBreakdown:
        """
        Compute all costs for a sell order.

        Sell tax is applied to GROSS sell value (notional), not net-of-brokerage.
        """
        ref_price = price if price is not None else (notional / quantity if quantity > 0 else notional)

        brokerage = self.broker_profile.calculate_fee(notional, cumulative_daily_notional)
        vat_result = self.vat_model.calculate(brokerage.base_fee)
        tax_result = self.tax_profile.sell_tax.calculate(notional)   # on GROSS
        slip = self.slippage_model.calculate(ref_price, quantity, Side.SELL, avg_daily_volume_vnd)

        total_cost = (
            brokerage.base_fee
            + vat_result.vat_amount
            + tax_result.tax_amount
            + slip.slippage_cost
        )

        return TransactionCostBreakdown(
            side="sell",
            notional=notional,
            brokerage_fee=brokerage.base_fee,
            vat_amount=vat_result.vat_amount,
            sell_tax=tax_result.tax_amount,
            slippage_cost=slip.slippage_cost,
            total_cost=total_cost,
            effective_price=slip.effective_price,
        )

    def round_trip_rate(self) -> float:
        """Approximate round-trip cost rate for documentation / describe()."""
        flat_notional = 1_000_000.0
        buy = self.buy_cost(flat_notional, quantity=1, price=flat_notional)
        sell = self.sell_cost(flat_notional, quantity=1, price=flat_notional)
        return (buy.total_cost + sell.total_cost) / flat_notional

    def describe(self) -> dict:
        return {
            "broker": self.broker_profile.broker_name,
            "account_type": self.broker_profile.account_type,
            "channel": self.broker_profile.channel,
            "vat_enabled": self.vat_model.enabled,
            "vat_rate": f"{self.vat_model.rate*100:.1f}%",
            "fee_includes_vat": self.broker_profile.fee_includes_vat,
            "sell_tax_rate": f"{self.tax_profile.sell_tax.rate*100:.3f}%",
            "round_trip_rate": f"{self.round_trip_rate()*100:.4f}%",
        }

    @classmethod
    def from_legacy(
        cls,
        commission_rate: float = 0.001,
        sell_tax_rate: float = 0.001,
        slippage_bps: float = 10.0,
        min_fee: float = 0.0,
    ) -> "TransactionCostModel":
        """
        Construct a TransactionCostModel from old TransactionCosts parameters.

        Reproduces the EXACT arithmetic of the legacy model:
            - No VAT (vat disabled)
            - Flat commission rate applied to full notional
            - Sell tax on gross sell value
            - Fixed-bps slippage

        Used by test_backtest_engine.py and any code that constructed
        TransactionCosts(commission_rate=...) before this refactor.
        """
        return cls(
            broker_profile=BrokerFeeProfile(
                broker_name="LEGACY",
                account_type="DEFAULT",
                channel="online",
                fee_model=FlatFeeModel(rate=commission_rate, min_fee_vnd=min_fee),
                fee_includes_vat=False,
            ),
            tax_profile=TaxProfile(sell_tax=SellTaxModel(rate=sell_tax_rate)),
            vat_model=VATModel(enabled=False),   # legacy model had no VAT
            slippage_model=FixedBpsSlippageModel(bps=slippage_bps),
        )


# Default instance using legacy-compatible parameters (backward compat)
DEFAULT_COSTS = TransactionCostModel.from_legacy()
