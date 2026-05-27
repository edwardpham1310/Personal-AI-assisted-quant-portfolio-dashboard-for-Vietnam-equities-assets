"""Transaction cost model for Vietnam stock market."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TransactionCosts:
    """
    Configurable trading cost model for Vietnam equities.

    Vietnam-specific defaults:
    - Commission: 0.1% per side (both buy and sell)
    - Sell tax: 0.1% on sell proceeds (securities transfer tax)
    - Slippage: 10 basis points (0.10%) market impact
    - Min fee: 0 (some brokers charge minimum; set as needed)
    """

    commission_rate: float = 0.001   # 0.1% both sides
    sell_tax_rate: float = 0.001     # 0.1% on sell side
    slippage_bps: float = 10.0       # basis points
    min_fee: float = 0.0             # minimum fee per trade in VND

    @property
    def slippage_rate(self) -> float:
        return self.slippage_bps / 10_000

    def buy_cost(self, notional: float) -> float:
        """Total cost of a buy order (commission + slippage)."""
        commission = max(notional * self.commission_rate, self.min_fee)
        slippage = notional * self.slippage_rate
        return commission + slippage

    def sell_cost(self, notional: float) -> float:
        """Total cost of a sell order (commission + sell tax + slippage)."""
        commission = max(notional * self.commission_rate, self.min_fee)
        tax = notional * self.sell_tax_rate
        slippage = notional * self.slippage_rate
        return commission + tax + slippage

    def round_trip_cost_rate(self) -> float:
        """Approximate total cost rate for a complete buy+sell round trip."""
        return (
            self.commission_rate * 2
            + self.sell_tax_rate
            + self.slippage_rate * 2
        )

    def effective_buy_price(self, price: float) -> float:
        """Price per share after buying (price + slippage)."""
        return price * (1 + self.slippage_rate)

    def effective_sell_price(self, price: float) -> float:
        """Effective price per share after selling (price - slippage)."""
        return price * (1 - self.slippage_rate)

    def describe(self) -> dict:
        return {
            "commission_rate": f"{self.commission_rate*100:.3f}%",
            "sell_tax_rate": f"{self.sell_tax_rate*100:.3f}%",
            "slippage_bps": f"{self.slippage_bps:.1f} bps",
            "min_fee": f"{self.min_fee:,.0f} VND",
            "round_trip_cost_rate": f"{self.round_trip_cost_rate()*100:.3f}%",
        }


# Default instance used by the backtest engine
DEFAULT_COSTS = TransactionCosts()
