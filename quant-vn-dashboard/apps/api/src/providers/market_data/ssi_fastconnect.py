"""SSI FastConnect Data — async implementation.

Design rules:
    * Tokens are cached in memory with a 60-second leeway.
    * An ``asyncio.Lock`` prevents stampedes during concurrent refresh.
    * 429 and 5xx responses are retried with exponential backoff; 4xx is not.
    * Error messages NEVER include the credential payload or request body.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timezone
from typing import Any

import httpx

from providers.market_data.base import Interval, MarketDataProvider, ProviderError
from schemas.market import IndexInfo, OHLCVBar, ProviderStatus, Quote, Security


logger = logging.getLogger(__name__)


_TOKEN_LEEWAY_SECONDS = 60.0
_BACKOFF_BASE = 0.5
_BACKOFF_CAP = 4.0
_SAFE_BODY_KEYS = {"status", "message", "code", "errorCode"}


def _fmt_date(d: date) -> str:
    """SSI expects dd/MM/yyyy."""
    return d.strftime("%d/%m/%Y")


def _parse_ssi_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        s = value.strip().replace("Z", "+00:00")
        # Try ISO first.
        try:
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        # SSI sometimes uses dd/MM/yyyy.
        try:
            return datetime.strptime(s, "%d/%m/%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _safe(obj: Any) -> dict[str, Any]:
    """Return only keys safe to log/echo from a response body."""
    if not isinstance(obj, dict):
        return {}
    return {k: v for k, v in obj.items() if k in _SAFE_BODY_KEYS}


class SSIFastConnectProvider(MarketDataProvider):
    """Talks to ``https://fc-data.ssi.com.vn`` for market data."""

    name = "ssi"

    def __init__(
        self,
        *,
        consumer_id: str,
        consumer_secret: str,
        base_url: str,
        timeout: float,
        max_retries: int,
    ) -> None:
        if not consumer_id or not consumer_secret:
            # 503 — caller cannot recover by retrying; only by configuring.
            raise ProviderError(
                "SSI credentials are missing — set SSI_CONSUMER_ID and SSI_CONSUMER_SECRET.",
                status_code=503,
            )
        if not base_url.startswith("https://"):
            raise ProviderError("SSI base_url must use HTTPS.", status_code=500)

        self._consumer_id = consumer_id
        self._consumer_secret = consumer_secret
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max(0, max_retries)
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._token_lock = asyncio.Lock()
        self._last_call_ts: datetime | None = None
        # Phase 2 data-policy state: tracks the *cause* of the last error so
        # the system status surface can distinguish AUTH_FAILED from generic
        # PROVIDER_ERROR. Cleared on success.
        self._last_error_code: str | None = None

    # ── Token management ───────────────────────────────────────────────────
    async def get_access_token(self) -> str:
        async with self._token_lock:
            if self._token and time.time() < self._token_expiry - _TOKEN_LEEWAY_SECONDS:
                return self._token
            return await self._refresh_token_locked()

    async def _refresh_token_locked(self) -> str:
        url = f"{self._base}/api/v2/Market/AccessToken"
        payload = {
            "consumerID": self._consumer_id,
            "consumerSecret": self._consumer_secret,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload)
            # Distinguish auth failures from network / 5xx so the UI can
            # surface AUTH_FAILED separately from PROVIDER_ERROR.
            if resp.status_code in (401, 403):
                self._last_error_code = "AUTH_FAILED"
                logger.warning("ssi.token_refresh_auth_failed status=%d", resp.status_code)
                raise ProviderError(
                    f"SSI token refresh rejected: HTTP {resp.status_code}",
                    status_code=502,
                )
            resp.raise_for_status()
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            # ``from None`` scrubs the chained exception so its traceback does
            # not leak the consumer_secret payload.
            self._last_error_code = "PROVIDER_ERROR"
            logger.warning("ssi.token_refresh_failed err=%s", type(exc).__name__)
            raise ProviderError(
                f"SSI token refresh failed: {type(exc).__name__}",
                status_code=502,
            ) from None

        body = resp.json()
        token = (body.get("data") or {}).get("accessToken") or body.get("accessToken")
        if not token:
            self._last_error_code = "PROVIDER_ERROR"
            raise ProviderError(
                f"SSI token response missing accessToken: {_safe(body)}",
                status_code=502,
            )
        expires_in = int((body.get("data") or {}).get("expiresIn", 3600))
        self._token = token
        self._token_expiry = time.time() + expires_in
        self._last_error_code = None  # success clears the error code
        logger.info("ssi.token_refreshed expires_in=%ds", expires_in)
        return token

    # ── HTTP helper with retry ─────────────────────────────────────────────
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._base}{path}"
        last_kind = "unknown"
        for attempt in range(self._max_retries + 1):
            try:
                token = await self.get_access_token()
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(
                        url,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                        },
                        params=params or {},
                    )
                self._last_call_ts = datetime.now(timezone.utc)
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    # Trigger a retry without leaking the body.
                    last_kind = f"HTTP{resp.status_code}"
                    raise httpx.HTTPStatusError(
                        f"upstream {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as exc:
                last_kind = type(exc).__name__
                if attempt >= self._max_retries:
                    break
                delay = min(_BACKOFF_BASE * (2**attempt), _BACKOFF_CAP)
                logger.warning(
                    "ssi.retry attempt=%d path=%s err=%s wait=%.2fs",
                    attempt, path, last_kind, delay,
                )
                await asyncio.sleep(delay)
        raise ProviderError(f"SSI GET {path} failed: {last_kind}", status_code=502) from None

    # ── MarketDataProvider methods ─────────────────────────────────────────
    async def get_securities(self, exchange: str | None = None) -> list[Security]:
        all_rows: list[dict[str, Any]] = []
        page = 1
        page_size = 100
        while True:
            params: dict[str, Any] = {"pageIndex": page, "pageSize": page_size}
            if exchange:
                params["market"] = exchange
            body = await self._get("/api/v2/Market/Securities", params)
            items = body.get("data") or []
            if not items:
                break
            all_rows.extend(items)
            if len(items) < page_size:
                break
            page += 1
        return [self._security_from(row, exchange) for row in all_rows]

    @staticmethod
    def _security_from(row: dict[str, Any], fallback_exchange: str | None) -> Security:
        symbol = row.get("Symbol") or row.get("symbol") or ""
        exch = (
            row.get("Exchange")
            or row.get("comGroupCode")
            or fallback_exchange
            or ""
        )
        return Security(
            symbol=str(symbol).upper(),
            name=row.get("StockName") or row.get("name") or row.get("companyName"),
            exchange=(exch.upper() if isinstance(exch, str) and exch else None),
            type=row.get("StockType") or row.get("type"),
            status=row.get("Status") or row.get("status"),
            board=row.get("Board") or row.get("board"),
            lot_size=row.get("BoardLotSize") or row.get("lotSize"),
            reference_price=row.get("RefPrice") or row.get("refPrice"),
        )

    async def get_security_details(self, symbol: str) -> Security:
        # SSI rejects pageSize values outside {10, 20, 50, 100, 1000} —
        # request 10 and pick the matching symbol locally.
        body = await self._get(
            "/api/v2/Market/Securities",
            {"symbol": symbol, "pageIndex": 1, "pageSize": 10},
        )
        items = body.get("data") or []
        target = symbol.upper()
        match = next(
            (
                r for r in items
                if str(r.get("Symbol") or r.get("symbol") or "").upper() == target
            ),
            items[0] if items else None,
        )
        if not match:
            raise ProviderError(f"SSI: no security details for {symbol}", status_code=404)
        return self._security_from(match, None)

    async def get_index_list(self) -> list[IndexInfo]:
        # SSI rejects pageSize values outside {10, 20, 50, 100, 1000} and the
        # correct path is /IndexList (not /Indices, which 404s).
        all_rows: list[dict[str, Any]] = []
        page = 1
        page_size = 100
        while True:
            body = await self._get(
                "/api/v2/Market/IndexList",
                {"pageIndex": page, "pageSize": page_size},
            )
            items = body.get("data") or []
            if not items:
                break
            all_rows.extend(items)
            if len(items) < page_size:
                break
            page += 1
        out: list[IndexInfo] = []
        for row in all_rows:
            code = row.get("IndexCode") or row.get("indexCode")
            if not code:
                continue
            out.append(
                IndexInfo(
                    code=str(code).upper(),
                    name=row.get("IndexName") or row.get("indexName"),
                    exchange=row.get("Exchange") or row.get("exchange"),
                )
            )
        return out

    async def get_index_components(self, index_code: str) -> list[str]:
        body = await self._get(
            "/api/v2/Market/IndexComponents",
            {"indexCode": index_code, "pageIndex": 1, "pageSize": 100},
        )
        items = body.get("data") or []
        # SSI returns one wrapper row per index with the members nested under
        # ``IndexComponent``; older parsers iterated the top level which gave
        # an empty list.
        symbols: list[str] = []
        for wrapper in items:
            components = (
                wrapper.get("IndexComponent")
                or wrapper.get("indexComponent")
                or []
            )
            for c in components:
                sym = (
                    c.get("StockSymbol")
                    or c.get("stockSymbol")
                    or c.get("Symbol")
                    or c.get("symbol")
                )
                if sym:
                    symbols.append(str(sym).upper())
        return symbols

    async def get_daily_ohlcv(
        self, symbol: str, start_date: date, end_date: date
    ) -> list[OHLCVBar]:
        bars: list[OHLCVBar] = []
        page = 1
        page_size = 100
        while True:
            body = await self._get(
                "/api/v2/Market/DailyOhlc",
                {
                    "symbol": symbol,
                    "fromDate": _fmt_date(start_date),
                    "toDate": _fmt_date(end_date),
                    "pageIndex": page,
                    "pageSize": page_size,
                },
            )
            items = body.get("data") or []
            if not items:
                break
            bars.extend(self._bar_from(row, symbol) for row in items)
            if len(items) < page_size:
                break
            page += 1
        return bars

    @staticmethod
    def _bar_from(row: dict[str, Any], symbol: str) -> OHLCVBar:
        ts = (
            _parse_ssi_ts(row.get("TradingDate"))
            or _parse_ssi_ts(row.get("tradingDate"))
            or _parse_ssi_ts(row.get("Date"))
            or datetime.now(timezone.utc)
        )
        def f(*keys: str) -> float:
            for k in keys:
                if row.get(k) is not None:
                    return float(row[k])
            return 0.0

        return OHLCVBar(
            symbol=symbol.upper(),
            ts=ts,
            open=f("Open", "open"),
            high=f("High", "high"),
            low=f("Low", "low"),
            close=f("Close", "close"),
            volume=f("Volume", "volume"),
            value=float(row["Value"]) if row.get("Value") is not None else None,
        )

    async def get_intraday_ohlcv(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        interval: Interval,
    ) -> list[OHLCVBar]:
        body = await self._get(
            "/api/v2/Market/IntradayOhlc",
            {
                "symbol": symbol,
                "fromDate": _fmt_date(start_date),
                "toDate": _fmt_date(end_date),
                "interval": interval,
                "pageIndex": 1,
                "pageSize": 1000,
            },
        )
        items = body.get("data") or []
        return [self._bar_from(row, symbol) for row in items]

    async def get_daily_stock_price(self, symbols: list[str]) -> list[Quote]:
        # SSI DailyStockPrice returns capitalized fields with names like
        # ``ClosePrice``/``PriceChange``/``PerPriceChange``/``TotalMatchVol``
        # (the prior parser used ``Close``/``Change``/``Ratio``/``Volume``
        # which silently fell back to RefPrice with null change). SSI also
        # rejects pageSize=1 — minimum is 10 — and REQUIRES fromDate/toDate in
        # dd/MM/yyyy, max 30 days, with ``toDate`` not in the future. We ask
        # for the last 10 calendar days and pick the most recent row.
        today = date.today()
        from_d = today - __import__("datetime").timedelta(days=10)
        out: list[Quote] = []
        for raw in symbols:
            sym = raw.upper()
            body = await self._get(
                "/api/v2/Market/DailyStockPrice",
                {
                    "symbol": sym,
                    "fromDate": _fmt_date(from_d),
                    "toDate": _fmt_date(today),
                    "pageIndex": 1,
                    "pageSize": 10,
                },
            )
            items = body.get("data") or []
            if not items:
                continue
            row = items[0]
            ts = _parse_ssi_ts(row.get("TradingDate")) or datetime.now(timezone.utc)
            ref = row.get("RefPrice") or row.get("refPrice")
            close = (
                row.get("ClosePrice")
                or row.get("closePrice")
                or row.get("Close")
                or row.get("close")
                or ref
                or 0
            )
            change = (
                row.get("PriceChange")
                or row.get("priceChange")
                or row.get("Change")
                or row.get("change")
            )
            ratio = (
                row.get("PerPriceChange")
                or row.get("perPriceChange")
                or row.get("Ratio")
                or row.get("ratio")
            )
            volume = (
                row.get("TotalMatchVol")
                or row.get("totalMatchVol")
                or row.get("Volume")
                or row.get("volume")
                or 0
            )
            out.append(
                Quote(
                    symbol=sym,
                    exchange=(
                        (
                            row.get("Exchange")
                            or row.get("exchange")
                            or row.get("Market")
                            or ""
                        ).upper()
                        or None
                    ),
                    price=float(close),
                    reference_price=float(ref) if ref is not None else None,
                    change=float(change) if change is not None else None,
                    change_pct=float(ratio) if ratio is not None else None,
                    volume=float(volume),
                    ts=ts,
                    stale=False,
                    source="ssi",
                )
            )
        return out

    async def get_daily_index(self, index_code: str) -> list[OHLCVBar]:
        body = await self._get(
            "/api/v2/Market/DailyIndex",
            {"indexId": index_code, "pageIndex": 1, "pageSize": 500},
        )
        items = body.get("data") or []
        return [self._bar_from(row, index_code) for row in items]

    async def get_latest_quotes(self, symbols: list[str]) -> list[Quote]:
        return await self.get_daily_stock_price(symbols)

    async def status(self) -> ProviderStatus:
        """Compute the Phase 2 ``status_code`` for the dashboard.

        Priority (first match wins):
            * CONFIG_MISSING — consumer ID/secret blank (also makes ``ready=False``)
            * AUTH_FAILED    — last token refresh rejected (401/403)
            * PROVIDER_ERROR — last call failed for a non-auth reason
            * STALE          — last call > 5 minutes ago (freshness threshold)
            * READY          — credentials present, no recent error
        """
        # CONFIG_MISSING short-circuits — `__init__` would have refused to
        # construct the provider, but defence-in-depth never hurts.
        if not self._consumer_id or not self._consumer_secret:
            return ProviderStatus(
                name="ssi", ready=False, mock=False, token_cached=False,
                last_call_ts=None, status_code="CONFIG_MISSING",
                note="SSI_CONSUMER_ID or SSI_CONSUMER_SECRET is not configured",
            )

        code: str = "READY"
        if self._last_error_code in ("AUTH_FAILED", "PROVIDER_ERROR"):
            code = self._last_error_code
        elif self._last_call_ts is not None:
            age = (datetime.now(timezone.utc) - self._last_call_ts).total_seconds()
            if age > 300:  # 5 min stale window
                code = "STALE"

        return ProviderStatus(
            name="ssi",
            ready=(code == "READY"),
            mock=False,
            token_cached=self._token is not None,
            last_call_ts=self._last_call_ts,
            status_code=code,  # type: ignore[arg-type]
        )
