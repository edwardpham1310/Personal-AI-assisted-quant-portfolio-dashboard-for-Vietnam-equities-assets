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

# Vietnamese Tet (Lunar New Year) approx dates — 5-day block starting the day before lunar NY
# These are business-day closures; exact dates vary. Add more years as needed.
_TET_HOLIDAYS: dict[int, list[datetime.date]] = {
    2018: [datetime.date(2018, 2, 14), datetime.date(2018, 2, 15), datetime.date(2018, 2, 16)],
    2019: [datetime.date(2019, 2, 4), datetime.date(2019, 2, 5), datetime.date(2019, 2, 6)],
    2020: [datetime.date(2020, 1, 23), datetime.date(2020, 1, 24), datetime.date(2020, 1, 27)],
    2021: [datetime.date(2021, 2, 10), datetime.date(2021, 2, 11), datetime.date(2021, 2, 12)],
    2022: [datetime.date(2022, 1, 31), datetime.date(2022, 2, 1), datetime.date(2022, 2, 2)],
    2023: [datetime.date(2023, 1, 20), datetime.date(2023, 1, 23), datetime.date(2023, 1, 24)],
    2024: [datetime.date(2024, 2, 8), datetime.date(2024, 2, 9), datetime.date(2024, 2, 12)],
    2025: [datetime.date(2025, 1, 28), datetime.date(2025, 1, 29), datetime.date(2025, 1, 30)],
}


def get_holidays(year: int) -> set[datetime.date]:
    """Return a set of Vietnam exchange holidays for the given year."""
    holidays: set[datetime.date] = set()

    # Fixed holidays
    for month, day in _FIXED_HOLIDAYS:
        try:
            holidays.add(datetime.date(year, month, day))
        except ValueError:
            pass

    # Hung Kings Day (3rd day of 3rd lunar month) — approx April 18 most years
    # We use April 18 as placeholder; precise date needs a lunar calendar library
    try:
        holidays.add(datetime.date(year, 4, 18))
    except ValueError:
        pass

    # Tet
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
