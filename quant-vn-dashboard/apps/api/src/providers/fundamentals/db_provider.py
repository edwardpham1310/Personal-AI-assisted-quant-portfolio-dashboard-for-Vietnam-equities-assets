"""DBFundamentalProvider — reads fundamentals from the ``securities``
master table via SupabaseDB. The CSV provider writes to this table; a
future vendor integration can do the same."""

from __future__ import annotations

from datetime import date
from typing import Any

from schemas.fundamentals import Fundamentals
from services.supabase_db import SupabaseDB

from .base import FundamentalDataProvider, FundamentalsProviderStatus


def _row_to_fundamentals(row: dict[str, Any]) -> Fundamentals:
    """Map a ``securities`` row to the DTO. None-safe."""
    npq = row.get("net_profit_last_4_quarters")
    if isinstance(npq, list):
        net_profit: list[float] | None = [float(x) for x in npq]
    else:
        net_profit = None

    fas_of = row.get("fundamentals_as_of")
    if isinstance(fas_of, str):
        try:
            fas_of_parsed: date | None = date.fromisoformat(fas_of[:10])
        except ValueError:
            fas_of_parsed = None
    elif isinstance(fas_of, date):
        fas_of_parsed = fas_of
    else:
        fas_of_parsed = None

    return Fundamentals(
        symbol=str(row["symbol"]).upper(),
        market_cap=row.get("market_cap"),
        market_cap_source=row.get("market_cap_source"),
        listed_share=row.get("listed_share"),
        roe=row.get("roe"),
        net_profit_last_4_quarters=net_profit,
        audit_opinion=row.get("audit_opinion"),
        fiscal_period=row.get("fiscal_period"),
        fundamentals_source=row.get("fundamentals_source"),
        fundamentals_as_of=fas_of_parsed,
        is_vn30=row.get("is_vn30"),
        is_vn100=row.get("is_vn100"),
    )


class DBFundamentalProvider(FundamentalDataProvider):
    def __init__(self, db: SupabaseDB) -> None:
        self._db = db

    async def get_fundamentals(self, symbol: str) -> Fundamentals | None:
        rows = await self._db.select(
            "securities",
            where={"symbol": symbol.upper()},
            limit=1,
        )
        if not rows:
            return None
        return _row_to_fundamentals(rows[0])

    async def get_many(
        self, symbols: list[str]
    ) -> dict[str, Fundamentals | None]:
        targets = [s.upper() for s in symbols]
        rows = await self._db.select(
            "securities",
            where={"symbol__in": targets},
        )
        by_symbol = {str(r["symbol"]).upper(): r for r in rows}
        return {
            s: (_row_to_fundamentals(by_symbol[s]) if s in by_symbol else None)
            for s in targets
        }

    async def list_known_symbols(self) -> list[str]:
        rows = await self._db.select(
            "securities",
            select=["symbol"],
            limit=10_000,
        )
        return sorted(str(r["symbol"]).upper() for r in rows)

    async def status(self) -> FundamentalsProviderStatus:
        rows = await self._db.select(
            "securities",
            select=["symbol", "fundamentals_as_of"],
            limit=10_000,
        )
        last_loaded = None
        for r in rows:
            v = r.get("fundamentals_as_of")
            if isinstance(v, str) and (last_loaded is None or v > last_loaded):
                last_loaded = v
        return FundamentalsProviderStatus(
            "CONNECTED" if rows else "CONFIG_MISSING",
            source_label="db.securities",
            last_loaded_at=last_loaded,
            symbols_covered=len(rows),
        )
