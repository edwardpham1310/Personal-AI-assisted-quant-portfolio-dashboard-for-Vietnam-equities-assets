"""
Portfolio ledger with T+2 settlement awareness.

This ledger is used for:
    - Recommendation validation (are there enough settled cash/shares?)
    - Future strict backtest engine (Phase 3)
    - Portfolio state display in dashboard

It wraps SettlementLedger (market/settlement.py) and TransactionCostModel
(costs/transaction.py) to provide a unified, auditable portfolio state.

Key accounting invariants:
    1. settled_cash + pending_cash = total_cash_on_hand (unrealised)
    2. pending_cash is NOT available for new buys (unless advance enabled)
    3. ADVANCED pending cash does NOT re-appear at settlement
    4. settled_shares are available to sell; pending_shares are not
    5. advance_liability is subtracted for net-worth calculation
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from ..market.settlement import (
    SettlementLedger,
    SettlementRule,
    AssetType,
    SETTLEMENT_DAYS,
)
from ..market.calendar import add_trading_days
from ..costs.transaction import TransactionCostModel, DEFAULT_COSTS
from ..costs.cash_advance import CashAdvanceModel, CashAdvanceProfile, CASH_ADVANCE_DISABLED


@dataclass
class AdvanceLiability:
    """One outstanding cash advance liability."""
    advance_id: str
    entry_id: str                    # links to settlement ledger entry
    advance_date: datetime.date
    settlement_date: datetime.date
    advanced_amount: float           # VND advanced
    advance_fee: float               # VND total fee charged
    net_cash_credited: float         # VND actually credited to settled_cash
    status: str = "PENDING"          # PENDING | SETTLED


@dataclass
class LedgerSnapshot:
    """Point-in-time snapshot of the portfolio ledger state."""
    as_of_date: datetime.date
    settled_cash: float
    pending_cash: float              # unsettled sell proceeds (NOT available for buys)
    total_cash: float                # settled + pending (informational)
    settled_shares: dict[str, int]   # available to sell
    pending_shares: dict[str, int]   # locked until T+2
    advance_liabilities: float       # total outstanding advance principal + fee
    realized_pnl: float
    unrealized_pnl: float
    total_equity: float              # settled_cash + MtM(settled_shares) + MtM(pending_shares)


class PortfolioLedger:
    """
    Settlement-aware portfolio ledger.

    Usage for recommendation validation:
        ledger = PortfolioLedger(initial_capital=100_000_000)
        ledger.process_buy(date, "FPT", quantity=1000, price=86_000)
        # 2 trading days later:
        ledger.advance_date(settlement_date)
        # Now can sell:
        ok = ledger.can_sell("FPT", 1000)

    Configuration flags:
        allow_use_unsettled_cash:   If False (default), buys require settled_cash only.
        allow_sell_unsettled_shares: If False (default), sells require settled_shares only.
    """

    def __init__(
        self,
        initial_capital: float = 0.0,
        cost_model: TransactionCostModel | None = None,
        cash_advance_model: CashAdvanceModel | None = None,
        allow_use_unsettled_cash: bool = False,
        allow_sell_unsettled_shares: bool = False,
        asset_type: AssetType = AssetType.STOCK,
    ) -> None:
        self._ledger = SettlementLedger()
        self._ledger.set_initial_cash(initial_capital)
        self._cost_model = cost_model or DEFAULT_COSTS
        self._advance_model = cash_advance_model
        self._allow_use_unsettled_cash = allow_use_unsettled_cash
        self._allow_sell_unsettled_shares = allow_sell_unsettled_shares
        self._settlement_rule = SettlementRule(
            asset_type=asset_type,
            settlement_days=SETTLEMENT_DAYS[asset_type],
        )
        self._advance_liabilities: list[AdvanceLiability] = []
        self._realized_pnl: float = 0.0
        self._cost_basis: dict[str, float] = {}   # symbol → cost per share (avg)
        self._position_qty: dict[str, int] = {}   # symbol → total settled + pending qty held

    # ── Date advancement ─────────────────────────────────────────────────────

    def advance_date(self, as_of_date: datetime.date) -> dict:
        """Settle all items due through as_of_date. Call at start of each trading day."""
        result = self._ledger.advance_date(as_of_date)
        # Close advance liabilities
        for adv in self._advance_liabilities:
            if adv.status == "PENDING" and adv.settlement_date <= as_of_date:
                adv.status = "SETTLED"
        return result

    # ── Trade recording ───────────────────────────────────────────────────────

    def process_buy(
        self,
        trade_date: datetime.date,
        symbol: str,
        quantity: int,
        price: float,
    ) -> dict[str, Any]:
        """
        Execute a buy: deduct settled_cash, record pending share delivery.

        Returns a breakdown dict for audit/reporting.
        """
        notional = price * quantity
        cost_bd = self._cost_model.buy_cost(
            notional=notional, quantity=quantity, price=price
        )
        total_required = notional + cost_bd.total_cost
        settlement_date = self._settlement_rule.settlement_date(trade_date)

        # Deduct cash immediately
        self._ledger.deduct_cash(total_required)

        # Record pending share delivery
        self._ledger.record_buy(trade_date, symbol, quantity, settlement_date, price)

        # Update position tracking and cost basis.
        # Cost basis per Vietnam quant convention (Phase 1 spec):
        #   cost_basis = entry_price * qty + brokerage_fee + brokerage_vat
        # Slippage is NOT included in cost basis — it is already embedded in the
        # execution price (the effective_price the trader paid). Including it
        # again would double-count slippage and understate realized PnL.
        existing_qty = self._position_qty.get(symbol, 0)
        existing_basis = self._cost_basis.get(symbol, 0.0)
        new_total_qty = existing_qty + quantity
        if quantity > 0:
            allocable_cost = cost_bd.brokerage_fee + cost_bd.vat_amount
            cost_basis_per_share = price + (allocable_cost / quantity)
        else:
            cost_basis_per_share = 0.0
        if new_total_qty > 0:
            self._cost_basis[symbol] = (
                existing_basis * existing_qty + cost_basis_per_share * quantity
            ) / new_total_qty
        self._position_qty[symbol] = new_total_qty

        return {
            "action": "BUY",
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "notional": notional,
            "brokerage_fee": cost_bd.brokerage_fee,
            "vat": cost_bd.vat_amount,
            "slippage": cost_bd.slippage_cost,
            "total_cost": cost_bd.total_cost,
            "total_cash_required": total_required,
            "settlement_date": settlement_date,
        }

    def process_sell(
        self,
        trade_date: datetime.date,
        symbol: str,
        quantity: int,
        price: float,
    ) -> dict[str, Any]:
        """
        Execute a sell: remove settled_shares, record pending cash proceeds.

        Returns a breakdown dict for audit/reporting.
        """
        notional = price * quantity
        cost_bd = self._cost_model.sell_cost(
            notional=notional, quantity=quantity, price=price
        )
        net_proceeds = notional - cost_bd.total_cost
        settlement_date = self._settlement_rule.settlement_date(trade_date)

        # Remove shares immediately
        self._ledger.deduct_settled_shares(symbol, quantity)

        # Record pending cash
        entry_id = self._ledger.record_sell(
            trade_date=trade_date,
            symbol=symbol,
            quantity=quantity,
            net_proceed=net_proceeds,
            gross_sell_value=notional,
            settlement_date=settlement_date,
        )

        # Realized PnL
        cost_basis = self._cost_basis.get(symbol, 0.0)
        allocated_cost = cost_basis * quantity
        realized = net_proceeds - allocated_cost
        self._realized_pnl += realized

        # Update position tracking
        self._position_qty[symbol] = max(0, self._position_qty.get(symbol, 0) - quantity)

        return {
            "action": "SELL",
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "notional": notional,
            "brokerage_fee": cost_bd.brokerage_fee,
            "vat": cost_bd.vat_amount,
            "sell_tax": cost_bd.sell_tax,
            "slippage": cost_bd.slippage_cost,
            "total_cost": cost_bd.total_cost,
            "net_proceeds": net_proceeds,
            "pending_entry_id": entry_id,
            "settlement_date": settlement_date,
            "allocated_cost_basis": allocated_cost,
            "realized_pnl": realized,
        }

    # ── Cash advance ─────────────────────────────────────────────────────────

    def apply_advance(
        self,
        entry_id: str,
        advanced_amount: float,
        advance_days: int,
        advance_date: datetime.date,
        settlement_date: datetime.date,
    ) -> dict[str, Any]:
        """
        Apply a cash advance against a pending sell entry.

        Double-count prevention: the entry_id is marked ADVANCED and will NOT
        contribute to settled_cash when settlement_date arrives.
        """
        if self._advance_model is None:
            raise ValueError("No CashAdvanceModel configured. Set cash_advance_model in PortfolioLedger.")

        result = self._advance_model.calculate(advanced_amount, advance_days)
        self._ledger.apply_cash_advance(entry_id, result.net_advanced_cash, result.total_advance_fee)

        adv_id = f"ADV_{entry_id}"
        self._advance_liabilities.append(AdvanceLiability(
            advance_id=adv_id,
            entry_id=entry_id,
            advance_date=advance_date,
            settlement_date=settlement_date,
            advanced_amount=advanced_amount,
            advance_fee=result.total_advance_fee,
            net_cash_credited=result.net_advanced_cash,
        ))

        return {
            "advance_id": adv_id,
            "advanced_amount": advanced_amount,
            "advance_days": advance_days,
            "fee_before_vat": result.fee_before_vat,
            "vat_on_fee": result.vat_amount,
            "total_advance_fee": result.total_advance_fee,
            "net_advanced_cash": result.net_advanced_cash,
            "settlement_date": settlement_date,
        }

    # ── Availability queries ──────────────────────────────────────────────────

    def available_cash(self, as_of_date: datetime.date) -> float:
        """
        Cash available for new buy orders.

        By default: settled_cash only.
        If allow_use_unsettled_cash=True: settled_cash + pending_cash.
        """
        base = self._ledger.available_cash_on(as_of_date)
        if self._allow_use_unsettled_cash:
            base += self._ledger.pending_cash_total()
        return base

    def available_shares(self, symbol: str, as_of_date: datetime.date) -> int:
        """
        Shares available to sell for ``symbol``.

        By default: settled_shares only.
        If allow_sell_unsettled_shares=True: includes pending_shares.
        """
        base = self._ledger.available_shares_on(symbol, as_of_date)
        if self._allow_sell_unsettled_shares:
            base += self._ledger.pending_shares_total(symbol)
        return base

    def can_buy(self, required_cash: float, as_of_date: datetime.date) -> bool:
        return self.available_cash(as_of_date) >= required_cash - 1.0

    def can_sell(self, symbol: str, quantity: int, as_of_date: datetime.date) -> bool:
        return self.available_shares(symbol, as_of_date) >= quantity

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(
        self,
        as_of_date: datetime.date,
        market_prices: dict[str, float] | None = None,
    ) -> LedgerSnapshot:
        prices = market_prices or {}
        snap = self._ledger.snapshot()
        settled_shares = snap["settled_shares"]

        unrealized = sum(
            settled_shares.get(sym, 0) * prices.get(sym, 0.0)
            for sym in settled_shares
        )
        total_equity = snap["settled_cash"] + snap["pending_cash"] + unrealized

        pending_shares_dict: dict[str, int] = {}
        for entry in self._ledger._pending_shares:
            if not entry.settled:
                pending_shares_dict[entry.symbol] = (
                    pending_shares_dict.get(entry.symbol, 0) + entry.quantity
                )

        advance_total = sum(
            a.advanced_amount + a.advance_fee
            for a in self._advance_liabilities
            if a.status == "PENDING"
        )

        return LedgerSnapshot(
            as_of_date=as_of_date,
            settled_cash=snap["settled_cash"],
            pending_cash=snap["pending_cash"],
            total_cash=snap["settled_cash"] + snap["pending_cash"],
            settled_shares={k: v for k, v in settled_shares.items() if v > 0},
            pending_shares={k: v for k, v in pending_shares_dict.items() if v > 0},
            advance_liabilities=advance_total,
            realized_pnl=self._realized_pnl,
            unrealized_pnl=unrealized,
            total_equity=total_equity,
        )
