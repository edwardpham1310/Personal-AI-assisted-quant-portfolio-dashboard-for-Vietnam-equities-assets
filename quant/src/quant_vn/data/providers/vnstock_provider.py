"""vnstock data provider (optional dependency)."""

from __future__ import annotations

import pandas as pd

from .base import AbstractDataProvider


class VnstockProvider(AbstractDataProvider):
    """
    Fetches data using the vnstock library (pip install vnstock).

    Install optional dependency: pip install "quant-vn[vnstock]"
    """

    def __init__(self, source: str = "VCI"):
        try:
            from vnstock import Vnstock  # type: ignore[import]
        except ImportError as e:
            raise ImportError(
                "vnstock is not installed. Run: pip install 'quant-vn[vnstock]'"
            ) from e
        self._source = source
        self._vnstock = Vnstock

    def get_ohlcv(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        timeframe: str = "1D",
    ) -> pd.DataFrame:
        from vnstock import Vnstock  # type: ignore[import]

        stock = Vnstock().stock(symbol=symbol.upper(), source=self._source)
        df = stock.quote.history(start=start_date, end=end_date, interval=timeframe)

        # Normalise column names from vnstock output
        col_map = {
            "time": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        }
        df = df.rename(columns={c: col_map.get(c.lower(), c) for c in df.columns})
        df["symbol"] = symbol.upper()
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.sort_values("date").reset_index(drop=True)
        return df

    def get_symbols(self, exchange: str | None = None) -> list[str]:
        from vnstock import Vnstock  # type: ignore[import]

        listing = Vnstock().stock(symbol="VCB", source=self._source).listing
        df = listing.all_symbols()
        if exchange:
            df = df[df["exchange"].str.upper() == exchange.upper()]
        return df["ticker"].str.upper().tolist()
