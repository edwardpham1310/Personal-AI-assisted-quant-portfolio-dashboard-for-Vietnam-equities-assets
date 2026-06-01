"""Phase 2.9 auto-trade scheduler helpers.

This module is intentionally NOT a background daemon. It hosts pure
functions used by the engine:

  * ``vn_market_is_open(now)`` — best-effort VN market-hours check
    (09:00–11:30 + 13:00–14:45 ICT, weekdays). No VN-holiday calendar
    yet — carry-over caveat shared with order_preview / paper_ledger.

  * ``cooldown_remaining_seconds(...)`` — given the user's
    ``auto_trade_orders`` rows for a given symbol+action, returns the
    cooldown gap in seconds (0 = no cooldown active).

Phase 2.9 does NOT include a long-running worker. Each tick is HTTP-
triggered by an external scheduler (cron / k8s CronJob / etc.) hitting
``POST /auto-trade/worker/tick`` with auth.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta, timezone

# Vietnam = UTC+7. Standardise on a constant offset; no DST in VN.
_VN_OFFSET = timedelta(hours=7)


def to_vn_local(now_utc: datetime) -> datetime:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    return now_utc.astimezone(timezone(_VN_OFFSET))


def vn_market_is_open(now_utc: datetime | None = None) -> bool:
    """True iff ``now_utc`` falls inside a VN HOSE/HNX continuous-trading
    window. Returns False at weekends and outside the morning/afternoon
    sessions. Holidays NOT modelled — same caveat as Phase 2.5/2.7/2.8.
    """
    now_utc = now_utc or datetime.now(UTC)
    local = to_vn_local(now_utc)
    if local.weekday() >= 5:  # Saturday/Sunday
        return False
    t = local.time()
    morning = time(9, 0) <= t <= time(11, 30)
    afternoon = time(13, 0) <= t <= time(14, 45)
    return morning or afternoon


def cooldown_remaining_seconds(
    *,
    recent_orders: Iterable[dict],
    symbol: str,
    action: str,
    cooldown_minutes: int,
    now_utc: datetime | None = None,
) -> int:
    """Return how many seconds until the cooldown for ``symbol`` +
    ``action`` lifts. 0 = no cooldown.

    Looks at the orders' ``created_at`` field for the most recent match.
    Failures to parse the timestamp are treated as "not in cooldown" so
    a poisoned row CAN bypass — counter-intuitive vs the fail-closed
    pattern elsewhere, BUT cooldown's job is throttling user behaviour,
    not security. If anyone is forging timestamps the audit/RLS layer
    catches them, not this.
    """
    if cooldown_minutes <= 0:
        return 0
    now = now_utc or datetime.now(UTC)
    cutoff = now - timedelta(minutes=cooldown_minutes)
    max_recent: datetime | None = None
    for o in recent_orders:
        # We treat all matching auto_trade_orders rows for this account
        # as potential cooldown sources, then filter on the linked
        # decision's (symbol, action) via the caller. Here we just
        # need the row's created_at.
        ts = o.get("created_at")
        if isinstance(ts, str):
            try:
                ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
        elif isinstance(ts, datetime):
            ts_dt = ts
        else:
            continue
        if ts_dt > cutoff:
            if max_recent is None or ts_dt > max_recent:
                max_recent = ts_dt
    if max_recent is None:
        return 0
    seconds_since = (now - max_recent).total_seconds()
    seconds_remaining = int(cooldown_minutes * 60 - seconds_since)
    return max(0, seconds_remaining)
