"""Deterministic mock market data — for local dev without SSI credentials.

Symbols supported: FPT, MWG, HPG, VNM, VNINDEX, VN30.
Bars and quotes are generated from a SHA-256 of ``symbol + timestamp`` so the
same query always returns the same values; this keeps Storybook screenshots,
e2e snapshots, and UI development reproducible.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta, timezone

from providers.market_data.base import Interval, MarketDataProvider, ProviderError
from schemas.market import IndexInfo, OHLCVBar, ProviderStatus, Quote, Security


_REFERENCE_PRICES: dict[str, float] = {
    "FPT": 86000.0,
    "MWG": 42000.0,
    "HPG": 25000.0,
    "VNM": 70000.0,
    "VNINDEX": 1280.0,
    "VN30": 1320.0,
}

_SECURITIES: dict[str, Security] = {
    "FPT": Security(
        symbol="FPT", name="FPT Corporation", exchange="HOSE",
        type="STOCK", status="ACTIVE", board="MAIN",
        lot_size=100, reference_price=86000.0,
    ),
    "MWG": Security(
        symbol="MWG", name="Mobile World Investment Corp", exchange="HOSE",
        type="STOCK", status="ACTIVE", board="MAIN",
        lot_size=100, reference_price=42000.0,
    ),
    "HPG": Security(
        symbol="HPG", name="Hoa Phat Group JSC", exchange="HOSE",
        type="STOCK", status="ACTIVE", board="MAIN",
        lot_size=100, reference_price=25000.0,
    ),
    "VNM": Security(
        symbol="VNM", name="Vietnam Dairy Products JSC", exchange="HOSE",
        type="STOCK", status="ACTIVE", board="MAIN",
        lot_size=100, reference_price=70000.0,
    ),
}

_INDICES: dict[str, IndexInfo] = {
    "VNINDEX": IndexInfo(code="VNINDEX", name="VN Index", exchange="HOSE"),
    "VN30": IndexInfo(code="VN30", name="VN30 Index", exchange="HOSE"),
}

_INDEX_COMPONENTS: dict[str, list[str]] = {
    "VNINDEX": ["FPT", "MWG", "HPG", "VNM"],
    "VN30": ["FPT", "MWG", "HPG", "VNM"],
}


def _det01(seed: str) -> tuple[float, float, float]:
    """Return three deterministic floats in [0,1) from ``seed``."""
    digest = hashlib.sha256(seed.encode()).digest()
    return (
        int.from_bytes(digest[0:4], "big") / 2**32,
        int.from_bytes(digest[4:8], "big") / 2**32,
        int.from_bytes(digest[8:12], "big") / 2**32,
    )


def _bar(symbol: str, ts: datetime, ref: float, *, volume_floor: int = 100_000) -> OHLCVBar:
    drift, spread, vol = _det01(f"{symbol}-{ts.isoformat()}")
    close = ref * (1 + (drift - 0.5) * 0.04)             # ±2%
    spread_pct = 0.001 + spread * 0.004                   # 10–50 bps
    high = close * (1 + spread_pct)
    low = close * (1 - spread_pct)
    open_price = close * (1 + (drift - 0.5) * 0.02)
    volume = float(volume_floor + int(vol * 500_000))
    return OHLCVBar(
        symbol=symbol,
        ts=ts,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        value=close * volume,
    )


class MockMarketDataProvider(MarketDataProvider):
    name = "mock"

    async def get_access_token(self) -> str:
        return "mock-token"

    async def get_securities(self, exchange: str | None = None) -> list[Security]:
        if exchange:
            return [s for s in _SECURITIES.values() if s.exchange == exchange.upper()]
        return list(_SECURITIES.values())

    async def get_security_details(self, symbol: str) -> Security:
        sec = _SECURITIES.get(symbol.upper())
        if not sec:
            raise ProviderError(f"Unknown symbol: {symbol}", status_code=404)
        return sec

    async def get_index_list(self) -> list[IndexInfo]:
        return list(_INDICES.values())

    async def get_index_components(self, index_code: str) -> list[str]:
        comps = _INDEX_COMPONENTS.get(index_code.upper())
        if comps is None:
            raise ProviderError(f"Unknown index: {index_code}", status_code=404)
        return list(comps)

    async def get_daily_ohlcv(
        self, symbol: str, start_date: date, end_date: date
    ) -> list[OHLCVBar]:
        sym = symbol.upper()
        ref = _REFERENCE_PRICES.get(sym)
        if ref is None:
            raise ProviderError(f"Unknown symbol: {symbol}", status_code=404)
        bars: list[OHLCVBar] = []
        cur = start_date
        while cur <= end_date:
            if cur.weekday() < 5:  # skip Sat/Sun
                ts = datetime.combine(cur, time.min, tzinfo=timezone.utc)
                bars.append(_bar(sym, ts, ref))
            cur += timedelta(days=1)
        return bars

    async def get_intraday_ohlcv(
        self, symbol: str, start_date: date, end_date: date, interval: Interval
    ) -> list[OHLCVBar]:
        sym = symbol.upper()
        ref = _REFERENCE_PRICES.get(sym)
        if ref is None:
            raise ProviderError(f"Unknown symbol: {symbol}", status_code=404)
        step_min = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}.get(interval)
        if step_min is None:
            raise ProviderError(f"Unsupported interval: {interval}", status_code=400)
        step = timedelta(minutes=step_min)

        bars: list[OHLCVBar] = []
        cur = start_date
        while cur <= end_date:
            if cur.weekday() < 5:
                # Mock VN session: 02:00 → 08:00 UTC (≈ 09:00–15:00 ICT).
                start_ts = datetime.combine(cur, time(2, 0), tzinfo=timezone.utc)
                end_ts = datetime.combine(cur, time(8, 0), tzinfo=timezone.utc)
                ts = start_ts
                while ts <= end_ts:
                    bars.append(_bar(sym, ts, ref, volume_floor=2_000))
                    ts += step
            cur += timedelta(days=1)
        return bars

    async def get_daily_stock_price(self, symbols: list[str]) -> list[Quote]:
        out: list[Quote] = []
        ts = datetime.now(timezone.utc).replace(microsecond=0)
        for raw in symbols:
            sym = raw.upper()
            ref = _REFERENCE_PRICES.get(sym)
            if ref is None:
                continue
            drift, _, vol = _det01(f"{sym}-{ts.isoformat()}")
            price = ref * (1 + (drift - 0.5) * 0.04)
            change = price - ref
            out.append(
                Quote(
                    symbol=sym,
                    exchange=_SECURITIES.get(sym, Security(symbol=sym)).exchange,
                    price=price,
                    reference_price=ref,
                    change=change,
                    change_pct=change / ref,
                    volume=float(int(vol * 1_000_000)),
                    ts=ts,
                    stale=False,
                    source="mock",
                )
            )
        return out

    async def get_daily_index(self, index_code: str) -> list[OHLCVBar]:
        today = date.today()
        return await self.get_daily_ohlcv(index_code, today - timedelta(days=30), today)

    async def get_latest_quotes(self, symbols: list[str]) -> list[Quote]:
        return await self.get_daily_stock_price(symbols)

    async def status(self) -> ProviderStatus:
        return ProviderStatus(
            name="mock",
            ready=True,
            mock=True,
            token_cached=True,
            last_call_ts=datetime.now(timezone.utc),
            note="Deterministic mock provider — set SSI_USE_MOCK=false for real SSI.",
            status_code="READY",
        )
