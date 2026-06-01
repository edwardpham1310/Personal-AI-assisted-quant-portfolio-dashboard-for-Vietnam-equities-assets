"""Order-preview calculator unit tests.

Pure-function tests — no HTTP, no providers. Exercises the math + rule
matrix against constructed Quote/Security/CashBalance/StockPosition
fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from schemas.market import Quote, Security
from schemas.trading import (
    CashBalance,
    OrderPreviewRequest,
    StockPosition,
)
from services.order_preview import (
    BROKERAGE_RATE,
    PreviewInputs,
    SELL_TAX_RATE,
    SLIPPAGE_RATE,
    VAT_RATE,
    calculate_preview,
)


_NOW = datetime(2026, 5, 31, tzinfo=timezone.utc)


def _quote(
    symbol: str = "FPT",
    *,
    price: float = 125000,
    ceiling: float | None = 130000,
    floor: float | None = 120000,
) -> Quote:
    return Quote(
        symbol=symbol,
        exchange="HOSE",
        price=price,
        reference_price=125000,
        ceiling_price=ceiling,
        floor_price=floor,
        change=0,
        change_pct=0,
        volume=1_000_000,
        ts=_NOW,
        stale=False,
        source="mock",
    )


def _security(symbol: str = "FPT", *, lot_size: int = 100, status: str = "ACTIVE") -> Security:
    return Security(symbol=symbol, exchange="HOSE", lot_size=lot_size, status=status)


def _cash(buying_power: float = 50_000_000, pending: float = 0.0) -> CashBalance:
    return CashBalance(
        account_id="ACC-X",
        cash_balance=buying_power + pending,
        buying_power=buying_power,
        withdrawable_cash=buying_power,
        pending_cash=pending,
        currency="VND",
        as_of=_NOW,
    )


def _position(qty: int = 200, sellable: int = 200, pending: int = 0) -> StockPosition:
    return StockPosition(
        account_id="ACC-X",
        symbol="FPT",
        exchange="HOSE",
        quantity=qty,
        sellable_quantity=sellable,
        pending_quantity=pending,
        avg_cost=80_000,
        market_price=125_000,
        market_value=125_000 * qty,
        unrealized_pnl=(125_000 - 80_000) * qty,
        as_of=_NOW,
    )


def _buy(qty: int = 100, price: float = 125000) -> OrderPreviewRequest:
    return OrderPreviewRequest(
        account_id="ACC-X", symbol="FPT", side="BUY",
        quantity=qty, limit_price=price, order_type="LIMIT",
    )


def _sell(qty: int = 100, price: float = 125000) -> OrderPreviewRequest:
    return OrderPreviewRequest(
        account_id="ACC-X", symbol="FPT", side="SELL",
        quantity=qty, limit_price=price, order_type="LIMIT",
    )


def test_buy_valid_basic_math() -> None:
    req = _buy()
    result = calculate_preview(
        PreviewInputs(req, _quote(), _security(), _cash(), None)
    )
    assert result.validation_status == "VALID"
    assert result.estimated_value == 12_500_000
    assert result.estimated_fees == round(12_500_000 * BROKERAGE_RATE)
    assert result.estimated_vat == round(result.estimated_fees * VAT_RATE)
    assert result.estimated_slippage == round(12_500_000 * SLIPPAGE_RATE)
    assert result.estimated_tax == 0
    assert result.total_cash_required is not None
    assert result.net_sell_proceeds is None
    assert result.is_live_order_submission_enabled is False


def test_sell_valid_net_proceeds_math() -> None:
    req = _sell()
    result = calculate_preview(
        PreviewInputs(req, _quote(), _security(), _cash(), _position())
    )
    assert result.validation_status == "WARN"  # T+2 settlement warning
    assert "T+2_SETTLEMENT" in " ".join(result.warnings)
    assert result.estimated_tax == round(12_500_000 * SELL_TAX_RATE)
    assert result.total_cash_required is None
    assert result.net_sell_proceeds is not None
    assert result.net_sell_proceeds < result.estimated_value


def test_buy_insufficient_cash_rejected() -> None:
    req = _buy(qty=1000, price=125_000)  # 125M required, only 50M available
    result = calculate_preview(
        PreviewInputs(req, _quote(), _security(), _cash(50_000_000), None)
    )
    assert result.validation_status == "REJECTED"
    assert any("INSUFFICIENT_CASH" in r for r in result.rejection_reasons)


def test_sell_insufficient_shares_rejected() -> None:
    req = _sell(qty=500)  # sellable=200
    result = calculate_preview(
        PreviewInputs(req, _quote(), _security(), _cash(), _position(sellable=200))
    )
    assert result.validation_status == "REJECTED"
    assert any("INSUFFICIENT_SHARES" in r for r in result.rejection_reasons)


def test_sell_no_position_rejected() -> None:
    req = _sell()
    result = calculate_preview(
        PreviewInputs(req, _quote(), _security(), _cash(), None)
    )
    assert result.validation_status == "REJECTED"
    assert any("NO_POSITION" in r for r in result.rejection_reasons)


def test_buy_lot_size_violation_rejected() -> None:
    req = _buy(qty=137)  # 137 % 100 != 0
    result = calculate_preview(
        PreviewInputs(req, _quote(), _security(lot_size=100), _cash(), None)
    )
    assert result.validation_status == "REJECTED"
    assert any("LOT_SIZE_VIOLATION" in r for r in result.rejection_reasons)


def test_buy_above_ceiling_rejected() -> None:
    req = _buy(price=140_000)  # ceiling=130k
    result = calculate_preview(
        PreviewInputs(req, _quote(ceiling=130_000), _security(), _cash(billion := 1_000_000_000), None)
    )
    assert result.validation_status == "REJECTED"
    assert any("PRICE_ABOVE_CEILING" in r for r in result.rejection_reasons)


def test_sell_below_floor_rejected() -> None:
    req = _sell(price=110_000)  # floor=120k
    result = calculate_preview(
        PreviewInputs(req, _quote(floor=120_000), _security(), _cash(), _position())
    )
    assert result.validation_status == "REJECTED"
    assert any("PRICE_BELOW_FLOOR" in r for r in result.rejection_reasons)


def test_buy_no_quote_falls_back_to_limit_only_warns() -> None:
    req = _buy()
    result = calculate_preview(
        PreviewInputs(req, None, _security(), _cash(), None)
    )
    assert any("NO_LIVE_QUOTE" in w for w in result.warnings)


def test_buy_no_cash_snapshot_warns() -> None:
    req = _buy()
    result = calculate_preview(
        PreviewInputs(req, _quote(), _security(), None, None)
    )
    assert any("NO_CASH_SNAPSHOT" in w for w in result.warnings)
    assert result.validation_status in ("WARN", "VALID")


def test_buy_partial_pending_cash_advance_warning() -> None:
    # Buying power short, but pending_cash covers the gap → WARN not REJECT.
    req = _buy(qty=100, price=125_000)  # need ~12.55M
    result = calculate_preview(
        PreviewInputs(
            req, _quote(), _security(),
            _cash(buying_power=5_000_000, pending=10_000_000),
            None,
        )
    )
    assert result.validation_status == "WARN"
    assert any("CASH_ADVANCE_REQUIRED" in w for w in result.warnings)


def test_inactive_symbol_rejected() -> None:
    req = _buy()
    result = calculate_preview(
        PreviewInputs(req, _quote(), _security(status="HALTED"), _cash(), None)
    )
    assert result.validation_status == "REJECTED"
    assert any("SYMBOL_NOT_TRADABLE" in r for r in result.rejection_reasons)


def test_liquidity_warning_when_order_exceeds_5pct_adv() -> None:
    req = _buy(qty=10_000, price=125_000)  # 1.25B
    # 5% of 20B = 1B cap → 1.25B exceeds cap
    result = calculate_preview(
        PreviewInputs(
            req, _quote(), _security(), _cash(buying_power=2_000_000_000), None,
            avg_value_20d=20_000_000_000,
        )
    )
    assert any("ORDER_EXCEEDS_5PCT_ADV" in w for w in result.warnings)


def test_settlement_date_is_t_plus_2() -> None:
    req = _buy()
    result = calculate_preview(
        PreviewInputs(req, _quote(), _security(), _cash(), None)
    )
    assert result.settlement_date is not None
    # Naive sanity: settlement date is a parseable ISO date.
    from datetime import date as _date
    parsed = _date.fromisoformat(result.settlement_date)
    assert parsed.weekday() < 5  # Mon-Fri (no holidays modelled)
