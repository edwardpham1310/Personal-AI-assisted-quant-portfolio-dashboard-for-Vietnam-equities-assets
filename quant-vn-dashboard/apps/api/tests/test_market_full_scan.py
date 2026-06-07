"""Full-market scan service (Phase 2.4).

Computes whole-market breadth + top movers over the securities universe with
cost/rate-limit safeguards: a symbol cap and chunked, error-tolerant fetches.
Exercised with the deterministic mock provider — no real SSI.
"""

from __future__ import annotations

import asyncio

from providers.market_data import MockMarketDataProvider
from schemas.market import Security
from services import market_full_scan


def test_full_scan_computes_breadth_and_top_movers() -> None:
    result = asyncio.run(
        market_full_scan.run_full_market_scan(
            MockMarketDataProvider(), max_symbols=100, chunk_size=2
        )
    )
    assert result["universe_size"] > 0
    assert set(result["breadth"]) == {"advancers", "decliners", "unchanged", "ceiling", "floor"}
    assert set(result["top_movers"]) == {"gainers", "losers", "by_value", "by_volume"}
    assert result["quotes_priced"] >= 0


def test_full_scan_caps_symbol_count() -> None:
    # max_symbols is a hard safeguard against scanning the whole ~1,600 universe.
    result = asyncio.run(
        market_full_scan.run_full_market_scan(
            MockMarketDataProvider(), max_symbols=2, chunk_size=1
        )
    )
    assert result["universe_size"] == 2


def test_full_scan_tolerates_chunk_failures_without_fabricating() -> None:
    class _FlakyProvider:
        async def get_securities(self, exchange=None):
            return [Security(symbol="FPT"), Security(symbol="MWG")]

        async def get_latest_quotes(self, symbols):
            raise RuntimeError("simulated SSI outage")

    result = asyncio.run(
        market_full_scan.run_full_market_scan(_FlakyProvider(), max_symbols=10, chunk_size=1)
    )
    # Universe still known, but no quotes priced → all-zero breadth, empty movers.
    assert result["universe_size"] == 2
    assert result["quotes_priced"] == 0
    assert result["breadth"]["advancers"] == 0
    assert result["top_movers"]["gainers"] == []
