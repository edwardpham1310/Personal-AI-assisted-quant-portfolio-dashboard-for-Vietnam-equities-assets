"""NullFundamentalProvider — returns ``None`` for every symbol.

Default in dev/test. Production startup should refuse to boot with
this provider when ``RECOMMENDATION_STRICT_MODE=true`` — strict mode
needs real fundamentals or every BUY_CANDIDATE downgrades to WATCH.
"""

from __future__ import annotations

from schemas.fundamentals import Fundamentals

from .base import FundamentalDataProvider, FundamentalsProviderStatus


class NullFundamentalProvider(FundamentalDataProvider):
    async def get_fundamentals(self, symbol: str) -> Fundamentals | None:
        return None

    async def get_many(
        self, symbols: list[str]
    ) -> dict[str, Fundamentals | None]:
        return {s.upper(): None for s in symbols}

    async def list_known_symbols(self) -> list[str]:
        return []

    async def status(self) -> FundamentalsProviderStatus:
        return FundamentalsProviderStatus(
            "NOT_IMPLEMENTED",
            source_label="null",
            symbols_covered=0,
            last_error=(
                "FundamentalsProvider is NullProvider — every guardrail "
                "check that requires fundamentals will REJECT in strict "
                "mode and WARN in relaxed mode."
            ),
        )
