"""Portfolio state tracking during backtesting."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Position:
    symbol: str
    quantity: float
    entry_date: datetime.date
    entry_price: float
    entry_cost: float = 0.0

    @property
    def notional(self) -> float:
        return self.quantity * self.entry_price

    def market_value(self, current_price: float) -> float:
        return self.quantity * current_price


@dataclass
class Trade:
    symbol: str
    entry_date: datetime.date
    entry_price: float
    exit_date: Optional[datetime.date]
    exit_price: Optional[float]
    quantity: float
    entry_cost: float
    exit_cost: float
    exit_reason: str = "signal"

    @property
    def gross_pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) * self.quantity

    @property
    def cost(self) -> float:
        return self.entry_cost + self.exit_cost

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.cost

    @property
    def holding_days(self) -> int:
        if self.exit_date is None:
            return 0
        from ..market.calendar import get_trading_days
        # Count trading days held: excludes entry day, includes exit day.
        return len(get_trading_days(self.entry_date, self.exit_date)) - 1

    @property
    def return_pct(self) -> float:
        invested = self.entry_price * self.quantity + self.entry_cost
        if invested == 0:
            return 0.0
        return self.net_pnl / invested

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "entry_date": self.entry_date,
            "entry_price": self.entry_price,
            "exit_date": self.exit_date,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "entry_cost": self.entry_cost,
            "exit_cost": self.exit_cost,
            "cost": self.cost,
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "holding_days": self.holding_days,
            "return_pct": self.return_pct,
            "exit_reason": self.exit_reason,
        }


@dataclass
class PortfolioState:
    """Tracks cash, positions, and trade history during a backtest."""

    initial_capital: float
    cash: float = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    closed_trades: list[Trade] = field(default_factory=list)
    equity_history: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.cash = self.initial_capital

    def open_position(
        self,
        symbol: str,
        date: datetime.date,
        price: float,
        quantity: float,
        entry_cost: float,
    ) -> None:
        total_spend = price * quantity + entry_cost
        if total_spend > self.cash + 1e-6:
            # Scale both quantity and cost proportionally — all costs are proportional
            # to notional, so scaling by the same factor keeps the cost rate exact.
            scale = max(0.0, self.cash / total_spend) if total_spend > 0 else 0.0
            quantity = quantity * scale
            entry_cost = entry_cost * scale
            total_spend = price * quantity + entry_cost
        if quantity <= 0:
            return
        self.cash -= total_spend
        self.positions[symbol] = Position(
            symbol=symbol,
            quantity=quantity,
            entry_date=date,
            entry_price=price,
            entry_cost=entry_cost,
        )

    def close_position(
        self,
        symbol: str,
        date: datetime.date,
        price: float,
        exit_cost: float,
        reason: str = "signal",
    ) -> Optional[Trade]:
        if symbol not in self.positions:
            return None
        pos = self.positions.pop(symbol)
        proceeds = price * pos.quantity - exit_cost
        self.cash += proceeds
        trade = Trade(
            symbol=symbol,
            entry_date=pos.entry_date,
            entry_price=pos.entry_price,
            exit_date=date,
            exit_price=price,
            quantity=pos.quantity,
            entry_cost=pos.entry_cost,
            exit_cost=exit_cost,
            exit_reason=reason,
        )
        self.closed_trades.append(trade)
        return trade

    def market_value(self, prices: dict[str, float]) -> float:
        return sum(pos.quantity * prices.get(sym, pos.entry_price)
                   for sym, pos in self.positions.items())

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + self.market_value(prices)

    def record_equity(
        self,
        date: datetime.date,
        prices: dict[str, float],
    ) -> None:
        mv = self.market_value(prices)
        eq = self.cash + mv
        self.equity_history.append({
            "date": date,
            "cash": self.cash,
            "position_value": mv,
            "equity": eq,
        })
