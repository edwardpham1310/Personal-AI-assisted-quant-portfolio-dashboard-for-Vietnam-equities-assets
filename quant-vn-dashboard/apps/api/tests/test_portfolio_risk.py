"""Portfolio risk score — pure model + route (Phase 2.5).

Read-only analytics. Verifies partial-awareness (only available components are
blended), explainability, and that nothing is fabricated. No trading paths.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from schemas.market import Quote
from services import market_cache
from services.portfolio_risk import RiskParams, compute_risk_score

_P = RiskParams(
    w_concentration=0.30, w_cash_buffer=0.15, w_regime=0.20,
    w_drawdown=0.20, w_volatility=0.15,
    target_cash_ratio=0.10, drawdown_cap=0.30, volatility_cap=0.40,
    min_history_points=5, trading_days_per_year=250,
)


def _components(result):
    return {c.key: c for c in result.components}


# ── Pure model ──────────────────────────────────────────────────────────────


def test_no_data_returns_null_score_and_all_unavailable() -> None:
    r = compute_risk_score(
        position_weights=[], total_market_value=0.0, cash=0.0, total_equity=0.0,
        regime_label=None, nav_history=[], as_of=None, params=_P,
    )
    assert r.score is None
    assert r.band == "unavailable"
    assert r.available_count == 0
    assert r.total_count == 6
    assert _components(r)["liquidity"].available is False
    assert _components(r)["liquidity"].reason == "no_adv_baseline"


def test_single_position_is_max_concentration() -> None:
    r = compute_risk_score(
        position_weights=[1.0], total_market_value=1000.0, cash=0.0, total_equity=1000.0,
        regime_label="UPTREND", nav_history=[], as_of=None, params=_P,
    )
    c = _components(r)
    assert c["concentration"].available and c["concentration"].score == 100.0
    assert c["cash_buffer"].available and c["cash_buffer"].score == 100.0  # no cash
    # regime: exposure 1.0 × UPTREND factor 0.3 → 30
    assert c["regime"].available and c["regime"].score == 30.0
    # no NAV history yet
    assert c["drawdown"].available is False
    assert c["volatility"].available is False
    assert r.score is not None


def test_diversified_lowers_concentration() -> None:
    r = compute_risk_score(
        position_weights=[0.25, 0.25, 0.25, 0.25], total_market_value=1000.0,
        cash=500.0, total_equity=1500.0, regime_label="MIXED",
        nav_history=[], as_of=None, params=_P,
    )
    # HHI = 4 * 0.0625 = 0.25 → 25
    assert _components(r)["concentration"].score == 25.0


def test_cash_only_portfolio_has_low_cash_risk_and_no_concentration() -> None:
    r = compute_risk_score(
        position_weights=[], total_market_value=0.0, cash=100.0, total_equity=100.0,
        regime_label=None, nav_history=[], as_of=None, params=_P,
    )
    c = _components(r)
    assert c["concentration"].available is False  # no priced positions
    assert c["cash_buffer"].available and c["cash_buffer"].score == 0.0  # full buffer
    assert r.score is not None


def test_history_components_available_with_enough_points() -> None:
    nav = [100.0, 110.0, 105.0, 120.0, 118.0, 130.0]  # 6 ≥ min 5
    r = compute_risk_score(
        position_weights=[1.0], total_market_value=1000.0, cash=0.0, total_equity=1000.0,
        regime_label="DOWNTREND", nav_history=nav, as_of="2026-06-01", params=_P,
    )
    c = _components(r)
    assert c["drawdown"].available and c["drawdown"].score is not None
    assert c["volatility"].available and c["volatility"].score is not None
    assert r.as_of == "2026-06-01"


def test_regime_unavailable_when_label_missing() -> None:
    r = compute_risk_score(
        position_weights=[1.0], total_market_value=1000.0, cash=0.0, total_equity=1000.0,
        regime_label=None, nav_history=[], as_of=None, params=_P,
    )
    rg = _components(r)["regime"]
    assert rg.available is False
    assert rg.reason == "regime_unavailable"


# ── Route ───────────────────────────────────────────────────────────────────


def _seed_quote(fake_cache, symbol: str, price: float) -> None:
    q = Quote(symbol=symbol, exchange="HOSE", price=price, ts=datetime.now(UTC), source="mock")
    fake_cache._data[market_cache.QUOTE_KEY.format(symbol=symbol)] = (
        json.dumps(q.model_dump(mode="json"), default=str),
        None,
    )


def test_risk_score_requires_auth(client: TestClient) -> None:
    assert client.get("/portfolio/risk-score").status_code == 401


def test_risk_score_no_account_is_null(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/portfolio/risk-score", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["score"] is None
    assert body["band"] == "unavailable"
    assert body["total_count"] == 6


def test_risk_score_with_position_is_partial_and_explainable(
    client: TestClient, auth_headers, fake_cache
) -> None:
    headers, _ = auth_headers()
    _seed_quote(fake_cache, "FPT", 70.0)
    client.post(
        "/portfolio/positions",
        headers=headers,
        json={"symbol": "FPT", "quantity": 100, "avg_cost": 50.0},
    )
    body = client.get("/portfolio/risk-score", headers=headers).json()
    assert body["score"] is not None
    comps = {c["key"]: c for c in body["components"]}
    assert comps["concentration"]["available"] is True
    assert comps["concentration"]["score"] == 100.0  # single position
    assert comps["concentration"]["detail"]  # explainable
    # No snapshots / cold regime / no ADV → honest unavailable.
    assert comps["drawdown"]["available"] is False
    assert comps["liquidity"]["available"] is False
    assert body["available_count"] < body["total_count"]


def test_risk_score_isolated_by_user(client: TestClient, auth_headers, fake_cache) -> None:
    headers_a, _ = auth_headers()
    _seed_quote(fake_cache, "FPT", 70.0)
    client.post(
        "/portfolio/positions",
        headers=headers_a,
        json={"symbol": "FPT", "quantity": 100, "avg_cost": 50.0},
    )
    headers_b, _ = auth_headers()
    body = client.get("/portfolio/risk-score", headers=headers_b).json()
    assert body["score"] is None  # user B has no account → no leak
