"""CSVFundamentalProvider — reads fundamentals from a CSV the operator
uploaded. Cheapest path to unblock the guardrail upgrade without a
paid vendor commitment.

Expected CSV schema (header row required):

    symbol,market_cap,listed_share,roe,net_profit_q1,net_profit_q2,
    net_profit_q3,net_profit_q4,audit_opinion,fiscal_period,is_vn30,is_vn100

* All numeric columns are floats; blanks are treated as ``None``.
* ``audit_opinion`` accepts the canonical English codes
  (``UNQUALIFIED`` / ``QUALIFIED`` / ``ADVERSE`` / ``DISCLAIMER``) AND
  common Vietnamese variants which are normalised on load:
    * "Chấp nhận toàn phần" → ``UNQUALIFIED``
    * "Ngoại trừ" → ``QUALIFIED``
    * "Trái ngược" → ``ADVERSE``
    * "Từ chối" → ``DISCLAIMER``
* ``is_vn30`` / ``is_vn100`` accept ``true``/``false``/``1``/``0``.

The provider reads the CSV lazily once per process and caches the
result in memory. Re-read by pointing at a new file path and
restarting the API.
"""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from schemas.fundamentals import Fundamentals

from .base import FundamentalDataProvider, FundamentalsProviderStatus

_AUDIT_NORMALISE: dict[str, str] = {
    "UNQUALIFIED": "UNQUALIFIED",
    "CLEAN": "UNQUALIFIED",
    "UNQUALIFIED_OPINION": "UNQUALIFIED",
    "CHẤP NHẬN TOÀN PHẦN": "UNQUALIFIED",
    "QUALIFIED": "QUALIFIED",
    "NGOẠI TRỪ": "QUALIFIED",
    "ADVERSE": "ADVERSE",
    "TRÁI NGƯỢC": "ADVERSE",
    "DISCLAIMER": "DISCLAIMER",
    "TỪ CHỐI": "DISCLAIMER",
}


def _to_float(raw: Any) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_bool(raw: Any) -> bool | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("true", "1", "yes", "y"):
        return True
    if s in ("false", "0", "no", "n"):
        return False
    if not s:
        return None
    return None


def _normalise_audit(raw: Any) -> str | None:
    if raw is None:
        return None
    key = str(raw).strip().upper()
    if not key:
        return None
    return _AUDIT_NORMALISE.get(key)


class CSVFundamentalProvider(FundamentalDataProvider):
    def __init__(self, csv_path: str | Path) -> None:
        self._path = Path(csv_path)
        self._rows: dict[str, Fundamentals] = {}
        self._loaded_at: str | None = None
        self._last_error: str | None = None
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if not self._path.exists():
            self._last_error = f"CSV not found: {self._path}"
            self._loaded = True
            return
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    sym = str(row.get("symbol") or "").upper().strip()
                    if not sym:
                        continue
                    npq_parts: list[float] = []
                    has_any_npq = False
                    for k in (
                        "net_profit_q1",
                        "net_profit_q2",
                        "net_profit_q3",
                        "net_profit_q4",
                    ):
                        v = _to_float(row.get(k))
                        if v is not None:
                            has_any_npq = True
                            npq_parts.append(v)
                    net_profit: list[float] | None = (
                        npq_parts if has_any_npq and len(npq_parts) == 4 else None
                    )
                    fundamentals = Fundamentals(
                        symbol=sym,
                        market_cap=_to_float(row.get("market_cap")),
                        market_cap_source="CSV" if row.get("market_cap") else None,
                        listed_share=_to_float(row.get("listed_share")),
                        roe=_to_float(row.get("roe")),
                        net_profit_last_4_quarters=net_profit,
                        audit_opinion=_normalise_audit(row.get("audit_opinion")),
                        fiscal_period=(
                            str(row.get("fiscal_period")).strip()
                            if row.get("fiscal_period")
                            else None
                        ),
                        fundamentals_source="CSV",
                        fundamentals_as_of=_parse_date(row.get("fundamentals_as_of")),
                        is_vn30=_to_bool(row.get("is_vn30")),
                        is_vn100=_to_bool(row.get("is_vn100")),
                    )
                    self._rows[sym] = fundamentals
            self._loaded_at = datetime.now(UTC).isoformat()
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"CSV load failed: {exc}"
        finally:
            self._loaded = True

    async def get_fundamentals(self, symbol: str) -> Fundamentals | None:
        self._load()
        return self._rows.get(symbol.upper())

    async def get_many(
        self, symbols: list[str]
    ) -> dict[str, Fundamentals | None]:
        self._load()
        return {s.upper(): self._rows.get(s.upper()) for s in symbols}

    async def list_known_symbols(self) -> list[str]:
        self._load()
        return sorted(self._rows.keys())

    async def status(self) -> FundamentalsProviderStatus:
        self._load()
        return FundamentalsProviderStatus(
            "CONNECTED" if self._rows else "CONFIG_MISSING",
            source_label=f"csv:{self._path.name}",
            last_loaded_at=self._loaded_at,
            symbols_covered=len(self._rows),
            last_error=self._last_error,
        )


def _parse_date(raw: Any) -> date | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
