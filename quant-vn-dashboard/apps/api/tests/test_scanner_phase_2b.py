"""Tests for the Phase 2.B scanner additions:

* ``vol_cov_20d`` — excludes current bar, handles zero mean,
  handles insufficient bars.
* ``consecutive_ceilings`` — counts correctly, handles missing
  ceiling, handles latest-only ceiling.
* ``ma200`` — computes with ≥200 bars, warns when fewer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from schemas.market import OHLCVBar
from services import scanner
from services.scanner import VOL_COV_WINDOW, _consecutive_ceilings


def _bars(
    closes: list[float],
    volumes: list[float] | None = None,
    *,
    ceilings: list[float | None] | None = None,
    start: datetime | None = None,
) -> list[OHLCVBar]:
    start = start or datetime(2026, 1, 2, tzinfo=UTC)
    vols = volumes or [1_000_000.0] * len(closes)
    out: list[OHLCVBar] = []
    for i, close in enumerate(closes):
        ceiling = ceilings[i] if ceilings is not None else None
        out.append(
            OHLCVBar(
                symbol="TEST",
                ts=start + timedelta(days=i),
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=vols[i],
                value=close * vols[i],
                ceiling_price=ceiling,
            )
        )
    return out


# ── Vol CoV ────────────────────────────────────────────────────────────────


def test_vol_cov_excludes_current_bar() -> None:
    """Today's volume must NOT be in the rolling window.

    Set today's volume to a wildly different value; the CoV must equal
    the CoV computed against the prior 20 bars only.
    """
    prior = [1_000_000.0] * VOL_COV_WINDOW
    today = 999_999_999.0
    volumes = prior + [today]
    bars = _bars([10.0] * (VOL_COV_WINDOW + 1), volumes=volumes)
    indicators = scanner.compute_indicators(bars)
    assert indicators.vol_cov_20d is not None
    # All prior volumes are identical → std = 0 → CoV = 0.0
    assert indicators.vol_cov_20d == pytest.approx(0.0, abs=1e-9)


def test_vol_cov_handles_zero_mean() -> None:
    """Mean=0 over the prior window returns None (no signal)."""
    volumes = [0.0] * VOL_COV_WINDOW + [42.0]  # current bar irrelevant
    bars = _bars([10.0] * (VOL_COV_WINDOW + 1), volumes=volumes)
    indicators = scanner.compute_indicators(bars)
    assert indicators.vol_cov_20d is None


def test_vol_cov_handles_insufficient_bars() -> None:
    """Fewer than window+1 bars returns None."""
    bars = _bars([10.0, 11.0, 12.0])
    indicators = scanner.compute_indicators(bars)
    assert indicators.vol_cov_20d is None


def test_vol_cov_typical_values() -> None:
    """Smoke check: alternating volumes produce a positive CoV."""
    alt = [1_000_000.0, 2_000_000.0] * (VOL_COV_WINDOW // 2)
    volumes = alt + [3_000_000.0]
    bars = _bars([10.0] * (VOL_COV_WINDOW + 1), volumes=volumes)
    indicators = scanner.compute_indicators(bars)
    assert indicators.vol_cov_20d is not None
    assert indicators.vol_cov_20d > 0.0


# ── Consecutive ceilings ───────────────────────────────────────────────────


def test_consecutive_ceilings_counts_correctly() -> None:
    """3 trailing bars with close == ceiling → count=3."""
    ceilings = [None] * 5 + [10.0, 10.5, 11.0]
    closes = [9.0] * 5 + [10.0, 10.5, 11.0]
    bars = _bars(closes, ceilings=ceilings)
    assert _consecutive_ceilings(bars) == 3


def test_consecutive_ceilings_breaks_on_non_ceiling() -> None:
    """A bar where close < ceiling breaks the streak."""
    ceilings = [10.0, 10.5, 11.0, 11.5]
    closes = [10.0, 10.4, 11.0, 11.5]  # bar 2 below its ceiling
    bars = _bars(closes, ceilings=ceilings)
    assert _consecutive_ceilings(bars) == 2


def test_consecutive_ceilings_handles_missing_ceiling_returns_none() -> None:
    """If NO bar carries a ceiling, return None (caller will warn)."""
    bars = _bars([10.0, 10.5, 11.0])
    assert _consecutive_ceilings(bars) is None


def test_consecutive_ceilings_handles_latest_only_ceiling() -> None:
    """Only the latest bar has a ceiling — streak is 0 or 1.

    With latest close==ceiling: 1.
    """
    ceilings: list[float | None] = [None, None, 11.0]
    closes = [10.0, 10.5, 11.0]
    bars = _bars(closes, ceilings=ceilings)
    assert _consecutive_ceilings(bars) == 1


def test_consecutive_ceilings_warning_when_no_history() -> None:
    """``missing_ceiling_price_for_consecutive_ceilings`` warning fires
    when no bar carries a ceiling. Verified via ``scan_symbol``."""
    bars = _bars([10.0] * 250)
    result = scanner.scan_symbol("TEST", bars)
    assert "missing_ceiling_price_for_consecutive_ceilings" in result.warnings


def test_consecutive_ceilings_warning_limited_history() -> None:
    """When only the latest bar carries a ceiling, scan_symbol warns
    ``limited_ceiling_history``."""
    ceilings = [None] * 249 + [10.0]
    closes = [10.0] * 250
    bars = _bars(closes, ceilings=ceilings)
    result = scanner.scan_symbol("TEST", bars)
    assert "limited_ceiling_history" in result.warnings


# ── MA200 ──────────────────────────────────────────────────────────────────


def test_ma200_calculates_when_ge_200_bars() -> None:
    """200+ bars → ma200 is the mean of the last 200 closes."""
    closes = [10.0 + i * 0.1 for i in range(250)]
    bars = _bars(closes)
    indicators = scanner.compute_indicators(bars)
    expected = sum(closes[-200:]) / 200
    assert indicators.ma200 is not None
    assert indicators.ma200 == pytest.approx(expected)
    assert indicators.price_above_ma200 is True


def test_ma200_returns_none_when_lt_200_bars() -> None:
    bars = _bars([10.0] * 100)
    indicators = scanner.compute_indicators(bars)
    assert indicators.ma200 is None
    assert indicators.price_above_ma200 is None


def test_ma200_warning_when_insufficient_history() -> None:
    """`insufficient_history_for_ma200` surfaces in scan_symbol warnings."""
    bars = _bars([10.0] * 100)
    result = scanner.scan_symbol("TEST", bars)
    assert "insufficient_history_for_ma200" in result.warnings


def test_price_below_ma200_when_close_below_average() -> None:
    closes = [100.0] * 200 + [50.0]  # latest is far below MA200=~100
    bars = _bars(closes)
    indicators = scanner.compute_indicators(bars)
    assert indicators.ma200 is not None
    assert indicators.price_above_ma200 is False


def test_bars_count_reflects_input_length() -> None:
    bars = _bars([10.0] * 137)
    indicators = scanner.compute_indicators(bars)
    assert indicators.bars_count == 137
