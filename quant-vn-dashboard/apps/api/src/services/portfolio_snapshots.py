"""Manual-portfolio NAV snapshots — the real backing store for the dashboard
equity curve.

The manual portfolio holds only current state, so there is nothing to draw a
historical equity curve from. This module computes the *same* NAV that
``/assets/summary`` reports (settled + pending + stock MV + advanced −
advance-liability) and appends one snapshot per account per trading day
(Asia/Ho_Chi_Minh) into ``portfolio_equity_snapshots``.

Forward-only and honest: the curve starts empty and grows one point per day a
snapshot is taken (dashboard-on-mount or an external cron hitting
``POST /portfolio/snapshots/run``). NAV history is never fabricated.

I/O is thin; the NAV math reuses the pure ``portfolio_valuation`` helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from core.security import AuthContext
from schemas.portfolio import EquityPoint
from services import market_cache, portfolio_valuation
from services.cache import Cache
from services.supabase_db import SupabaseDB

_ICT = ZoneInfo("Asia/Ho_Chi_Minh")

_TABLE = "portfolio_equity_snapshots"


@dataclass(frozen=True)
class NavSnapshot:
    total_equity: float
    cash: float
    stock_value: float
    currency: str
    warnings: list[str] = field(default_factory=list)


def _ict_today_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(_ICT)).astimezone(_ICT).date().isoformat()


async def _read_cash_for_nav(
    db: SupabaseDB, user: AuthContext, account_id: str
) -> dict[str, float] | None:
    """Pure read of the cash row (no auto-init side effect, unlike the
    /assets/summary helper). Returns ``None`` when there is no cash row."""
    rows = await db.select(_cash_table(), where={"account_id": account_id}, user_jwt=user.raw_token)
    if not rows:
        return None
    r = rows[0]
    return {
        "settled_cash": float(r.get("settled_cash") or 0.0),
        "pending_cash": float(r.get("pending_cash") or 0.0),
        "advanced_cash": float(r.get("advanced_cash") or 0.0),
        "cash_advance_liability": float(r.get("cash_advance_liability") or 0.0),
        "currency": r.get("currency") or "VND",
    }


def _cash_table() -> str:
    return "cash_balances"


async def compute_nav(
    db: SupabaseDB,
    user: AuthContext,
    cache: Cache,
    account_id: str,
) -> NavSnapshot:
    """Compute current NAV for an account — identical definition to
    ``/assets/summary.total_equity`` so the curve and the KPI never disagree."""
    cash = await _read_cash_for_nav(db, user, account_id)
    positions = await db.select(
        "manual_positions", where={"account_id": account_id}, user_jwt=user.raw_token
    )

    stock_value = 0.0
    warnings: list[str] = []
    if positions:
        symbols = [str(p["symbol"]).upper() for p in positions]
        quotes = await market_cache.get_quotes(cache, symbols)
        summary, _ = portfolio_valuation.compute_summary(positions, quotes)
        stock_value = summary.total_market_value
        warnings = list(summary.warnings)

    settled = cash["settled_cash"] if cash else 0.0
    pending = cash["pending_cash"] if cash else 0.0
    advanced = cash["advanced_cash"] if cash else 0.0
    advance_liability = cash["cash_advance_liability"] if cash else 0.0
    currency = cash["currency"] if cash else "VND"

    total_equity = settled + pending + stock_value + advanced - advance_liability
    cash_component = settled + pending + advanced - advance_liability

    return NavSnapshot(
        total_equity=total_equity,
        cash=cash_component,
        stock_value=stock_value,
        currency=currency,
        warnings=warnings,
    )


async def record_daily_snapshot(
    db: SupabaseDB,
    user: AuthContext,
    cache: Cache,
    account_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Upsert today's (ICT) NAV snapshot for ``account_id``. Idempotent per
    trading day: a second call on the same day recomputes and updates the
    existing row rather than appending a duplicate."""
    snapshot_date = _ict_today_iso(now)
    nav = await compute_nav(db, user, cache, account_id)

    existing = await db.select(
        _TABLE, where={"account_id": account_id, "snapshot_date": snapshot_date},
        user_jwt=user.raw_token,
    )
    payload = {
        "total_equity": nav.total_equity,
        "cash": nav.cash,
        "stock_value": nav.stock_value,
        "currency": nav.currency,
        "ts": (now or datetime.now(_ICT)).astimezone(_ICT).isoformat(),
    }
    if existing:
        await db.update(
            _TABLE, payload, where={"id": existing[0]["id"]}, user_jwt=user.raw_token
        )
    else:
        await db.insert(
            _TABLE,
            {
                "user_id": user.user_id,
                "account_id": account_id,
                "snapshot_date": snapshot_date,
                **payload,
            },
            user_jwt=user.raw_token,
        )
    return {
        "snapshot_date": snapshot_date,
        "total_equity": nav.total_equity,
        "warnings": nav.warnings,
    }


async def load_curve(
    db: SupabaseDB,
    user: AuthContext,
    account_id: str,
    *,
    start: str | None = None,
    end: str | None = None,
) -> list[EquityPoint]:
    """Read the stored NAV history for an account as ``EquityPoint`` rows,
    oldest first (ascending by ``snapshot_date``).

    ``start`` / ``end`` are inclusive ISO dates (YYYY-MM-DD). Because
    ``snapshot_date`` is a zero-padded ISO date, lexicographic comparison is
    chronological — so the window is a true *calendar* range, not a row count
    (snapshots are forward-only and may skip non-trading days). Empty list when
    nothing falls in the window (honest-empty)."""
    rows = await db.select(_TABLE, where={"account_id": account_id}, user_jwt=user.raw_token)
    rows = [r for r in rows if r.get("snapshot_date")]
    if start is not None:
        rows = [r for r in rows if str(r["snapshot_date"]) >= start]
    if end is not None:
        rows = [r for r in rows if str(r["snapshot_date"]) <= end]
    rows.sort(key=lambda r: str(r.get("snapshot_date")))
    return [
        EquityPoint(ts=str(r["snapshot_date"]), equity=float(r.get("total_equity") or 0.0))
        for r in rows
    ]
