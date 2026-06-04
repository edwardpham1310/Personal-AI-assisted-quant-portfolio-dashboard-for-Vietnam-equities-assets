"""Pure helpers that derive market breadth + top movers from a snapshot of
``Quote`` objects the poller already fetched.

Design constraints (deliberate, audited):

* **No new I/O.** These are pure functions fed by quotes already in hand, so
  the poller can call them with zero extra SSI load.
* **Universe caveat.** The poller only fetches ``MARKET_CORE_SYMBOLS`` (+ any
  active SSE subscriptions) — a handful of large caps, NOT the whole market.
  The advance/decline counts are therefore breadth *over the polled set*, not
  true HOSE/HNX/UPCoM market breadth. Do not present them as full-market
  breadth without widening the polled universe.
  TODO(breadth): full-market breadth needs a separate periodic scan of all
  listed symbols with its own SSI cost budget — out of scope for the poller
  piggy-back.
* **Ceiling / floor.** Counted only for quotes that actually carry
  ``ceiling_price`` / ``floor_price`` (the SSI DailyStockPrice parser populates
  them when present; the mock provider does not). When absent the count stays
  ``0`` — we report "0 detected at limit", never a guessed band.
  TODO(breadth): we intentionally do NOT derive limits by applying ±7/10/15%
  to the reference price — VN limit bands vary by exchange and listing status
  (new listings, cautionary stocks) and shift after corporate actions.
* **by_value** uses ``Quote.value`` (session turnover in VND) directly — never
  ``price * volume`` (SSI volume units are not guaranteed to be shares). It is
  empty when ``value`` is absent (e.g. the mock provider leaves it ``None``).
* **by_volume** ranks by raw session ``Quote.volume`` (top-N). It is an
  ORDINAL activity ranking only — SSI volume units are not guaranteed to be
  shares, so magnitudes are not strictly comparable across symbols; ``by_value``
  (turnover in VND) remains the more robust liquidity measure. This replaces the
  former ``by_volume_spike``, which required an Average-Daily-Volume (ADV-20d)
  baseline a live quote cannot carry — so it was always empty. We do NOT
  fabricate a spike multiple.
  TODO(top_movers): a true volume-spike (today ÷ ADV-20d) needs daily-bar
  history — wire an ADV-20d lookup (datapipe ``avg_volume_20d`` or the scanner's
  ``_volume_ratio``) if/when the poller caches daily bars.

The output shapes match the frontend contracts exactly
(``MarketBreadth`` / ``TopMovers`` / ``Mover`` in
``apps/web/src/lib/mock/market.ts``) so no adapter is needed on either the REST
route or the SSE ``market-overview`` consumer.
"""

from __future__ import annotations

from typing import Any

from schemas.market import Quote

_EPS = 1e-9
_DEFAULT_TOP_N = 5


def _signed_change_pct(q: Quote) -> float | None:
    """Best-effort daily change as a fraction (0.0123 = +1.23%), or ``None``
    when the quote carries no usable reference."""
    if q.change_pct is not None:
        return q.change_pct
    if q.reference_price not in (None, 0) and q.reference_price:
        return (q.price - q.reference_price) / q.reference_price
    if q.change is not None and q.reference_price not in (None, 0) and q.reference_price:
        return q.change / q.reference_price
    return None


def empty_breadth() -> dict[str, int]:
    """Cold-cache / no-data breadth payload (full shape, all zeros)."""
    return {"advancers": 0, "decliners": 0, "unchanged": 0, "ceiling": 0, "floor": 0}


def empty_top_movers() -> dict[str, list[Any]]:
    """Cold-cache / no-data top-movers payload (full shape, empty lists).

    All four keys are always present so the frontend ``TopMoversCard`` (which
    indexes ``movers[tab]``) never hits ``undefined``.
    """
    return {"gainers": [], "losers": [], "by_value": [], "by_volume": []}


def compute_breadth(quotes: list[Quote]) -> dict[str, int]:
    """Advance/decline/unchanged + ceiling/floor counts over the polled set."""
    advancers = decliners = unchanged = ceiling = floor = 0
    for q in quotes:
        pct = _signed_change_pct(q)
        if pct is not None:
            if pct > _EPS:
                advancers += 1
            elif pct < -_EPS:
                decliners += 1
            else:
                unchanged += 1
        # Quotes with no usable reference are skipped entirely (not counted as
        # unchanged) so the numbers don't get silently distorted.
        if q.ceiling_price is not None and q.price >= q.ceiling_price - _EPS:
            ceiling += 1
        if q.floor_price is not None and q.price <= q.floor_price + _EPS:
            floor += 1
    return {
        "advancers": advancers,
        "decliners": decliners,
        "unchanged": unchanged,
        "ceiling": ceiling,
        "floor": floor,
    }


def _mover(q: Quote, pct: float, *, with_value: bool = False) -> dict[str, Any]:
    row: dict[str, Any] = {
        "symbol": q.symbol,
        "price": q.price,
        "change_pct": pct,
        "volume": q.volume or 0,
    }
    if with_value and q.value is not None:
        row["value"] = q.value
    return row


def compute_top_movers(quotes: list[Quote], top_n: int = _DEFAULT_TOP_N) -> dict[str, list[Any]]:
    """Top gainers / losers / by-value / by-volume over the polled set.

    ``by_volume`` is an ordinal raw-session-volume ranking (see module
    docstring); it replaces the former always-empty ``by_volume_spike``.
    """
    with_pct = [(q, _signed_change_pct(q)) for q in quotes]
    movable = [(q, pct) for q, pct in with_pct if pct is not None]

    gainers = sorted(
        (qp for qp in movable if qp[1] > _EPS), key=lambda qp: qp[1], reverse=True
    )[:top_n]
    losers = sorted((qp for qp in movable if qp[1] < -_EPS), key=lambda qp: qp[1])[:top_n]

    by_value_src = [(q, pct) for q, pct in movable if q.value is not None]
    by_value = sorted(by_value_src, key=lambda qp: qp[0].value or 0.0, reverse=True)[:top_n]

    # Ranked by raw session volume (ordinal only). Restricted to movable rows so
    # every mover carries a valid change_pct for the % column.
    by_volume_src = [(q, pct) for q, pct in movable if q.volume]
    by_volume = sorted(by_volume_src, key=lambda qp: qp[0].volume or 0.0, reverse=True)[:top_n]

    return {
        "gainers": [_mover(q, pct) for q, pct in gainers],
        "losers": [_mover(q, pct) for q, pct in losers],
        "by_value": [_mover(q, pct, with_value=True) for q, pct in by_value],
        "by_volume": [_mover(q, pct) for q, pct in by_volume],
    }
