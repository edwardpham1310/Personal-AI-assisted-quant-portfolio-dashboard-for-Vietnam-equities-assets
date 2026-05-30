"""
Vietnam T+2 settlement model.

Settlement rules (as of 2024 for HOSE and HNX):
    - Ordinary listed stocks: T+2 trading days
    - ETFs: T+2 trading days
    - Open-ended fund certificates: T+3 or fund-specific (verify with fund)

Settlement behavior modeled here:
    BUY trade on date T:
        - Cash is committed immediately (deducted from settled_cash).
        - Bought shares enter pending_shares (cannot be sold until T+2).
        - At settlement date (T+2): pending_shares → settled_shares.

    SELL trade on date T:
        - Shares leave settled_shares immediately (cannot be re-sold).
        - Net sell proceeds enter pending_cash (not available for new buys).
        - At settlement date (T+2): pending_cash → settled_cash.
        - UNLESS cash advance is used (see costs/cash_advance.py):
          in that case pending_cash is marked ADVANCED and the advance net cash
          is added immediately; NO additional cash is added at settlement.

DEFAULT config:
    allow_sell_unsettled_shares = False
    allow_use_unsettled_cash    = False

T+2 is counted in TRADING DAYS (skips weekends and holidays) using the
Vietnam trading calendar in market/calendar.py.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum

from .calendar import add_trading_days


class AssetType(str, Enum):
    STOCK = "STOCK"       # T+2
    ETF = "ETF"           # T+2
    BOND = "BOND"         # T+1 (not modeled in MVP)
    FUND = "FUND"         # T+3 or fund-specific; placeholder


class SettlementSession(str, Enum):
    AFTERNOON_T_PLUS_2 = "AFTERNOON_T_PLUS_2"
    NEXT_TRADING_DAY = "NEXT_TRADING_DAY"   # funds/bonds may use this


class PendingCashStatus(str, Enum):
    PENDING = "PENDING"       # waiting for T+2 settlement
    ADVANCED = "ADVANCED"     # cash advance drawn; will NOT add cash again at T+2
    SETTLED = "SETTLED"       # settled into settled_cash


SETTLEMENT_DAYS: dict[AssetType, int] = {
    AssetType.STOCK: 2,
    AssetType.ETF: 2,
    AssetType.BOND: 1,
    AssetType.FUND: 3,
}


@dataclass
class SettlementRule:
    asset_type: AssetType = AssetType.STOCK
    settlement_days: int = 2

    def settlement_date(self, trade_date: datetime.date) -> datetime.date:
        """Return settlement date = trade_date + settlement_days trading days."""
        return add_trading_days(trade_date, self.settlement_days)


@dataclass
class PendingCashEntry:
    """One pending cash item from a sell trade."""
    entry_id: str                           # unique id, e.g. f"{symbol}_{trade_date}_{idx}"
    symbol: str
    sell_date: datetime.date
    settlement_date: datetime.date          # when this becomes settled_cash
    gross_sell_value: float                 # VND — price * quantity
    net_amount: float                       # VND — after all sell costs
    status: PendingCashStatus = PendingCashStatus.PENDING
    advance_net_cash: float = 0.0           # VND — net cash from advance (if ADVANCED)
    advance_fee: float = 0.0               # VND — fee charged for advance


@dataclass
class PendingSharesEntry:
    """One pending shares item from a buy trade."""
    entry_id: str
    symbol: str
    buy_date: datetime.date
    settlement_date: datetime.date
    quantity: int                           # whole shares only
    buy_price: float                        # VND per share at purchase
    settled: bool = False                   # set True by advance_date(); prevents double-credit


class SettlementLedger:
    """
    In-memory settlement ledger for one portfolio / backtest run.

    Tracks pending cash (from sells) and pending shares (from buys).

    Key guarantee: pending_cash is NEVER automatically added to settled_cash
    in available_cash(). It becomes settled_cash only when advance_date() is
    called with a date >= entry.settlement_date AND the entry is PENDING (not
    ADVANCED). ADVANCED entries are closed at settlement with zero cash impact
    (the advance already credited the cash on draw date).

    Usage during simulation:
        1. Call advance_date(today) at the start of each bar to settle items.
        2. Call record_buy / record_sell after each executed trade.
        3. Query available_cash(today) / available_shares(symbol, today).
    """

    def __init__(self) -> None:
        self._pending_cash: list[PendingCashEntry] = []
        self._pending_shares: list[PendingSharesEntry] = []
        self._settled_cash: float = 0.0
        self._settled_shares: dict[str, int] = {}
        self._entry_counter: int = 0

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _new_id(self, prefix: str) -> str:
        self._entry_counter += 1
        return f"{prefix}_{self._entry_counter}"

    # ── Recording trades ─────────────────────────────────────────────────────

    def record_buy(
        self,
        trade_date: datetime.date,
        symbol: str,
        quantity: int,
        settlement_date: datetime.date,
        buy_price: float = 0.0,
    ) -> None:
        """Record a buy trade: shares go into pending until settlement date."""
        if settlement_date < trade_date:
            raise ValueError(
                f"settlement_date {settlement_date} cannot be before trade_date {trade_date}. "
                f"Use add_trading_days(trade_date, +n) to compute settlement."
            )
        if quantity <= 0:
            raise ValueError(f"quantity must be positive; got {quantity}")
        entry = PendingSharesEntry(
            entry_id=self._new_id(f"BUY_{symbol}"),
            symbol=symbol,
            buy_date=trade_date,
            settlement_date=settlement_date,
            quantity=quantity,
            buy_price=buy_price,
        )
        self._pending_shares.append(entry)

    def record_sell(
        self,
        trade_date: datetime.date,
        symbol: str,
        quantity: int,
        net_proceed: float,
        gross_sell_value: float,
        settlement_date: datetime.date,
    ) -> str:
        """
        Record a sell trade: net proceeds go into pending until settlement date.

        Returns the entry_id for cash advance operations.
        """
        if settlement_date < trade_date:
            raise ValueError(
                f"settlement_date {settlement_date} cannot be before trade_date {trade_date}."
            )
        if quantity <= 0:
            raise ValueError(f"quantity must be positive; got {quantity}")
        if net_proceed < 0:
            raise ValueError(f"net_proceed must be non-negative; got {net_proceed}")
        entry_id = self._new_id(f"SELL_{symbol}")
        entry = PendingCashEntry(
            entry_id=entry_id,
            symbol=symbol,
            sell_date=trade_date,
            settlement_date=settlement_date,
            gross_sell_value=gross_sell_value,
            net_amount=net_proceed,
            status=PendingCashStatus.PENDING,
        )
        self._pending_cash.append(entry)
        return entry_id

    def apply_cash_advance(
        self,
        entry_id: str,
        advance_net_cash: float,
        advance_fee: float,
    ) -> None:
        """
        Mark a pending cash entry as ADVANCED and record the advance net cash.

        Double-count prevention: entries marked ADVANCED are NOT settled into
        settled_cash when their settlement_date arrives.

        Args:
            entry_id:         ID returned from record_sell().
            advance_net_cash: VND credited now = advanced_amount - total_fee.
            advance_fee:      Total fee charged for the advance.
        """
        for entry in self._pending_cash:
            if entry.entry_id == entry_id:
                if entry.status != PendingCashStatus.PENDING:
                    raise ValueError(
                        f"Entry {entry_id} is already {entry.status.value}; "
                        "cannot apply advance again."
                    )
                entry.status = PendingCashStatus.ADVANCED
                entry.advance_net_cash = advance_net_cash
                entry.advance_fee = advance_fee
                self._settled_cash += advance_net_cash
                return
        raise KeyError(f"PendingCashEntry with id={entry_id!r} not found.")

    # ── Advancing time (settlement) ───────────────────────────────────────────

    def advance_date(self, as_of_date: datetime.date) -> dict:
        """
        Settle all pending items whose settlement_date <= as_of_date.

        Call this at the start of each trading day before querying availability.

        Returns a dict with newly settled amounts for observability.
        """
        newly_settled_cash = 0.0
        newly_settled_shares: dict[str, int] = {}

        for entry in self._pending_cash:
            if entry.settlement_date <= as_of_date and entry.status == PendingCashStatus.PENDING:
                entry.status = PendingCashStatus.SETTLED
                self._settled_cash += entry.net_amount
                newly_settled_cash += entry.net_amount

        for entry in self._pending_shares:
            if entry.settlement_date <= as_of_date and not entry.settled:
                entry.settled = True
                self._settled_shares[entry.symbol] = (
                    self._settled_shares.get(entry.symbol, 0) + entry.quantity
                )
                newly_settled_shares[entry.symbol] = (
                    newly_settled_shares.get(entry.symbol, 0) + entry.quantity
                )

        return {
            "newly_settled_cash": newly_settled_cash,
            "newly_settled_shares": newly_settled_shares,
        }

    # ── Initialise with cash/shares ────────────────────────────────────────

    def set_initial_cash(self, amount: float) -> None:
        """Set the initial settled cash (e.g. from PortfolioState.initial_capital)."""
        self._settled_cash = amount

    def deduct_cash(self, amount: float) -> None:
        """Deduct cash for a buy order (committed immediately at trade time)."""
        self._settled_cash -= amount

    def deduct_settled_shares(self, symbol: str, quantity: int) -> None:
        """Remove settled shares when a sell is executed."""
        current = self._settled_shares.get(symbol, 0)
        if quantity > current:
            raise ValueError(
                f"Cannot deduct {quantity} settled shares of {symbol}; "
                f"only {current} are settled."
            )
        self._settled_shares[symbol] = current - quantity

    def add_settled_shares(self, symbol: str, quantity: int) -> None:
        """Directly add settled shares (e.g. for initial position setup)."""
        self._settled_shares[symbol] = self._settled_shares.get(symbol, 0) + quantity

    # ── Availability queries ──────────────────────────────────────────────────

    @property
    def settled_cash(self) -> float:
        return self._settled_cash

    def available_cash_on(self, as_of_date: datetime.date) -> float:
        """
        Return settled cash that is immediately available for new buy orders.

        This is settled_cash ONLY. Pending cash from unsettled sells is NOT
        included here (it requires cash advance to access early).

        IMPORTANT: Auto-advances settlement internally to ``as_of_date`` to
        ensure any entries whose ``settlement_date <= as_of_date`` are
        included in ``settled_cash``. This makes the query date-aware.
        """
        self.advance_date(as_of_date)
        return self._settled_cash

    def available_shares_on(self, symbol: str, as_of_date: datetime.date) -> int:
        """
        Return settled shares of ``symbol`` available to sell on ``as_of_date``.

        Pending shares (bought but not yet settled) are NOT included.

        IMPORTANT: Auto-advances settlement internally to ``as_of_date`` so
        recently settled shares are included.
        """
        self.advance_date(as_of_date)
        return self._settled_shares.get(symbol, 0)

    def pending_cash_total(self) -> float:
        """Total pending cash (PENDING status only — not yet available)."""
        return sum(
            e.net_amount for e in self._pending_cash
            if e.status == PendingCashStatus.PENDING
        )

    def pending_shares_total(self, symbol: str) -> int:
        """Total pending (unsettled) shares of ``symbol``."""
        return sum(
            e.quantity for e in self._pending_shares
            if e.symbol == symbol and not e.settled
        )

    def total_equity_estimate(self, market_prices: dict[str, float]) -> float:
        """
        Rough equity estimate for observability.

        = settled_cash + pending_cash(PENDING) + settled_positions_MtM
        Does NOT include pending share positions (future value unclear).
        """
        equity = self._settled_cash + self.pending_cash_total()
        for symbol, qty in self._settled_shares.items():
            price = market_prices.get(symbol, 0.0)
            equity += qty * price
        return equity

    def snapshot(self) -> dict:
        """Return a snapshot dict for logging / equity curve recording."""
        return {
            "settled_cash": self._settled_cash,
            "pending_cash": self.pending_cash_total(),
            "pending_cash_entries": len([e for e in self._pending_cash
                                         if e.status == PendingCashStatus.PENDING]),
            "advanced_cash_entries": len([e for e in self._pending_cash
                                          if e.status == PendingCashStatus.ADVANCED]),
            "settled_shares": dict(self._settled_shares),
        }
