"""Vietnam trading calendar utilities."""

from __future__ import annotations

import datetime

import numpy as np
import pandas as pd


# Vietnam public holidays (non-exhaustive; extend as needed)
# Format: (month, day) for fixed holidays; Tet is approximate and changes yearly
_FIXED_HOLIDAYS = [
    (1, 1),   # New Year's Day
    (4, 30),  # Liberation Day
    (5, 1),   # Labour Day
    (9, 2),   # National Day
]

# Hung Kings Day (Giỗ Tổ Hùng Vương) — 10th day of the 3rd lunar month.
# This is a lunar holiday and changes each year. Listed as observed Gregorian dates.
# IMPORTANT: Must be updated annually. Source: Vietnamese government decrees.
_HUNG_KINGS_DAY: dict[int, datetime.date] = {
    2018: datetime.date(2018, 4, 25),
    2019: datetime.date(2019, 4, 14),
    2020: datetime.date(2020, 4, 2),
    2021: datetime.date(2021, 4, 21),
    2022: datetime.date(2022, 4, 10),
    2023: datetime.date(2023, 4, 29),
    2024: datetime.date(2024, 4, 18),
    2025: datetime.date(2025, 4, 7),
    2026: datetime.date(2026, 3, 27),
    2027: datetime.date(2027, 4, 16),
    2028: datetime.date(2028, 4, 5),
    2029: datetime.date(2029, 4, 23),
    2030: datetime.date(2030, 4, 12),
}

# Vietnamese Tet (Lunar New Year) trading closure blocks.
# These are the actual HOSE/HNX closure dates (Gregorian) per official exchange announcements.
# IMPORTANT: Must be updated annually. Source: HOSE/HNX official circulars.
_TET_HOLIDAYS: dict[int, list[datetime.date]] = {
    2018: [
        datetime.date(2018, 2, 14), datetime.date(2018, 2, 15), datetime.date(2018, 2, 16),
        datetime.date(2018, 2, 19), datetime.date(2018, 2, 20),
    ],
    2019: [
        datetime.date(2019, 2, 4), datetime.date(2019, 2, 5), datetime.date(2019, 2, 6),
        datetime.date(2019, 2, 7), datetime.date(2019, 2, 8),
    ],
    2020: [
        datetime.date(2020, 1, 23), datetime.date(2020, 1, 24), datetime.date(2020, 1, 27),
        datetime.date(2020, 1, 28), datetime.date(2020, 1, 29),
    ],
    2021: [
        datetime.date(2021, 2, 10), datetime.date(2021, 2, 11), datetime.date(2021, 2, 12),
        datetime.date(2021, 2, 15), datetime.date(2021, 2, 16),
    ],
    2022: [
        datetime.date(2022, 1, 31), datetime.date(2022, 2, 1), datetime.date(2022, 2, 2),
        datetime.date(2022, 2, 3), datetime.date(2022, 2, 4),
    ],
    2023: [
        datetime.date(2023, 1, 20), datetime.date(2023, 1, 23), datetime.date(2023, 1, 24),
        datetime.date(2023, 1, 25), datetime.date(2023, 1, 26),
    ],
    2024: [
        datetime.date(2024, 2, 8), datetime.date(2024, 2, 9), datetime.date(2024, 2, 12),
        datetime.date(2024, 2, 13), datetime.date(2024, 2, 14),
    ],
    2025: [
        datetime.date(2025, 1, 27), datetime.date(2025, 1, 28), datetime.date(2025, 1, 29),
        datetime.date(2025, 1, 30), datetime.date(2025, 1, 31),
    ],
    2026: [
        datetime.date(2026, 2, 16), datetime.date(2026, 2, 17), datetime.date(2026, 2, 18),
        datetime.date(2026, 2, 19), datetime.date(2026, 2, 20),
    ],
    2027: [
        datetime.date(2027, 2, 5), datetime.date(2027, 2, 6), datetime.date(2027, 2, 7),
        datetime.date(2027, 2, 8), datetime.date(2027, 2, 9),
    ],
    2028: [
        datetime.date(2028, 1, 25), datetime.date(2028, 1, 26), datetime.date(2028, 1, 27),
        datetime.date(2028, 1, 28), datetime.date(2028, 1, 29),
    ],
    2029: [
        datetime.date(2029, 2, 12), datetime.date(2029, 2, 13), datetime.date(2029, 2, 14),
        datetime.date(2029, 2, 15), datetime.date(2029, 2, 16),
    ],
    2030: [
        datetime.date(2030, 2, 2), datetime.date(2030, 2, 3), datetime.date(2030, 2, 4),
        datetime.date(2030, 2, 5), datetime.date(2030, 2, 6),
    ],
}


def get_holidays(year: int) -> set[datetime.date]:
    """Return a set of Vietnam exchange holidays for the given year.

    Coverage: 2018–2030. Years outside this range will be missing Tet and Hung
    Kings Day — a warning is not raised here; callers that care about accuracy
    should check ``year in _TET_HOLIDAYS`` themselves.
    """
    holidays: set[datetime.date] = set()

    # Fixed-date statutory holidays
    for month, day in _FIXED_HOLIDAYS:
        try:
            holidays.add(datetime.date(year, month, day))
        except ValueError:
            pass

    # Hung Kings Day — lunar-based, changes every year
    if year in _HUNG_KINGS_DAY:
        holidays.add(_HUNG_KINGS_DAY[year])

    # Tet closure block
    if year in _TET_HOLIDAYS:
        holidays.update(_TET_HOLIDAYS[year])

    return holidays


def is_trading_day(date: datetime.date) -> bool:
    """Return True if the given date is a Vietnam exchange trading day."""
    if date.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return date not in get_holidays(date.year)


def get_trading_days(start: datetime.date, end: datetime.date) -> list[datetime.date]:
    """Return sorted list of trading days in [start, end]."""
    days = []
    current = start
    while current <= end:
        if is_trading_day(current):
            days.append(current)
        current += datetime.timedelta(days=1)
    return days


def add_trading_days(date: datetime.date, n: int) -> datetime.date:
    """Advance date by n trading days (positive n = forward, negative = backward)."""
    step = 1 if n >= 0 else -1
    remaining = abs(n)
    current = date
    while remaining > 0:
        current += datetime.timedelta(days=step)
        if is_trading_day(current):
            remaining -= 1
    return current


def t2_settlement_date(trade_date: datetime.date) -> datetime.date:
    """Return the T+2 settlement date (2 trading days after trade date)."""
    return add_trading_days(trade_date, 2)


def get_trading_calendar_df(start: datetime.date, end: datetime.date) -> pd.DataFrame:
    """Return a DataFrame with trading days and weekend/holiday flags."""
    date_range = pd.date_range(start=start, end=end, freq="D")
    records = []
    for ts in date_range:
        d = ts.date()
        records.append({
            "date": d,
            "is_trading_day": is_trading_day(d),
            "weekday": d.weekday(),
            "is_weekend": d.weekday() >= 5,
            "is_holiday": not is_trading_day(d) and d.weekday() < 5,
        })
    return pd.DataFrame(records)
