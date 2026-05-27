"""SSI FastConnect Data API provider.

Authentication: consumerID + consumerSecret → access token (cached, auto-refreshed).

Set SSI_CONSUMER_ID and SSI_CONSUMER_SECRET in .env before use.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import httpx
import pandas as pd

from .base import MarketDataProvider, ProviderError

logger = logging.getLogger(__name__)

_TOKEN_LEEWAY_SECONDS = 60  # refresh token this many seconds before expiry
_SAFE_RESPONSE_KEYS = {"status", "message", "code", "errorCode"}


class SSIFastConnectProvider(MarketDataProvider):
    name = "ssi"

    def __init__(
        self,
        consumer_id: str,
        consumer_secret: str,
        base_url: str = "https://fc-data.ssi.com.vn",
        timeout: float = 30.0,
    ) -> None:
        if not consumer_id or not consumer_secret:
            raise ProviderError(
                "SSI credentials are missing. "
                "Set SSI_CONSUMER_ID and SSI_CONSUMER_SECRET in your .env file."
            )
        if not base_url.startswith("https://"):
            raise ProviderError(
                f"SSI base_url must use HTTPS. Got: {base_url[:8]}..."
            )
        self._consumer_id = consumer_id
        self._consumer_secret = consumer_secret
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # ── Authentication ──────────────────────────────────────────────────────

    def _get_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - _TOKEN_LEEWAY_SECONDS:
            return self._access_token
        return self._refresh_token()

    def _refresh_token(self) -> str:
        url = f"{self._base_url}/api/v2/Market/AccessToken"
        payload = {
            "consumerID": self._consumer_id,
            "consumerSecret": self._consumer_secret,
        }
        try:
            resp = httpx.post(url, json=payload, timeout=self._timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"SSI token refresh failed: {exc}") from exc

        body = resp.json()
        token = body.get("data", {}).get("accessToken") or body.get("accessToken")
        if not token:
            safe_info = {k: v for k, v in body.items() if k in _SAFE_RESPONSE_KEYS}
            raise ProviderError(f"SSI token response missing accessToken: {safe_info}")

        expires_in = int(body.get("data", {}).get("expiresIn", 3600))
        self._access_token = token
        self._token_expires_at = time.time() + expires_in
        logger.debug("SSI token refreshed, expires in %ds", expires_in)
        return token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            resp = httpx.get(url, headers=self._headers(), params=params, timeout=self._timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"SSI GET {path} failed: {exc}") from exc
        return resp.json()

    # ── MarketDataProvider methods ──────────────────────────────────────────

    def get_symbols(self, exchange: str | None = None) -> pd.DataFrame:
        """Return all listed securities from SSI."""
        all_rows: list[dict[str, Any]] = []
        page = 1
        page_size = 100

        while True:
            params: dict[str, Any] = {"pageIndex": page, "pageSize": page_size}
            if exchange:
                params["market"] = exchange
            body = self._get("/api/v2/Market/Securities", params=params)

            items = body.get("data", []) or []
            if not items:
                break
            all_rows.extend(items)
            if len(items) < page_size:
                break
            page += 1

        if not all_rows:
            return pd.DataFrame()

        df = pd.DataFrame(all_rows)
        if exchange and "comGroupCode" in df.columns:
            df = df[df["comGroupCode"].str.upper() == exchange.upper()]
        return df

    def get_daily_ohlcv(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Return daily OHLCV data for a symbol."""
        all_rows: list[dict[str, Any]] = []
        page = 1
        page_size = 100

        while True:
            params: dict[str, Any] = {
                "symbol": symbol,
                "fromDate": _fmt_date(start_date),
                "toDate": _fmt_date(end_date),
                "pageIndex": page,
                "pageSize": page_size,
            }
            body = self._get("/api/v2/Market/DailyOhlc", params=params)

            items = body.get("data", []) or []
            if not items:
                break
            all_rows.extend(items)
            if len(items) < page_size:
                break
            page += 1

        if not all_rows:
            return pd.DataFrame()

        df = pd.DataFrame(all_rows)
        df["symbol"] = symbol
        return df

    def get_security_details(self, symbol: str) -> dict[str, Any]:
        body = self._get("/api/v2/Market/Securities", params={"symbol": symbol, "pageSize": 1})
        items = body.get("data", [])
        if not items:
            raise ProviderError(f"SSI: no security details for {symbol}")
        return items[0]

    def get_index_list(self) -> pd.DataFrame:
        body = self._get("/api/v2/Market/Indices")
        items = body.get("data", []) or []
        return pd.DataFrame(items)

    def get_index_components(self, index_code: str) -> pd.DataFrame:
        body = self._get(
            "/api/v2/Market/IndexComponents",
            params={"indexCode": index_code},
        )
        items = body.get("data", []) or []
        return pd.DataFrame(items)

    def get_daily_index(self, index_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        params = {
            "indexId": index_code,
            "fromDate": _fmt_date(start_date),
            "toDate": _fmt_date(end_date),
            "pageIndex": 1,
            "pageSize": 500,
        }
        body = self._get("/api/v2/Market/DailyIndex", params=params)
        items = body.get("data", []) or []
        return pd.DataFrame(items)


def _fmt_date(d: str) -> str:
    """Ensure date is in dd/MM/yyyy format as expected by SSI API."""
    try:
        dt = datetime.strptime(d, "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except ValueError:
        return d
