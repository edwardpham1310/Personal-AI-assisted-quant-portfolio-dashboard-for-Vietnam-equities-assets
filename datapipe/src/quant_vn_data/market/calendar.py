"""Vietnam market calendar utilities.

Identifies trading days, public holidays, and missing date gaps.
Vietnam public holidays are approximated; update annually as needed.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

_VN_PUBLIC_HOLIDAYS_2024_2026: set[date] = {
    # 2024
    date(2024, 1, 1),   # New Year
    date(2024, 2, 8), date(2024, 2, 9), date(2024, 2, 10),
    date(2024, 2, 12), date(2024, 2, 13), date(2024, 2, 14),  # Tet
    date(2024, 4, 18),  # Hung Kings
    date(2024, 4, 30), date(2024, 5, 1),  # Reunification/Labour
    date(2024, 9, 2),   # National Day
    # 2025
    date(2025, 1, 1),
    date(2025, 1, 28), date(2025, 1, 29), date(2025, 1, 30),
    date(2025, 1, 31), date(2025, 2, 3),  # Tet
    date(2025, 4, 7),   # Hung Kings
    date(2025, 4, 30), date(2025, 5, 1),
    date(2025, 9, 1), date(2025, 9, 2),
    # 2026
    date(2026, 1, 1),
    date(2026, 2, 17), date(2026, 2, 18), date(2026, 2, 19),
    date(2026, 2, 20), date(2026, 2, 23),  # Tet
    date(2026, 4, 27),  # Hung Kings
    date(2026, 4, 30), date(2026, 5, 1),
    date(2026, 9, 2),
}


class VietnamMarketCalendar:
    def __init__(self, holidays: set[date] | None = None) -> None:
        self._holidays = holidays or _VN_PUBLIC_HOLIDAYS_2024_2026

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self._holidays

    def trading_days(self, start: date, end: date) -> list[date]:
        days = []
        cur = start
        while cur <= end:
            if self.is_trading_day(cur):
                days.append(cur)
            cur += timedelta(days=1)
        return days

    def missing_trading_dates(
        self,
        df: pd.DataFrame,
        symbol: str | None = None,
        date_col: str = "trading_date",
    ) -> list[date]:
        if df.empty or date_col not in df.columns:
            return []
        observed = set(pd.to_datetime(df[date_col]).dt.date)
        if not observed:
            return []
        start = min(observed)
        end = max(observed)
        expected = set(self.trading_days(start, end))
        missing = sorted(expected - observed)
        return missing
