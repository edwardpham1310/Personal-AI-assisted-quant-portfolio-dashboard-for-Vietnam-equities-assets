"""VSDC corporate action provider.

VSDC is the Vietnam Securities Depository and Clearing Corporation.
This provider fetches corporate action data from VSDC's public disclosure pages.

MVP: stores raw HTML/JSON, parses common event types.
Extend by implementing _parse_<action_type> methods for additional event formats.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

import httpx
import pandas as pd

from .base import CorporateActionProvider, ProviderError

logger = logging.getLogger(__name__)


class VSDCProvider(CorporateActionProvider):
    name = "vsdc"

    # VSDC public search endpoint (may change — treat as best-effort)
    _BASE_URL = "https://www.vsdc.com.vn"
    _SEARCH_PATH = "/vi/hssv/timkiemsk"

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout

    def get_corporate_actions(
        self,
        symbol: str | None,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Fetch corporate actions from VSDC.

        Falls back to an empty DataFrame with a warning if the page structure
        changes or network is unavailable.
        """
        try:
            raw_html = self._fetch_html(symbol, start_date, end_date)
        except ProviderError as exc:
            logger.warning("VSDC fetch failed (%s) — returning empty DataFrame: %s", symbol, exc)
            return pd.DataFrame()

        rows = self._parse_html(raw_html, symbol)
        if not rows:
            logger.info("VSDC: no corporate actions parsed for %s", symbol)
            return pd.DataFrame()
        return pd.DataFrame(rows)

    def get_raw_html(self, symbol: str | None, start_date: str, end_date: str) -> bytes:
        """Return raw HTML for storage without parsing."""
        return self._fetch_html(symbol, start_date, end_date)

    def _fetch_html(self, symbol: str | None, start_date: str, end_date: str) -> bytes:
        params: dict[str, Any] = {
            "fromDate": _fmt_vsdc_date(start_date),
            "toDate": _fmt_vsdc_date(end_date),
        }
        if symbol:
            params["stockCode"] = symbol

        try:
            resp = httpx.get(
                f"{self._BASE_URL}{self._SEARCH_PATH}",
                params=params,
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (research/quant-vn-data)"},
            )
            resp.raise_for_status()
            return resp.content
        except httpx.HTTPError as exc:
            raise ProviderError(f"VSDC HTTP error: {exc}") from exc

    def _parse_html(self, html: bytes, symbol: str | None) -> list[dict[str, Any]]:
        """Best-effort HTML parser.  Returns a list of raw dicts.

        In a production system you would use BeautifulSoup here.
        This MVP version extracts common table rows using regex patterns.
        Install beautifulsoup4 and lxml for a more robust implementation.
        """
        try:
            from bs4 import BeautifulSoup  # type: ignore[import]
            return _parse_with_bs4(html, symbol)
        except ImportError:
            logger.debug("BeautifulSoup not installed — using regex VSDC parser")
            return _parse_with_regex(html, symbol)


def _parse_with_bs4(html: bytes, symbol: str | None) -> list[dict[str, Any]]:
    from bs4 import BeautifulSoup  # type: ignore[import]

    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []

    for row in soup.select("table tr"):
        cells = [td.get_text(strip=True) for td in row.select("td")]
        if len(cells) < 5:
            continue
        entry: dict[str, Any] = {
            "symbol": cells[0] or symbol,
            "isin": cells[1] if len(cells) > 1 else None,
            "action_type": cells[2] if len(cells) > 2 else None,
            "record_date": cells[3] if len(cells) > 3 else None,
            "ex_date": cells[4] if len(cells) > 4 else None,
            "raw_text": "|".join(cells),
            "source": "vsdc",
            "parse_status": "PARSED",
        }
        rows.append(entry)

    return rows


def _parse_with_regex(html: bytes, symbol: str | None) -> list[dict[str, Any]]:
    text = html.decode("utf-8", errors="replace")
    date_pattern = r"\d{2}/\d{2}/\d{4}"
    dates = re.findall(date_pattern, text)

    if not dates:
        return []

    return [{
        "symbol": symbol,
        "raw_text": text[:2000],
        "source": "vsdc",
        "parse_status": "RAW_ONLY",
    }]


def _fmt_vsdc_date(d: str) -> str:
    """Convert yyyy-mm-dd to dd/mm/yyyy for VSDC query params."""
    try:
        from datetime import datetime
        dt = datetime.strptime(d, "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except ValueError:
        return d
