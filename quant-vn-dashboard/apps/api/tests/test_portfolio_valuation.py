"""Pure unit tests for portfolio_valuation."""

from __future__ import annotations

from datetime import UTC, date, datetime

from schemas.market import Quote
from services.portfolio_valuation import (
    build_pnl_waterfall,
    compute_summary,
    cost_breakdown,
    enrich_position,
    realized_pnl_from_trades,
)


def _quote(symbol: str, price: float, *, ts: datetime | None = None) -> Quote:
    return Quote(
        symbol=symbol,
        exchange="HOSE",
        price=price,
        ts=ts or datetime(2026, 5, 29, 7, 0, tzinfo=UTC),
        source="mock",
    )


# ── enrich_position ──────────────────────────────────────────────────────────


def test_enrich_position_with_market_price_computes_pnl() -> None:
    pos = {
        "id": "p1",
        "account_id": "a1",
        "symbol": "FPT",
        "exchange": "HOSE",
        "quantity": 100,
        "avg_cost": 50.0,
    }
    ep = enrich_position(pos, market_price=70.0, weight=0.5)
    assert ep.market_value == 7000.0
    assert ep.unrealized_pnl == 2000.0
    assert ep.unrealized_pnl_pct == 2000.0 / 5000.0
    assert ep.weight == 0.5
    assert ep.warnings == []


def test_enrich_position_without_market_price_warns() -> None:
    pos = {
        "id": "p1",
        "account_id": "a1",
        "symbol": "FPT",
        "quantity": 100,
        "avg_cost": 50.0,
    }
    ep = enrich_position(pos, market_price=None)
    assert ep.market_value is None
    assert ep.unrealized_pnl is None
    assert ep.unrealized_pnl_pct is None
    assert "quote_missing" in ep.warnings


def test_enrich_position_zero_cost_basis_returns_null_pct() -> None:
    # Bought at zero (rights issue?) — pct must be None, not div/0.
    pos = {
        "id": "p1",
        "account_id": "a1",
        "symbol": "FPT",
        "quantity": 100,
        "avg_cost": 0.0,
    }
    ep = enrich_position(pos, market_price=10.0)
    assert ep.market_value == 1000.0
    assert ep.unrealized_pnl == 1000.0
    assert ep.unrealized_pnl_pct is None


# ── compute_summary ──────────────────────────────────────────────────────────


def test_compute_summary_empty() -> None:
    summary, enriched = compute_summary([], [])
    assert summary.total_market_value == 0.0
    assert summary.total_cost_basis == 0.0
    assert summary.total_unrealized_pnl == 0.0
    assert summary.total_unrealized_pnl_pct is None
    assert summary.position_count == 0
    assert summary.by_strategy_tag == {}
    assert enriched == []


def test_compute_summary_skips_missing_quote_but_still_lists_position() -> None:
    positions = [
        {"id": "p1", "account_id": "a1", "symbol": "FPT", "quantity": 100, "avg_cost": 50.0, "strategy_tag": "tech"},
        {"id": "p2", "account_id": "a1", "symbol": "MWG", "quantity": 200, "avg_cost": 40.0, "strategy_tag": "retail"},
    ]
    quotes = [_quote("FPT", 70.0), None]
    summary, enriched = compute_summary(positions, quotes)

    # Only FPT's mark counts in market value.
    assert summary.total_market_value == 7000.0
    # Cost basis includes both (the cost is known regardless of price).
    assert summary.total_cost_basis == 100 * 50.0 + 200 * 40.0
    assert summary.position_count == 2

    # Surface a per-symbol warning.
    assert any("MWG" in w for w in summary.warnings)

    # Tag aggregation only over the priced position.
    assert summary.by_strategy_tag == {"tech": 7000.0}

    # MWG's enriched row carries the warning and null fields.
    mwg = next(e for e in enriched if e.symbol == "MWG")
    assert mwg.market_price is None
    assert "quote_missing" in mwg.warnings


