"""Abstract TradingProvider — Phase 2.5 read-only contract.

There is no ``place_order`` method. There never will be a method on this
class that submits an order to a broker as long as Phase 2.5 is in force.
Phase 3 will add a separate ``OrderSubmissionProvider`` interface gated
by ``SSI_TRADING_ORDER_PLACEMENT_ENABLED`` and a startup assertion.

If you find yourself adding a live order submission method to this class,
stop and read ``docs/trading-rules.md`` — that is a Phase 3 change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from schemas.trading import (
    CashBalance,
    MaxBuyQuantity,
    MaxSellQuantity,
    OrderBookEntry,
    OrderHistoryEntry,
    StockPosition,
    TradingProviderStatus,
)


class TradingProviderError(Exception):
    """Raised when the trading provider cannot satisfy a read request.

    Carries:
      * ``message`` — operator-facing detail (logged, NEVER returned to clients).
      * ``status_code`` — HTTP status the route layer will surface.
      * ``client_safe_message`` — short, sanitized message safe to put in a
        response body. Defaults to a generic per-status string so a
        future SSI HTTP client can never leak a stack trace, token, or
        upstream payload to the dashboard user.
    """

    _DEFAULT_SAFE_BY_STATUS: dict[int, str] = {
        400: "Invalid request to trading provider.",
        401: "Trading provider authentication failed.",
        403: "Trading provider rejected the request.",
        404: "Resource not found at trading provider.",
        429: "Trading provider rate limit reached. Try again shortly.",
        500: "Trading provider configuration error.",
        501: "Trading provider operation not implemented in this phase.",
        502: "Trading provider unavailable.",
        503: "Trading provider not configured.",
        504: "Trading provider timeout.",
    }

    def __init__(
        self,
        message: str,
        status_code: int = 502,
        *,
        client_safe_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.client_safe_message = (
            client_safe_message
            or self._DEFAULT_SAFE_BY_STATUS.get(
                status_code, "Trading provider error."
            )
        )


class TradingProvider(ABC):
    """Read-only contract for SSI Trading.

    All methods are async because real SSI calls are network I/O. None of
    these methods can place, cancel, or modify orders.
    """

    name: str = "trading"

    @abstractmethod
    async def get_cash_balance(self, account_id: str) -> CashBalance:
        """Return current cash + buying power for the account."""

    @abstractmethod
    async def get_stock_positions(self, account_id: str) -> list[StockPosition]:
        """Return all open stock positions (read-only snapshot)."""

    @abstractmethod
    async def get_max_buy_qty(
        self, account_id: str, symbol: str, price: float
    ) -> MaxBuyQuantity:
        """How many shares can this account buy at ``price``?"""

    @abstractmethod
    async def get_max_sell_qty(
        self, account_id: str, symbol: str
    ) -> MaxSellQuantity:
        """How many shares are sellable right now (settled + unencumbered)?"""

    @abstractmethod
    async def get_order_book(self, account_id: str) -> list[OrderBookEntry]:
        """Open / in-flight orders. Read-only."""

    @abstractmethod
    async def get_order_history(
        self,
        account_id: str,
        start_date: date,
        end_date: date,
    ) -> list[OrderHistoryEntry]:
        """Closed orders in the date range."""

    @abstractmethod
    async def status(self) -> TradingProviderStatus:
        """System-status snapshot for the trading provider."""

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
        """Phase 2.8 placeholder — concrete implementations override.

        Default raises NOT_IMPLEMENTED so any caller that bypasses the
        orchestrator's gate (which is the only legitimate caller) fails
        loudly. The orchestrator at ``services.live_orders`` is the
        SINGLE choke-point that may call this method, and it does so
        only when ALL 5 env flags align AND the user has confirmed.
        """
        raise TradingProviderError(
            "submit_order: orchestrator must be the only caller.",
            status_code=501,
        )
