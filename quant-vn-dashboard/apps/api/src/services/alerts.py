"""Alert evaluation — pure, shared by the /alerts and /watchlists routes.

Trading safety: evaluation only *reads* the latest cached quote and reports
whether a threshold is currently met. It never persists, never recommends an
action, and never touches any order path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from schemas.alerts import Alert, AlertListResponse, AlertWithStatus
from schemas.market import Quote
from services import market_cache
from services.cache import Cache


def evaluate(condition: str, threshold: float, quote: Quote) -> bool | None:
    """Is the alert condition currently met for this quote?

    Returns None when the needed field is missing (cannot evaluate), so callers
    surface an honest "not evaluated" instead of a false negative.
    """
    if condition in ("price_above", "price_below"):
        price = quote.price
        if price is None:
            return None
        return price >= threshold if condition == "price_above" else price <= threshold
    if condition in ("pct_change_above", "pct_change_below"):
        pct = quote.change_pct
        if pct is None:
            return None
        return pct >= threshold if condition == "pct_change_above" else pct <= threshold
    return None


def build_status(row: dict[str, Any], quote: Quote | None) -> AlertWithStatus:
    """Map a stored alert row + optional quote to an evaluated AlertWithStatus."""
    alert = Alert.model_validate(row)
    if quote is None:
        return AlertWithStatus(**alert.model_dump(), evaluated=False)
    triggered = evaluate(alert.condition, alert.threshold, quote)
    return AlertWithStatus(
        **alert.model_dump(),
        evaluated=triggered is not None,
        currently_triggered=triggered,
        observed_price=quote.price,
        observed_change_pct=quote.change_pct,
        quote_stale=bool(getattr(quote, "stale", False)),
        quote_as_of=(quote.ts.isoformat() if isinstance(quote.ts, datetime) else None),
    )


async def build_alert_list(rows: list[dict[str, Any]], *, cache: Cache) -> AlertListResponse:
    """Evaluate alert rows against the latest cached quotes, sorted by symbol.

    Shared by the /alerts list endpoint and the watchlist-scoped alerts read so
    both surfaces evaluate identically. Honest-empty for no rows.
    """
    now_iso = datetime.now(UTC).isoformat()
    if not rows:
        return AlertListResponse(alerts=[], count=0, triggered_count=0, as_of=now_iso)
    symbols = sorted({str(r.get("symbol", "")).upper() for r in rows if r.get("symbol")})
    quotes = await market_cache.get_quotes(cache, symbols)
    qmap = {q.symbol.upper(): q for q in quotes if q is not None}
    statuses = [
        build_status(r, qmap.get(str(r.get("symbol", "")).upper())) for r in rows
    ]
    statuses.sort(key=lambda a: (a.symbol, a.created_at or ""))
    triggered = sum(1 for a in statuses if a.currently_triggered)
    return AlertListResponse(
        alerts=statuses, count=len(statuses), triggered_count=triggered, as_of=now_iso
    )
