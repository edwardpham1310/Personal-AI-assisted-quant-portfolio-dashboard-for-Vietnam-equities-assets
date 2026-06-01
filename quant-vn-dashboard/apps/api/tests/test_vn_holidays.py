"""Tests for the shared VN holiday calendar used by order_preview
and paper_ledger T+2 settlement."""

from __future__ import annotations

from datetime import date

import pytest

from services.vn_holidays import (
    VN_MARKET_HOLIDAYS,
    add_business_days,
    is_business_day,
)


def test_weekday_is_business_day() -> None:
    # 2026-06-01 is a Monday, not a holiday.
    assert is_business_day(date(2026, 6, 1)) is True


def test_saturday_is_not_business_day() -> None:
    assert is_business_day(date(2026, 6, 6)) is False  # Saturday


def test_sunday_is_not_business_day() -> None:
    assert is_business_day(date(2026, 6, 7)) is False  # Sunday


def test_tet_2026_is_holiday() -> None:
    for d in (
        date(2026, 2, 16),
        date(2026, 2, 17),
        date(2026, 2, 18),
        date(2026, 2, 19),
        date(2026, 2, 20),
    ):
        assert d in VN_MARKET_HOLIDAYS
        assert is_business_day(d) is False


def test_reunification_and_labour_day_2026() -> None:
    assert is_business_day(date(2026, 4, 30)) is False  # Reunification
    assert is_business_day(date(2026, 5, 1)) is False   # Labour


def test_t_plus_two_skips_weekend() -> None:
    # Mon 2026-06-01 + 2 BD = Wed 2026-06-03 (no weekend in between)
    assert add_business_days(date(2026, 6, 1), 2) == date(2026, 6, 3)


def test_t_plus_two_skips_weekend_when_starting_thursday() -> None:
    # Thu 2026-06-04 + 2 BD must skip Sat/Sun → Mon 2026-06-08
    assert add_business_days(date(2026, 6, 4), 2) == date(2026, 6, 8)


def test_t_plus_two_skips_tet_2026() -> None:
    # Fri 2026-02-13 + 2 BD: skip Sat/Sun then 5 weekdays of Tết →
    # next business day is Mon 2026-02-23, second is Tue 2026-02-24.
    assert add_business_days(date(2026, 2, 13), 2) == date(2026, 2, 24)


def test_t_plus_two_around_30_4_2026() -> None:
    # Wed 2026-04-29 + 2 BD: 30/4 + 1/5 are holidays, then Sat/Sun,
    # so the 2 business days land on Mon 2026-05-04 (1st BD) and
    # Tue 2026-05-05 (2nd BD).
    assert add_business_days(date(2026, 4, 29), 2) == date(2026, 5, 5)


def test_add_business_days_rejects_negative_n() -> None:
    with pytest.raises(ValueError):
        add_business_days(date(2026, 6, 1), -1)


def test_add_business_days_raises_past_coverage() -> None:
    # Coverage ends 2027-12-31. A large n from late-2027 must raise
    # rather than silently invent dates outside the calendar.
    with pytest.raises(RuntimeError, match="VN holiday calendar coverage"):
        add_business_days(date(2027, 12, 30), 5)


def test_order_preview_uses_shared_calendar() -> None:
    """Regression: ``order_preview._add_business_days`` must delegate
    to the shared helper so settlement_date matches paper_ledger."""
    from services.order_preview import _add_business_days as op_helper

    assert op_helper(date(2026, 4, 29), 2) == add_business_days(
        date(2026, 4, 29), 2
    )


def test_paper_ledger_uses_shared_calendar() -> None:
    from services.paper_ledger import _add_business_days as pl_helper

    assert pl_helper(date(2026, 4, 29), 2) == add_business_days(
        date(2026, 4, 29), 2
    )
