"""Deterministic mock TradingProvider — for local dev + tests.

Always reports ``mock=True`` so the system-status banner can warn if it
ever lands in production. The Phase 2.5 startup guard
(``_assert_production_order_placement_disabled``) keeps the order
placement flag off; this provider has no submission code anyway.

Mock account IDs supported:
    * ``ACC-DEFAULT``: 50 000 000 VND cash, holds 200 FPT @ 80 000.
    * Any other ID: empty cash + empty positions (lets tests model
      "new account" without seeding fixtures).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

from providers.trading.base import TradingProvider, TradingProviderError
from schemas.trading import (
    CashBalance,
    MaxBuyQuantity,
    MaxSellQuantity,
    OrderBookEntry,
    OrderHistoryEntry,
    StockPosition,
    TradingProviderStatus,
)

_DEFAULT_ACCOUNT = "ACC-DEFAULT"

# A small portfolio of mock positions keyed by account_id.
_MOCK_POSITIONS: dict[str, list[dict]] = {
    _DEFAULT_ACCOUNT: [
        {
            "symbol": "FPT",
            "exchange": "HOSE",
            "quantity": 200,
            "sellable_quantity": 200,
            "pending_quantity": 0,
            "avg_cost": 80000.0,
            "market_price": 86000.0,
        },
        {
            "symbol": "MWG",
            "exchange": "HOSE",
            "quantity": 100,
            "sellable_quantity": 100,
            "pending_quantity": 0,
            "avg_cost": 40000.0,
            "market_price": 42000.0,
        },
    ],
}

_MOCK_CASH: dict[str, dict] = {
    _DEFAULT_ACCOUNT: {
        "cash_balance": 50_000_000.0,
        "buying_power": 48_500_000.0,
        "withdrawable_cash": 30_000_000.0,
        "pending_cash": 1_500_000.0,
    },
}


def _hash01(seed: str) -> float:
    return int.from_bytes(hashlib.sha256(seed.encode()).digest()[:4], "big") / 2**32


class MockTradingProvider(TradingProvider):
    name = "mock-trading"

    async def get_cash_balance(self, account_id: str) -> CashBalance:
        row = _MOCK_CASH.get(account_id, {
            "cash_balance": 0.0,
            "buying_power": 0.0,
            "withdrawable_cash": 0.0,
            "pending_cash": 0.0,
        })
        return CashBalance(
            account_id=account_id,
            cash_balance=row["cash_balance"],
            buying_power=row["buying_power"],
            withdrawable_cash=row["withdrawable_cash"],
            pending_cash=row["pending_cash"],
            currency="VND",
            as_of=datetime.now(UTC),
        )

    async def get_stock_positions(self, account_id: str) -> list[StockPosition]:
        rows = _MOCK_POSITIONS.get(account_id, [])
        now = datetime.now(UTC)
        out: list[StockPosition] = []
        for r in rows:
            mv = r["market_price"] * r["quantity"]
            cost = r["avg_cost"] * r["quantity"]
            out.append(
                StockPosition(
                    account_id=account_id,
                    symbol=r["symbol"],
                    exchange=r["exchange"],
                    quantity=r["quantity"],
                    sellable_quantity=r["sellable_quantity"],
                    pending_quantity=r["pending_quantity"],
                    avg_cost=r["avg_cost"],
                    market_price=r["market_price"],
                    market_value=mv,
                    unrealized_pnl=mv - cost,
                    as_of=now,
                )
            )
        return out

    async def get_max_buy_qty(
        self, account_id: str, symbol: str, price: float
    ) -> MaxBuyQuantity:
        if price <= 0:
            raise TradingProviderError("price must be positive", status_code=400)
        cash = await self.get_cash_balance(account_id)
        # Rough approximation: buying_power / (price * 1.0025). Round down to lot.
        max_raw = int(cash.buying_power / (price * 1.0025))
        max_lot = (max_raw // 100) * 100
        return MaxBuyQuantity(
            account_id=account_id,
            symbol=symbol.upper(),
            price=price,
            max_quantity=max_lot,
            buying_power=cash.buying_power,
            note="Estimated from buying_power; broker's official quote may differ.",
            as_of=datetime.now(UTC),
        )

    async def get_max_sell_qty(
        self, account_id: str, symbol: str
    ) -> MaxSellQuantity:
        positions = await self.get_stock_positions(account_id)
        sym = symbol.upper()
        sellable = next(
            (p.sellable_quantity for p in positions if p.symbol == sym), 0
        )
        return MaxSellQuantity(
            account_id=account_id,
            symbol=sym,
            max_quantity=sellable,
            sellable_quantity=sellable,
            note="Mock provider — sellable equals settled quantity.",
            as_of=datetime.now(UTC),
        )

    async def get_order_book(self, account_id: str) -> list[OrderBookEntry]:
        # Mock: always empty — Phase 2.5 never places orders.
        return []

    async def get_order_history(
        self,
        account_id: str,
        start_date: date,
        end_date: date,
    ) -> list[OrderHistoryEntry]:
        # Mock: empty range, but assert the contract so test failures
        # surface invalid date windows immediately.
        if end_date < start_date:
            raise TradingProviderError(
                "end_date must be >= start_date", status_code=400
            )
        return []

    async def submit_order(
        self,
        *,
        account_id: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: int,
        limit_price: float | None,
    ) -> dict:
        """Mock provider — refuses live submission. The orchestrator's
        dry-run path NEVER calls this method; only the live path does,
        and the mock cannot legitimately fulfil a live order. Returns
        501 so tests that try to bypass the dry-run flag fail loudly.
        """
        raise TradingProviderError(
            "MockTradingProvider does not submit live orders.",
            status_code=501,
        )

    async def status(self) -> TradingProviderStatus:
        return TradingProviderStatus(
            name="mock-trading",
            mock=True,
            read_only=True,
            order_placement_enabled=False,
            status_code="READ_ONLY",
            last_call_ts=datetime.now(UTC),
            last_error_sanitized=None,
            note="Deterministic mock trading provider. No broker contact.",
        )
