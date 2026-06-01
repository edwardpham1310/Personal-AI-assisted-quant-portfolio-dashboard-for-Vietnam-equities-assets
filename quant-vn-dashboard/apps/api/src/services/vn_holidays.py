"""Vietnam Stock Exchange holiday calendar — hardcoded for 2026–2027.

Why a hardcoded set: the dashboard is a single-operator research tool;
adding a `pyluach` or `lunardate` dependency to compute Tết
programmatically is not justified. This list is sourced from the
official HOSE annual schedule (published by VSD/HOSE in December each
year) and must be reviewed annually.

Public API:

  * ``VN_MARKET_HOLIDAYS`` — frozenset[date] of non-trading days
    (Tết, Hùng Vương, 30/4 Reunification, 1/5 Labour, 2/9 National,
    plus any weekday make-ups). Weekends are NOT included.
  * ``is_business_day(d)`` — True iff d is a weekday AND not a holiday.
  * ``add_business_days(start, n)`` — T+N skipping weekends and
    holidays. The shared replacement for the per-module
    ``_add_business_days`` helpers.

Used by:
  * services.order_preview (settlement_date estimate)
  * services.paper_ledger (lazy T+2 settlement)
  * services.auto_trade_scheduler (cooldown calculations remain unchanged
    because cooldown is wall-clock minutes, not business-days)

Coverage horizon: 2026-01-01 → 2027-12-31. Calling add_business_days
past 2027-12-31 raises RuntimeError so we don't silently compute a
wrong date — operator must update the list.
"""

from __future__ import annotations

from datetime import date, timedelta

# ── Source data ─────────────────────────────────────────────────────────────
#
# HOSE 2026 schedule (published 2025-12, reviewed 2026-06):
#   * Tết Dương lịch (New Year): 2026-01-01 (Thu)
#   * Tết Nguyên đán: 2026-02-16 (Mon) → 2026-02-20 (Fri)  [5 weekdays]
#   * Giỗ Tổ Hùng Vương (10/3 âm lịch ≈ 2026-04-26 Sun) → make-up Mon
#     not formally observed in 2026 because the date falls on Sunday
#     and Vietnam labour code does not auto-shift the stock-exchange
#     holiday onto Monday; HOSE annual schedule footnote.
#   * Reunification Day: 2026-04-30 (Thu)
#   * Labour Day: 2026-05-01 (Fri)
#   * National Day: 2026-09-02 (Wed)
#
# HOSE 2027 schedule (provisional — refresh in Dec 2026):
#   * Tết Dương lịch: 2027-01-01 (Fri)
#   * Tết Nguyên đán: 2027-02-08 (Mon) → 2027-02-12 (Fri)
#   * Giỗ Tổ Hùng Vương: 2027-04-15 (Thu)
#   * Reunification + Labour: 2027-04-30 (Fri), 2027-05-03 (Mon make-up)
#   * National Day: 2027-09-02 (Thu)
#
# When refreshing: keep entries sorted, weekdays only.
VN_MARKET_HOLIDAYS: frozenset[date] = frozenset(
    {
        # 2026
        date(2026, 1, 1),
        date(2026, 2, 16),
        date(2026, 2, 17),
        date(2026, 2, 18),
        date(2026, 2, 19),
        date(2026, 2, 20),
        date(2026, 4, 30),
        date(2026, 5, 1),
        date(2026, 9, 2),
        # 2027
        date(2027, 1, 1),
        date(2027, 2, 8),
        date(2027, 2, 9),
        date(2027, 2, 10),
        date(2027, 2, 11),
        date(2027, 2, 12),
        date(2027, 4, 15),
        date(2027, 4, 30),
        date(2027, 5, 3),
        date(2027, 9, 2),
    }
)

_COVERAGE_END: date = date(2027, 12, 31)


def is_business_day(d: date) -> bool:
    """True iff ``d`` is Mon–Fri AND not in ``VN_MARKET_HOLIDAYS``."""
    return d.weekday() < 5 and d not in VN_MARKET_HOLIDAYS


def add_business_days(start: date, n: int) -> date:
    """Return ``start + n business days``, skipping weekends and VN holidays.

    Raises RuntimeError if the result would fall past the coverage
    horizon — this surfaces stale calendar data rather than silently
    returning a wrong settlement date.
    """
    if n < 0:
        raise ValueError("n must be >= 0")
    d = start
    added = 0
    while added < n:
        d = d + timedelta(days=1)
        if d > _COVERAGE_END:
            raise RuntimeError(
                f"VN holiday calendar coverage ends {_COVERAGE_END.isoformat()}. "
                f"Refresh VN_MARKET_HOLIDAYS before computing dates beyond it."
            )
        if is_business_day(d):
            added += 1
    return d
