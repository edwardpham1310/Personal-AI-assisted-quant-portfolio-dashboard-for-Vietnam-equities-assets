"""Execution model: position sizing and order construction."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..market.costs import TransactionCosts


class ExecutionMode(str, Enum):
    NEXT_OPEN = "next_open"       # Signal on T → execute at T+1 open (default, no lookahead)
    NEXT_CLOSE = "next_close"     # Signal on T → execute at T+1 close
    SAME_CLOSE = "same_close"     # Signal on T → execute at T close (ONLY for academic comparison)


class PositionSizingMethod(str, Enum):
    FIXED_CASH = "fixed_cash"           # Fixed VND amount per trade
    PCT_EQUITY = "pct_equity"           # % of current equity
    EQUAL_WEIGHT = "equal_weight"       # 1/N of equity (for portfolio)
    FULL_EQUITY = "full_equity"         # 100% of available cash (single asset)


@dataclass
class ExecutionConfig:
    """Configuration for order execution and position sizing."""

    mode: ExecutionMode = ExecutionMode.NEXT_OPEN
    sizing_method: PositionSizingMethod = PositionSizingMethod.FULL_EQUITY
    fixed_cash_amount: float = 10_000_000  # 10M VND (used with FIXED_CASH)
    pct_equity: float = 1.0               # used with PCT_EQUITY
    max_position_pct: float = 1.0         # max fraction of equity in one position
    allow_fractional_shares: bool = True   # True = fractional qty (for VND-based sizing)
    allow_short: bool = False

    def compute_quantity(
        self,
        available_cash: float,
        current_equity: float,
        price: float,
        n_symbols: int = 1,
        costs: "TransactionCosts | None" = None,
    ) -> float:
        """Compute the number of shares to buy given equity and price.

        When costs are provided, the notional is shrunk by the buy-side cost rate so
        that price * qty + buy_cost(price * qty) fits within available_cash.
        """
        if price <= 0:
            return 0.0

        if self.sizing_method == PositionSizingMethod.FULL_EQUITY:
            notional = min(available_cash, current_equity * self.max_position_pct)
        elif self.sizing_method == PositionSizingMethod.PCT_EQUITY:
            notional = current_equity * self.pct_equity
        elif self.sizing_method == PositionSizingMethod.FIXED_CASH:
            notional = self.fixed_cash_amount
        elif self.sizing_method == PositionSizingMethod.EQUAL_WEIGHT:
            notional = current_equity / max(n_symbols, 1)
        else:
            notional = available_cash

        notional = min(notional, available_cash)

        # Reserve capacity for buy-side costs so total_spend stays within cash.
        # price * qty + buy_cost_rate * price * qty <= notional
        # => qty <= notional / (price * (1 + buy_cost_rate))
        if costs is not None:
            buy_cost_rate = costs.commission_rate + costs.slippage_rate
            notional = notional / (1.0 + buy_cost_rate)

        qty = notional / price

        if not self.allow_fractional_shares:
            qty = float(int(qty))

        return max(qty, 0.0)
