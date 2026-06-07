"""Full-market breadth + top-movers scan.

Unlike the poller's tracked-universe breadth (core symbols only), this fetches
quotes for the whole listed-securities universe and computes WHOLE-MARKET
breadth + top movers using the same pure helpers in ``market_breadth``.

It is OFF by default and runs on the slow ``full_market_poll_interval`` cadence.
Cost/rate-limit safeguards:
  * ``max_symbols`` caps how many securities are scanned.
  * Fetches are CHUNKED and SEQUENTIAL (never one giant fan-out).
  * A failed chunk is skipped (partial coverage is honest, not fatal).

TODO(ssi-sandbox): the real SSI ``get_latest_quotes`` batch size / rate limits
for many-symbol fetches are unvalidated. Keep ``max_symbols`` conservative and
verify against the SSI sandbox before scanning the full ~1,600-symbol universe.
"""

from __future__ import annotations

import logging
from typing import Any

from providers.market_data.base import MarketDataProvider
from services import market_breadth

logger = logging.getLogger(__name__)


async def run_full_market_scan(
    provider: MarketDataProvider,
    *,
    max_symbols: int = 500,
    chunk_size: int = 50,
) -> dict[str, Any]:
    """Scan the securities universe and compute whole-market breadth + movers.

    Returns ``{breadth, top_movers, universe_size, quotes_priced}``. Reuses the
    pure ``market_breadth`` helpers, so the output shape matches the
    tracked-universe payloads exactly.
    """
    securities = await provider.get_securities()
    symbols = [str(s.symbol).upper() for s in securities if getattr(s, "symbol", None)]
    symbols = symbols[: max(0, max_symbols)]

    quotes: list[Any] = []
    chunk = max(1, chunk_size)
    for i in range(0, len(symbols), chunk):
        batch = symbols[i : i + chunk]
        try:
            qs = await provider.get_latest_quotes(batch)
        except Exception as exc:  # noqa: BLE001 — skip the chunk, keep partial coverage
            logger.warning(
                "full_market_scan.chunk_failed offset=%d size=%d err=%s",
                i, len(batch), type(exc).__name__,
            )
            continue
        quotes.extend(q for q in qs if q is not None)

    return {
        "breadth": market_breadth.compute_breadth(quotes),
        "top_movers": market_breadth.compute_top_movers(quotes),
        "universe_size": len(symbols),
        "quotes_priced": len(quotes),
    }
