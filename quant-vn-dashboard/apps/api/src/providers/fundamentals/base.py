"""FundamentalDataProvider — abstract interface for company fundamentals.

SSI FastConnect Data does not expose ROE, net profit, or audit opinion;
these come from a separate source (operator-uploaded CSV → DB master
row today, paid vendor tomorrow). Recommendation engine and guardrails
read this interface, not SSI directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from schemas.fundamentals import Fundamentals


ProviderStatusCode = Literal[
    "CONNECTED",
    "CONFIG_MISSING",
    "ERROR",
    "NOT_IMPLEMENTED",
]


class FundamentalsProviderError(Exception):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class FundamentalsProviderStatus:
    def __init__(
        self,
        status_code: ProviderStatusCode,
        *,
        source_label: str,
        last_loaded_at: str | None = None,
        symbols_covered: int = 0,
        last_error: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.source_label = source_label
        self.last_loaded_at = last_loaded_at
        self.symbols_covered = symbols_covered
        self.last_error = last_error

    def to_dict(self) -> dict[str, object]:
        return {
            "status_code": self.status_code,
            "source_label": self.source_label,
            "last_loaded_at": self.last_loaded_at,
            "symbols_covered": self.symbols_covered,
            "last_error": self.last_error,
        }


class FundamentalDataProvider(ABC):
    """Read-only fundamentals provider.

    Implementations:
      * ``NullFundamentalProvider`` — returns ``None`` for every symbol;
        the safe default in dev/test.
      * ``DBFundamentalProvider`` — reads the ``securities`` master row.
      * ``CSVFundamentalProvider`` — reads a CSV the operator uploaded.
      * ``ExternalFundamentalProvider`` — placeholder for a paid vendor.
    """

    @abstractmethod
    async def get_fundamentals(self, symbol: str) -> Fundamentals | None: ...

    @abstractmethod
    async def get_many(self, symbols: list[str]) -> dict[str, Fundamentals | None]:
        """Batched version — same semantics as calling ``get_fundamentals``
        once per symbol but the implementation can issue one query."""

    @abstractmethod
    async def list_known_symbols(self) -> list[str]: ...

    @abstractmethod
    async def status(self) -> FundamentalsProviderStatus: ...