def test_compute_summary_weights_sum_to_one_when_all_priced() -> None:
    positions = [
        {"id": "p1", "account_id": "a1", "symbol": "FPT", "quantity": 100, "avg_cost": 50.0},
        {"id": "p2", "account_id": "a1", "symbol": "MWG", "quantity": 100, "avg_cost": 40.0},
    ]
    quotes = [_quote("FPT", 60.0), _quote("MWG", 40.0)]
    summary, enriched = compute_summary(positions, quotes)
    total_w = sum(e.weight or 0.0 for e in enriched)
    assert abs(total_w - 1.0) < 1e-9
    assert summary.last_marked_at is not None


# ── realized_pnl_from_trades ─────────────────────────────────────────────────


def test_realized_pnl_simple_buy_then_partial_sell() -> None:
    # Buy 100 @ 50, then sell 60 @ 70 → realized = 60 * (70 - 50) = 1200.
    trades = [
        {"account_id": "a1", "symbol": "FPT", "side": "BUY", "quantity": 100,
         "price": 50.0, "trade_date": "2026-05-01"},
        {"account_id": "a1", "symbol": "FPT", "side": "SELL", "quantity": 60,
         "price": 70.0, "trade_date": "2026-05-05"},
    ]
    result = realized_pnl_from_trades(trades)
    assert result["total_realized"] == 1200.0
    assert result["by_symbol"]["FPT"]["realized"] == 1200.0
    assert result["by_symbol"]["FPT"]["cost_basis_at_sell"] == 60 * 50.0


def test_realized_pnl_weighted_average_cost_on_two_buys() -> None:
    # Buy 100 @ 50, buy 100 @ 70  → avg cost 60.
    # Sell 50 @ 80 → realized = 50 * (80 - 60) = 1000.
    trades = [
        {"account_id": "a1", "symbol": "FPT", "side": "BUY", "quantity": 100,
         "price": 50.0, "trade_date": "2026-05-01"},
        {"account_id": "a1", "symbol": "FPT", "side": "BUY", "quantity": 100,
         "price": 70.0, "trade_date": "2026-05-02"},
        {"account_id": "a1", "symbol": "FPT", "side": "SELL", "quantity": 50,
         "price": 80.0, "trade_date": "2026-05-05"},
    ]
    result = realized_pnl_from_trades(trades)
    assert abs(result["total_realized"] - 1000.0) < 1e-9


def test_realized_pnl_with_no_trades_is_zero() -> None:
    result = realized_pnl_from_trades([])
    assert result["total_realized"] == 0.0
    assert result["by_symbol"] == {}


# ── cost_breakdown ───────────────────────────────────────────────────────────


def test_cost_breakdown_all_period_sums_every_field() -> None:
    trades = [
        {"trade_date": "2026-05-01", "brokerage_fee": 100, "vat": 10,
         "sell_tax": 0, "cash_advance_fee": 0, "slippage_estimate": 5},
        {"trade_date": "2026-05-15", "brokerage_fee": 50, "vat": 5,
         "sell_tax": 30, "cash_advance_fee": 0, "slippage_estimate": 2},
    ]
    cb = cost_breakdown(trades, period="ALL")
    assert cb.brokerage_fee == 150
    assert cb.vat == 15
    assert cb.sell_tax == 30
    assert cb.slippage_estimate == 7
    assert cb.total == 150 + 15 + 30 + 0 + 7
    assert cb.trade_count == 2


def test_cost_breakdown_mtd_filters_prior_months() -> None:
    trades = [
        {"trade_date": "2026-04-15", "brokerage_fee": 999},
        {"trade_date": "2026-05-02", "brokerage_fee": 25},
    ]
    cb = cost_breakdown(trades, period="MTD", today=date(2026, 5, 29))
    assert cb.brokerage_fee == 25
    assert cb.trade_count == 1


