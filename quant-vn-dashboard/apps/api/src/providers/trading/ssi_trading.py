"""SSI FastConnect Trading provider — read-only stub for Phase 2.5.

This class exists so the deps factory has something to return when an
operator sets ``SSI_TRADING_USE_MOCK=false`` with real credentials, but
the underlying SSI Trading REST calls are NOT implemented yet — that is
a Phase 3 milestone with its own review.

Every method raises ``TradingProviderError(status_code=501,
NOT_IMPLEMENTED)``. The route layer turns that into a clean response
("503 Service Unavailable" or "501 Not Implemented"). Crucially:

* The stub never reaches SSI — there is no HTTP client constructed
  inside the read methods.
* There is no ``place_order`` method (the base class forbids it).
* The status() method emits ``NOT_IMPLEMENTED`` so the system-status
  view explains the situation to operators.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

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


_NOT_IMPLEMENTED_MSG = (
    "SSI Trading read-only sync is not implemented in Phase 2.5. "
    "Use SSI_TRADING_USE_MOCK=true for development, or wait for Phase 3."
)


class SSITradingProvider(TradingProvider):
    """Phase 2.5 stub — accepts credentials but does not call SSI Trading.

    The class deliberately stores credentials only on ``__init__`` and
    never touches them again, so a Phase 3 implementation can wire the
    REST calls without changing the deps factory.
    """

    name = "ssi-trading"

    def __init__(
        self,
        *,
        consumer_id: str,
        consumer_secret: str,
        base_url: str,
        timeout: float = 10.0,
    ) -> None:
        if not consumer_id or not consumer_secret:
            raise TradingProviderError(
                "SSI Trading credentials are missing.", status_code=503
            )
        if not base_url.startswith("https://"):
            raise TradingProviderError(
                "SSI Trading base_url must use HTTPS.", status_code=500
            )
        self._consumer_id = consumer_id
        self._consumer_secret = consumer_secret
        self._base_url = base_url
        self._timeout = timeout

    async def get_cash_balance(self, account_id: str) -> CashBalance:
        raise TradingProviderError(_NOT_IMPLEMENTED_MSG, status_code=501)

    async def get_stock_positions(self, account_id: str) -> list[StockPosition]:
        raise TradingProviderError(_NOT_IMPLEMENTED_MSG, status_code=501)

    async def get_max_buy_qty(
        self, account_id: str, symbol: str, price: float
    ) -> MaxBuyQuantity:
        raise TradingProviderError(_NOT_IMPLEMENTED_MSG, status_code=501)

    async def get_max_sell_qty(
        self, account_id: str, symbol: str
    ) -> MaxSellQuantity:
        raise TradingProviderError(_NOT_IMPLEMENTED_MSG, status_code=501)

    async def get_order_book(self, account_id: str) -> list[OrderBookEntry]:
        raise TradingProviderError(_NOT_IMPLEMENTED_MSG, status_code=501)

    async def get_order_history(
        self,
        account_id: str,
        start_date: date,
        end_date: date,
    ) -> list[OrderHistoryEntry]:
        raise TradingProviderError(_NOT_IMPLEMENTED_MSG, status_code=501)

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
        """Phase 2.8 stub. Phase 3 wires the real SSI NewOrder HTTP call.

        Even when the orchestrator's 5-flag gate is fully open, this
        method raises NOT_IMPLEMENTED today — by design. The Phase 2.8
        scope is the safety scaffolding (state machine, gating,
        re-validation, audit). Actual SSI POST /Trading/NewOrder lives
        behind a separate Phase 3 review.
        """
        raise TradingProviderError(
            "SSI submit_order not implemented in Phase 2.8 (scaffolding only).",
            status_code=501,
        )

    async def status(self) -> TradingProviderStatus:
        return TradingProviderStatus(
            name="ssi-trading",
            mock=False,
            read_only=True,
            order_placement_enabled=False,
            status_code="NOT_IMPLEMENTED",
            last_call_ts=None,
            last_error_sanitized=None,
            note=(
                "SSI Trading read-only sync is gated to Phase 3. Switch to "
                "SSI_TRADING_USE_MOCK=true for local development."
            ),
        )
