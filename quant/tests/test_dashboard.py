import pandas as pd

from quant_vn.dashboard.analysis import analyze_symbol
from quant_vn.dashboard.static import build_dashboard_html


def _prices(close_start=100.0, step=1.0, rows=90):
    dates = pd.date_range("2024-01-01", periods=rows, freq="B")
    close = pd.Series([close_start + i * step for i in range(rows)], index=dates)
    return pd.DataFrame(
        {
            "open": close * 0.99,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": 1_000_000,
        },
        index=dates,
    )


def test_dashboard_signal_for_uptrend_is_constructive():
    signal = analyze_symbol("FPT", _prices())

    assert signal.symbol == "FPT"
    assert signal.label in {"Buy", "Strong Buy"}
    assert signal.score >= 2
    assert signal.sma20 is not None
    assert signal.sma50 is not None


def test_dashboard_html_contains_recommendation_table():
    prices = {"FPT": _prices()}
    signal = analyze_symbol("FPT", prices["FPT"])

    html = build_dashboard_html([signal], prices, "2024-01-01", "2024-05-01")

    assert "quant-vn Trading Dashboard" in html
    assert "Recommendation Summary" in html
    assert "FPT" in html