def test_cost_breakdown_uses_asia_ho_chi_minh_for_default_today(
    monkeypatch,
) -> None:
    """A trade timestamped local-time HCMC midnight on June 1 must NOT fall
    into May's MTD when the engine is called at 23:59 UTC on May 31 — which
    is 06:59 HCMC on June 1. Default ``today`` should pick the HCMC date.
    """
    import services.portfolio_valuation as pv

    # Fix wall clock at 23:30 UTC on May 31, 2026 — that's 06:30 ICT on
    # June 1, so MTD must anchor to June 1 (not May 1).
    class _FixedDatetime:
        @classmethod
        def now(cls, tz=None):  # noqa: D401
            from datetime import datetime as _real

            instant = _real(2026, 5, 31, 23, 30, tzinfo=UTC)
            return instant.astimezone(tz) if tz is not None else instant

    monkeypatch.setattr(pv, "datetime", _FixedDatetime)

    trades = [
        # Filed on May 31 HCMC time — last day of May locally.
        {"trade_date": "2026-05-31", "brokerage_fee": 100},
        # Filed on June 1 HCMC time — start of the new MTD period.
        {"trade_date": "2026-06-01", "brokerage_fee": 25},
    ]
    cb = pv.cost_breakdown(trades, period="MTD")
    # MTD anchored at June 1 ICT → only the June 1 trade qualifies.
    assert cb.brokerage_fee == 25
    assert cb.trade_count == 1


# ── build_pnl_waterfall ──────────────────────────────────────────────────────


def test_waterfall_normal_orders_and_net_identity() -> None:
    wf = build_pnl_waterfall(realized=1200.0, unrealized=2000.0, costs=300.0, as_of="2026-05-29")
    assert [b.bucket for b in wf.buckets] == ["Realized", "Unrealized", "Costs", "Net"]
    vals = {b.bucket: b.value for b in wf.buckets}
    assert vals["Realized"] == 1200.0  # gross — unchanged by fees
    assert vals["Unrealized"] == 2000.0
    assert vals["Costs"] == -300.0  # costs negate
    assert vals["Net"] == 1200.0 + 2000.0 - 300.0
    # Net is the arithmetic sum of the prior three buckets (no double-count).
    assert abs(vals["Net"] - (vals["Realized"] + vals["Unrealized"] + vals["Costs"])) < 1e-9
    assert wf.as_of == "2026-05-29"


def test_waterfall_costs_only_is_negative_net() -> None:
    wf = build_pnl_waterfall(realized=0.0, unrealized=0.0, costs=202.0)
    vals = {b.bucket: b.value for b in wf.buckets}
    assert vals["Costs"] == -202.0
    assert vals["Net"] == -202.0
    assert wf.as_of is None


def test_waterfall_negative_net_when_costs_exceed_gains() -> None:
    wf = build_pnl_waterfall(realized=100.0, unrealized=0.0, costs=500.0)
    vals = {b.bucket: b.value for b in wf.buckets}
    assert vals["Net"] == -400.0


def test_waterfall_only_unrealized_no_trades() -> None:
    wf = build_pnl_waterfall(realized=0.0, unrealized=2000.0, costs=0.0, as_of="2026-05-29")
    vals = {b.bucket: b.value for b in wf.buckets}
    assert vals["Realized"] == 0.0
    assert vals["Unrealized"] == 2000.0
    assert abs(vals["Costs"]) < 1e-9
    assert vals["Net"] == 2000.0


def test_waterfall_no_double_count_realized_stays_gross() -> None:
    # Fees live ONLY in the Costs bucket; Realized is the gross figure verbatim.
    realized_gross = 1500.0
    wf = build_pnl_waterfall(realized=realized_gross, unrealized=0.0, costs=120.0)
    vals = {b.bucket: b.value for b in wf.buckets}
    assert vals["Realized"] == realized_gross
    assert vals["Costs"] == -120.0
    assert vals["Net"] == realized_gross - 120.0
