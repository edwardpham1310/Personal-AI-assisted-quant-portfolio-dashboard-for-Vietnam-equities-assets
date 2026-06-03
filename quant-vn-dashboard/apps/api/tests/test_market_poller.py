"""Market poller tests."""

from __future__ import annotations

import pytest

from providers.market_data import MockMarketDataProvider
from services import market_cache
from services.cache import InMemoryCache
from workers.market_poller import MarketPoller


def _poller(provider, cache, core=("FPT", "MWG")) -> MarketPoller:
    return MarketPoller(
        provider=provider,
        cache=cache,
        poll_interval=1.0,
        full_market_interval=60.0,
        quote_ttl=30,
        index_ttl=30,
        core_symbols=list(core),
        core_indices=["VNINDEX"],
    )


@pytest.mark.asyncio
async def test_poll_once_populates_cache() -> None:
    cache = InMemoryCache()
    poller = _poller(MockMarketDataProvider(), cache)

    result = await poller.poll_once()

    assert result["ok"] is True
    assert result["symbol_count"] == 2
    assert result["quotes_written"] == 2

    fpt = await market_cache.get_quote(cache, "FPT")
    assert fpt is not None
    assert fpt.symbol == "FPT"
    assert fpt.source == "mock"

    last = await market_cache.get_last_poll(cache)
    assert last is not None and last["ok"] is True


@pytest.mark.asyncio
async def test_poll_once_writes_breadth_and_top_movers() -> None:
    cache = InMemoryCache()
    poller = _poller(MockMarketDataProvider(), cache, core=("FPT", "MWG", "HPG", "VNM"))

    await poller.poll_once()

    breadth = await market_cache.get_breadth(cache)
    assert breadth is not None
    assert set(breadth) == {"advancers", "decliners", "unchanged", "ceiling", "floor"}
    # Mock quotes carry change_pct, so every polled symbol is classified.
    assert breadth["advancers"] + breadth["decliners"] + breadth["unchanged"] == 4

    movers = await market_cache.get_top_movers(cache)
    assert movers is not None
    assert set(movers) == {"gainers", "losers", "by_value", "by_volume_spike"}
    # Mock provider leaves Quote.value None → by_value empty; no ADV → spike empty.
    assert movers["by_value"] == []
    assert movers["by_volume_spike"] == []


@pytest.mark.asyncio
async def test_poll_once_handles_provider_failure_safely() -> None:
    """Errors must surface as type names — never as request bodies or secrets."""
    cache = InMemoryCache()

    class FailingProvider(MockMarketDataProvider):
        async def get_latest_quotes(self, symbols):  # type: ignore[override]
            raise RuntimeError("SUPER_SECRET_VALUE in upstream payload")

    poller = _poller(FailingProvider(), cache)
    result = await poller.poll_once()

    assert result["ok"] is False
    assert result["error"] == "RuntimeError"

    last = await market_cache.get_last_poll(cache)
    assert last is not None
    assert last["ok"] is False
    assert last["error"] == "RuntimeError"
    # The leak guard: the raw exception message must NEVER end up in the cache.
    import json

    serialized = json.dumps(last)
    assert "SUPER_SECRET_VALUE" not in serialized


@pytest.mark.asyncio
async def test_subscriptions_add_symbols_to_active_set() -> None:
    cache = InMemoryCache()
    poller = _poller(MockMarketDataProvider(), cache, core=("FPT",))

    token = await poller.subscribe(["vcb", "VNM"])
    active = await poller.active_symbols()
    assert set(active) == {"FPT", "VCB", "VNM"}

    await poller.unsubscribe(token)
    assert set(await poller.active_symbols()) == {"FPT"}


@pytest.mark.asyncio
async def test_subscriptions_use_refcount() -> None:
    cache = InMemoryCache()
    poller = _poller(MockMarketDataProvider(), cache, core=("FPT",))

    a = await poller.subscribe(["VCB"])
    b = await poller.subscribe(["VCB", "HPG"])
    assert set(await poller.active_symbols()) == {"FPT", "VCB", "HPG"}

    await poller.unsubscribe(a)
    # Still subscribed via b.
    assert "VCB" in await poller.active_symbols()
    await poller.unsubscribe(b)
    assert set(await poller.active_symbols()) == {"FPT"}


@pytest.mark.asyncio
async def test_index_refresh_writes_cache() -> None:
    cache = InMemoryCache()
    poller = _poller(MockMarketDataProvider(), cache)

    result = await poller.refresh_indices_once()
    assert result["indices_written"] >= 1

    vnindex = await market_cache.get_index(cache, "VNINDEX")
    assert vnindex is not None
    assert vnindex["code"] == "VNINDEX"
    assert "close" in vnindex


@pytest.mark.asyncio
async def test_start_stop_lifecycle() -> None:
    cache = InMemoryCache()
    poller = _poller(MockMarketDataProvider(), cache)
    assert poller.is_running is False
    await poller.start()
    assert poller.is_running is True
    await poller.stop()
    assert poller.is_running is False
