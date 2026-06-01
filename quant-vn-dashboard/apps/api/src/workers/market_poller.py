"""Background market poller.

Owns a single asyncio task that:
    1. Polls ``provider.get_latest_quotes(active_symbols)`` every
       ``poll_interval`` seconds.
    2. Writes the result to the hot cache with a short TTL.
    3. Backs off exponentially on provider failure (max 60s) so SSI
       does not get hammered when it is degraded.
    4. Occasionally (``full_market_interval``) refreshes index data.

``active_symbols`` is the union of:
    * A configurable ``core_symbols`` set (always polled).
    * Per-SSE subscriptions registered by stream handlers — when a client
      opens ``/stream/quotes?symbols=…`` we add those symbols so the next
      poll cycle picks them up.

Error messages never include credentials. Only the exception type name and
endpoint path are logged or surfaced.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import Any
from uuid import uuid4

from providers.market_data.base import MarketDataProvider
from services import market_cache
from services.cache import Cache

logger = logging.getLogger(__name__)

_BACKOFF_CAP_SECONDS = 60.0


class MarketPoller:
    """Owns one polling loop. Constructed in the FastAPI lifespan."""

    def __init__(
        self,
        *,
        provider: MarketDataProvider,
        cache: Cache,
        poll_interval: float,
        full_market_interval: float,
        quote_ttl: int,
        index_ttl: int,
        core_symbols: list[str],
        core_indices: list[str],
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._poll_interval = max(1.0, poll_interval)
        self._full_market_interval = max(30.0, full_market_interval)
        self._quote_ttl = quote_ttl
        self._index_ttl = index_ttl
        self._core_symbols = {s.upper() for s in core_symbols}
        self._core_indices = [c.upper() for c in core_indices]

        self._subscriptions: Counter[str] = Counter()
        self._subscription_tokens: dict[str, list[str]] = {}
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._backoff_step = 0
        self._last_full_market_at: float = 0.0

    # ── Subscriptions ──────────────────────────────────────────────────────
    async def subscribe(self, symbols: list[str]) -> str:
        token = uuid4().hex
        cleaned = [s.upper() for s in symbols if s]
        async with self._lock:
            for sym in cleaned:
                self._subscriptions[sym] += 1
            self._subscription_tokens[token] = cleaned
        return token

    async def unsubscribe(self, token: str) -> None:
        async with self._lock:
            symbols = self._subscription_tokens.pop(token, [])
            for sym in symbols:
                self._subscriptions[sym] -= 1
                if self._subscriptions[sym] <= 0:
                    del self._subscriptions[sym]

    async def active_symbols(self) -> list[str]:
        async with self._lock:
            return sorted(self._core_symbols | set(self._subscriptions.keys()))

    # ── Lifecycle ──────────────────────────────────────────────────────────
    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="market-poller")
        logger.info(
            "market_poller.started poll_interval=%.1fs core_symbols=%d",
            self._poll_interval, len(self._core_symbols),
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None
        logger.info("market_poller.stopped")

    # ── Single cycle (exposed for tests + admin) ───────────────────────────
    async def poll_once(self) -> dict[str, Any]:
        symbols = await self.active_symbols()
        if not symbols:
            await market_cache.set_last_poll(self._cache, ok=True, symbol_count=0)
            return {"ok": True, "symbol_count": 0, "quotes_written": 0}
        try:
            quotes = await self._provider.get_latest_quotes(symbols)
            for q in quotes:
                await market_cache.set_quote(self._cache, q, ttl_seconds=self._quote_ttl)
            await market_cache.set_last_poll(
                self._cache, ok=True, symbol_count=len(symbols)
            )
            self._backoff_step = 0
            return {
                "ok": True,
                "symbol_count": len(symbols),
                "quotes_written": len(quotes),
            }
        except Exception as exc:
            # Only the exception type leaves this process — never the body.
            err = type(exc).__name__
            await market_cache.set_last_poll(
                self._cache,
                ok=False,
                symbol_count=len(symbols),
                error=err,
            )
            logger.warning("market_poller.poll_failed err=%s symbols=%d", err, len(symbols))
            return {"ok": False, "error": err, "symbol_count": len(symbols)}

    async def refresh_indices_once(self) -> dict[str, Any]:
        wrote = 0
        for code in self._core_indices:
            try:
                bars = await self._provider.get_daily_index(code)
            except Exception as exc:
                logger.warning(
                    "market_poller.index_failed code=%s err=%s",
                    code, type(exc).__name__,
                )
                continue
            if not bars:
                continue
            last = bars[-1]
            await market_cache.set_index(
                self._cache,
                code,
                {
                    "code": code,
                    "open": last.open,
                    "high": last.high,
                    "low": last.low,
                    "close": last.close,
                    "volume": last.volume,
                    "ts": last.ts.isoformat(),
                },
                ttl_seconds=self._index_ttl,
            )
            wrote += 1
        return {"indices_written": wrote}

    # ── Loop ───────────────────────────────────────────────────────────────
    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            result = await self.poll_once()
            if not result.get("ok"):
                self._backoff_step = min(self._backoff_step + 1, 6)
                wait = min(2**self._backoff_step, _BACKOFF_CAP_SECONDS)
            else:
                wait = self._poll_interval

            now = loop.time()
            if now - self._last_full_market_at >= self._full_market_interval:
                await self.refresh_indices_once()
                self._last_full_market_at = loop.time()

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait)
            except TimeoutError:
                pass
