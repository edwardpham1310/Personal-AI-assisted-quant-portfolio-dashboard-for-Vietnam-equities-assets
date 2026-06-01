"""Phase 2.5 trading route tests.

Coverage:
* Auth gating on every route.
* Read-only views via the mock provider.
* Order-preview submission produces a structured result.
* User isolation — one user cannot access another user's account.
* Forbidden submission routes return 501 + audit log.
* SSI Trading stub (when ``SSI_TRADING_USE_MOCK=false``) raises 501 cleanly
  without contacting the broker.
* No direct SSI Trading HTTP call exists in routes/providers
  (regression sweep).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ── Auth gating ────────────────────────────────────────────────────────────


def test_all_trading_routes_require_auth(client: TestClient) -> None:
    assert client.get("/trading").status_code == 401
    assert client.get("/trading/cash?account_id=x").status_code == 401
    assert client.get("/trading/positions?account_id=x").status_code == 401
    assert (
        client.get("/trading/max-buy-qty?account_id=x&symbol=FPT&price=1").status_code
        == 401
    )
    assert (
        client.get("/trading/max-sell-qty?account_id=x&symbol=FPT").status_code == 401
    )
    assert client.get("/trading/order-book?account_id=x").status_code == 401
    assert client.post("/trading/order-preview", json={}).status_code == 401
    assert client.post("/trading/new-order").status_code == 401
    assert client.post("/trading/submit-order").status_code == 401
    assert client.post("/trading/cancel-order").status_code == 401


# ── Account registration + masking ─────────────────────────────────────────


def test_mask_short_account_number_does_not_leak() -> None:
    """A 4-char account number must NOT pass through verbatim — masking
    must collapse to '****'. Regression guard: a refactor that always
    appended ``cleaned[-4:]`` would silently leak the full number for
    4-digit accounts."""
    from api.routes.trading import _mask_account_number

    assert _mask_account_number("1234") == "****"
    assert _mask_account_number("12") == "****"
    assert _mask_account_number("") == "****"
    # Punctuation and whitespace must be stripped before masking.
    assert _mask_account_number("1234-5678") == "****5678"
    assert _mask_account_number(" 1234 5678 ") == "****5678"
    # Long numbers keep the last-4.
    assert _mask_account_number("1234567890") == "****7890"


def test_order_preview_rejects_invalid_symbol_format(
    client: TestClient, auth_headers
) -> None:
    """The new symbol regex (^[A-Z0-9]+$) must reject Unicode lookalikes,
    HTML, and control chars at the FastAPI layer before they ever reach
    the calculator or the audit log."""
    headers, _ = auth_headers()
    account_id = _register(client, headers)
    for bad in ("FP T", "<script>", "F‮pt", "fpt", "FPT;DROP"):
        r = client.post(
            "/trading/order-preview",
            headers=headers,
            json={
                "account_id": account_id,
                "symbol": bad,
                "side": "BUY",
                "quantity": 100,
                "limit_price": 86000,
                "order_type": "LIMIT",
            },
        )
        assert r.status_code == 422, f"expected 422 for {bad!r}, got {r.status_code}"


def test_buy_price_equal_to_ceiling_does_not_reject(
    client: TestClient, auth_headers
) -> None:
    """Boundary: ``limit == ceiling`` is VALID (the check uses ``>``,
    not ``>=``). Pinning this prevents a silent regression to ``>=``
    that would block all ceiling-day orders."""
    headers, _ = auth_headers()
    account_id = _register(client, headers)
    # Mock provider's FPT ref = 86000; we don't have ceiling/floor exposed
    # via mock quotes, so the boundary is enforced when quote is None
    # (no rejection on band). We exercise the calculator directly to pin
    # the boundary.
    from datetime import datetime, timezone

    from schemas.market import Quote, Security
    from schemas.trading import (
        CashBalance,
        OrderPreviewRequest,
    )
    from services.order_preview import PreviewInputs, calculate_preview

    now = datetime(2026, 5, 31, tzinfo=timezone.utc)
    q = Quote(
        symbol="FPT", exchange="HOSE", price=86000, ceiling_price=92000,
        floor_price=80000, ts=now, stale=False, source="mock",
    )
    s = Security(symbol="FPT", exchange="HOSE", lot_size=100, status="ACTIVE")
    c = CashBalance(
        account_id="X", cash_balance=10_000_000, buying_power=10_000_000,
        withdrawable_cash=10_000_000, pending_cash=0, currency="VND", as_of=now,
    )
    req = OrderPreviewRequest(
        account_id="X", symbol="FPT", side="BUY",
        quantity=100, limit_price=92000, order_type="LIMIT",
    )
    result = calculate_preview(PreviewInputs(req, q, s, c, None))
    # Equality at ceiling must NOT be a REJECTED.
    assert not any("PRICE_ABOVE_CEILING" in r for r in result.rejection_reasons)


def test_sell_quantity_equal_to_sellable_does_not_reject(
    auth_headers,
) -> None:
    """Boundary: selling exactly sellable_quantity is VALID/WARN, not
    REJECTED. A regression flipping ``>`` to ``>=`` would block all
    full-position liquidations."""
    from datetime import datetime, timezone

    from schemas.market import Quote, Security
    from schemas.trading import (
        CashBalance,
        OrderPreviewRequest,
        StockPosition,
    )
    from services.order_preview import PreviewInputs, calculate_preview

    now = datetime(2026, 5, 31, tzinfo=timezone.utc)
    q = Quote(symbol="FPT", exchange="HOSE", price=86000, ts=now, stale=False, source="mock")
    s = Security(symbol="FPT", exchange="HOSE", lot_size=100, status="ACTIVE")
    pos = StockPosition(
        account_id="X", symbol="FPT", exchange="HOSE",
        quantity=200, sellable_quantity=200, pending_quantity=0,
        avg_cost=80000, market_price=86000, as_of=now,
    )
    c = CashBalance(
        account_id="X", cash_balance=0, buying_power=0,
        withdrawable_cash=0, pending_cash=0, currency="VND", as_of=now,
    )
    req = OrderPreviewRequest(
        account_id="X", symbol="FPT", side="SELL",
        quantity=200, limit_price=86000, order_type="LIMIT",
    )
    result = calculate_preview(PreviewInputs(req, q, s, c, pos))
    assert not any(
        "INSUFFICIENT_SHARES" in r for r in result.rejection_reasons
    )


def test_order_preview_route_handles_provider_failure(
    client: TestClient, auth_headers, monkeypatch
) -> None:
    """When the trading provider raises ``TradingProviderError`` inside
    ``_fetch_preview_context``, the preview must still render with
    warnings — never propagate the raw exception to a 500. This was
    untested and could regress silently."""
    from providers.trading import MockTradingProvider
    from providers.trading.base import TradingProviderError

    async def boom(*_a, **_kw):
        raise TradingProviderError("internal SSI stack trace", status_code=502)

    monkeypatch.setattr(
        MockTradingProvider, "get_cash_balance", boom
    )
    monkeypatch.setattr(
        MockTradingProvider, "get_stock_positions", boom
    )

    headers, _ = auth_headers()
    account_id = _register(client, headers)
    r = client.post(
        "/trading/order-preview",
        headers=headers,
        json={
            "account_id": account_id,
            "symbol": "FPT",
            "side": "BUY",
            "quantity": 100,
            "limit_price": 86000,
            "order_type": "LIMIT",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Without cash snapshot, calculator emits NO_CASH_SNAPSHOT.
    assert any("NO_CASH_SNAPSHOT" in w for w in body["warnings"])


def test_provider_error_response_does_not_leak_raw_message(
    client: TestClient, auth_headers, monkeypatch
) -> None:
    """When a route handler converts ``TradingProviderError`` to HTTP, the
    response body must contain only the ``client_safe_message`` — never
    the raw ``str(exc)`` which could carry SSI internals once Phase 3
    wires the real HTTP client."""
    from providers.trading import MockTradingProvider
    from providers.trading.base import TradingProviderError

    LEAKY = "SSI_TOKEN_xyz_or_internal_stack_trace"

    async def leaky_cash(*_a, **_kw):
        raise TradingProviderError(LEAKY, status_code=502)

    monkeypatch.setattr(MockTradingProvider, "get_cash_balance", leaky_cash)

    headers, _ = auth_headers()
    account_id = _register(client, headers)
    r = client.get(f"/trading/cash?account_id={account_id}", headers=headers)
    assert r.status_code == 502
    detail = r.json().get("detail", "")
    assert LEAKY not in detail, f"raw exc message leaked: {detail}"
    # And the response carries the safe pre-defined message.
    assert "Trading provider unavailable" in detail


def test_register_account_masks_number(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.post(
        "/trading/accounts",
        headers=headers,
        json={"account_number": "1234567890", "account_alias": "Main", "broker": "SSI"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["account_number_masked"] == "****7890"
    assert body["read_only_enabled"] is True
    assert body["trading_enabled"] is False
    # Full account number must NOT be in the response (or any audit log).
    assert "1234567890" not in r.text


def test_list_accounts_returns_only_user_owned(
    client: TestClient, auth_headers
) -> None:
    headers_a, uid_a = auth_headers()
    headers_b, _ = auth_headers()
    client.post(
        "/trading/accounts",
        headers=headers_a,
        json={"account_number": "1111", "broker": "SSI"},
    )
    r_b = client.get("/trading", headers=headers_b)
    assert r_b.status_code == 200
    assert r_b.json() == []
    r_a = client.get("/trading", headers=headers_a)
    assert r_a.status_code == 200
    assert len(r_a.json()) == 1


def test_other_user_cannot_access_account(client: TestClient, auth_headers) -> None:
    headers_a, _ = auth_headers()
    headers_b, _ = auth_headers()
    a = client.post(
        "/trading/accounts",
        headers=headers_a,
        json={"account_number": "9999", "broker": "SSI"},
    ).json()
    account_id = a["id"]
    r = client.get(f"/trading/cash?account_id={account_id}", headers=headers_b)
    assert r.status_code == 404


# ── Read-only views via mock provider ──────────────────────────────────────


def _register(client: TestClient, headers: dict) -> str:
    r = client.post(
        "/trading/accounts",
        headers=headers,
        json={"account_number": "5555", "broker": "SSI"},
    )
    return r.json()["id"]


def test_cash_returns_buying_power(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    account_id = _register(client, headers)
    # The mock provider returns ACC-DEFAULT shape only when account_id ==
    # 'ACC-DEFAULT' — for other ids it returns zeros. We use the API to
    # validate the response shape (which is what production users see).
    r = client.get(f"/trading/cash?account_id={account_id}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "buying_power" in body
    assert "pending_cash" in body
    assert "currency" in body and body["currency"] == "VND"


def test_positions_returns_list(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    account_id = _register(client, headers)
    r = client.get(f"/trading/positions?account_id={account_id}", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_max_buy_rejects_zero_price(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    account_id = _register(client, headers)
    r = client.get(
        f"/trading/max-buy-qty?account_id={account_id}&symbol=FPT&price=0",
        headers=headers,
    )
    assert r.status_code == 400


def test_max_sell_returns_shape(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    account_id = _register(client, headers)
    r = client.get(
        f"/trading/max-sell-qty?account_id={account_id}&symbol=FPT", headers=headers
    )
    assert r.status_code == 200
    body = r.json()
    assert "max_quantity" in body
    assert "sellable_quantity" in body


def test_order_book_returns_list(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    account_id = _register(client, headers)
    r = client.get(f"/trading/order-book?account_id={account_id}", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_order_history_rejects_inverted_dates(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    account_id = _register(client, headers)
    r = client.get(
        f"/trading/order-history?account_id={account_id}"
        "&start_date=2026-05-10&end_date=2026-05-01",
        headers=headers,
    )
    assert r.status_code == 400


# ── Order preview ──────────────────────────────────────────────────────────


def test_order_preview_buy_returns_structured_result(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    account_id = _register(client, headers)
    r = client.post(
        "/trading/order-preview",
        headers=headers,
        json={
            "account_id": account_id,
            "symbol": "FPT",
            "side": "BUY",
            "quantity": 100,
            "limit_price": 86000,
            "order_type": "LIMIT",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    for key in (
        "symbol", "side", "quantity", "order_type", "limit_price",
        "estimated_value", "estimated_fees", "estimated_tax", "estimated_vat",
        "estimated_slippage", "total_cash_required", "net_sell_proceeds",
        "validation_status", "warnings", "rejection_reasons",
        "is_live_order_submission_enabled", "settlement_date",
    ):
        assert key in body, f"missing key: {key}"
    assert body["is_live_order_submission_enabled"] is False
    assert body["net_sell_proceeds"] is None
    assert body["total_cash_required"] is not None


def test_order_preview_sell_no_position_rejected(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    account_id = _register(client, headers)
    r = client.post(
        "/trading/order-preview",
        headers=headers,
        json={
            "account_id": account_id,
            "symbol": "FPT",
            "side": "SELL",
            "quantity": 100,
            "limit_price": 86000,
            "order_type": "LIMIT",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["validation_status"] == "REJECTED"
    assert any("NO_POSITION" in r for r in body["rejection_reasons"])


def test_order_preview_rejects_lot_violation(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    account_id = _register(client, headers)
    r = client.post(
        "/trading/order-preview",
        headers=headers,
        json={
            "account_id": account_id,
            "symbol": "FPT",
            "side": "BUY",
            "quantity": 137,
            "limit_price": 86000,
            "order_type": "LIMIT",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["validation_status"] == "REJECTED"
    assert any("LOT_SIZE" in r for r in body["rejection_reasons"])


def test_order_preview_unknown_account_404(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.post(
        "/trading/order-preview",
        headers=headers,
        json={
            "account_id": "11111111-1111-1111-1111-111111111111",
            "symbol": "FPT",
            "side": "BUY",
            "quantity": 100,
            "limit_price": 86000,
            "order_type": "LIMIT",
        },
    )
    assert r.status_code == 404


# ── Forbidden submission endpoints ─────────────────────────────────────────


@pytest.mark.parametrize("path", ["/trading/new-order", "/trading/submit-order", "/trading/cancel-order"])
def test_forbidden_routes_return_501(client: TestClient, auth_headers, path: str) -> None:
    headers, _ = auth_headers()
    r = client.post(path, headers=headers, json={"symbol": "FPT", "quantity": 100})
    assert r.status_code == 501
    assert "Phase 2.5" in r.json()["detail"] or "preview" in r.json()["detail"].lower()


@pytest.mark.parametrize("path,action", [
    ("/trading/new-order", "trading.new_order_attempt_blocked"),
    ("/trading/submit-order", "trading.submit_order_attempt_blocked"),
    ("/trading/cancel-order", "trading.cancel_order_attempt_blocked"),
])
def test_forbidden_routes_persist_audit_log(
    client: TestClient, fake_db, auth_headers, path: str, action: str
) -> None:
    headers, uid = auth_headers()
    client.post(path, headers=headers, json={"symbol": "FPT"})
    rows = fake_db._tables["trading_audit_logs"]
    matching = [r for r in rows if r["user_id"] == uid and r["action"] == action]
    assert len(matching) >= 1
    assert matching[-1]["metadata"]["reason"] == "PHASE_2_5_LIVE_TRADING_DISABLED"


# ── Status endpoint ────────────────────────────────────────────────────────


def test_trading_status_reports_safe_mode(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/trading/status", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["mock"] is True
    assert body["read_only"] is True
    assert body["order_placement_enabled"] is False
    assert body["ssi_trading_order_placement_enabled"] is False


# ── SSI Trading stub: 501 without ever contacting SSI ──────────────────────


def test_ssi_trading_stub_emits_not_implemented_status() -> None:
    """The SSITradingProvider raises NotImplemented-style 501 on read calls
    but its ``status()`` returns a structured snapshot. This proves the
    deps factory can wire it without crashing — Phase 3 will replace the
    501 bodies with real SSI calls.
    """
    import asyncio

    from providers.trading import SSITradingProvider
    from providers.trading.base import TradingProviderError

    provider = SSITradingProvider(
        consumer_id="id",
        consumer_secret="secret",
        base_url="https://fc-tradeapi.ssi.com.vn",
        timeout=5.0,
    )
    status = asyncio.run(provider.status())
    assert status.status_code == "NOT_IMPLEMENTED"
    assert status.mock is False
    assert status.order_placement_enabled is False

    async def _try_cash() -> None:
        await provider.get_cash_balance("ACC-X")

    with pytest.raises(TradingProviderError) as exc:
        asyncio.run(_try_cash())
    assert exc.value.status_code == 501


def test_ssi_trading_stub_rejects_missing_credentials() -> None:
    from providers.trading import SSITradingProvider
    from providers.trading.base import TradingProviderError

    with pytest.raises(TradingProviderError) as exc:
        SSITradingProvider(
            consumer_id="",
            consumer_secret="",
            base_url="https://fc-tradeapi.ssi.com.vn",
            timeout=5.0,
        )
    assert exc.value.status_code == 503


def test_ssi_trading_stub_rejects_non_https_url() -> None:
    from providers.trading import SSITradingProvider
    from providers.trading.base import TradingProviderError

    with pytest.raises(TradingProviderError) as exc:
        SSITradingProvider(
            consumer_id="id",
            consumer_secret="secret",
            base_url="http://fc-tradeapi.ssi.com.vn",
            timeout=5.0,
        )
    assert exc.value.status_code == 500


# ── No-live-order regression sweep ─────────────────────────────────────────


_SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
_WEB_SRC_ROOT = (
    Path(__file__).resolve().parents[3] / "apps" / "web" / "src"
)

# Method-call patterns (require parens — these are CALLs, not mentions).
# Phase 2.8: ``submit_order`` is intentionally added to the
# TradingProvider ABC as the gated-scaffold for live submission. The
# sweep allow-lists the provider files + the orchestrator + its single
# route caller; everywhere else, ``submit_order(`` remains forbidden.
_FORBIDDEN_CALL_PATTERNS = [
    r"\bplaceOrder\s*\(",
    r"\bNewOrder\s*\(",
    r"\bplace_order\s*\(",
    r"\bsubmit_order\s*\(",
    r"\bnew_order\s*\(",
    r"\bsend_order\s*\(",
    r"\bcreate_order\s*\(",
    r"\bdispatch_order\s*\(",
    r"\bexecute_order\s*\(",
    r"\.place\s*\(",  # broker-client style: client.place(payload)
]

# Phase 2.8 allow-list: these source files legitimately contain
# ``submit_order(`` because they define / orchestrate / route the
# gated live submission scaffold. The orchestrator (services/live_orders.py)
# is the SINGLE caller of provider.submit_order, and the route handler
# in api/routes/trading.py (``submit_live_order_intent``) is the SINGLE
# HTTP entry into the orchestrator.
_PHASE_2_8_ALLOWED_FILES = {
    # Provider definitions of the method.
    "base.py",            # providers/trading/base.py (ABC)
    "mock_trading.py",    # providers/trading/mock_trading.py
    "ssi_trading.py",     # providers/trading/ssi_trading.py
    # Orchestrator + the single route entry that consume it.
    "live_orders.py",     # services/live_orders.py
    "trading.py",         # api/routes/trading.py (route handler)
    # Phase 2.9 guarded auto-trading engine calls
    # ``provider.submit_order`` via the same gated path.
    "auto_trade_engine.py",  # services/auto_trade_engine.py
}

# URL substrings — block accidental fetch("/api/orders/place"), POSTs to
# SSI's actual NewOrder/placeOrder URL fragments, etc. These would NOT be
# caught by the method-call patterns above because they're just strings.
_FORBIDDEN_URL_PATTERNS = [
    r"/NewOrder\b",
    r"/placeOrder\b",
    r"/orders/place\b",
    r"/order/submit\b",
    r"/Trading/Order\b",  # SSI FastConnect Trading namespace
]


def _sweep(root: Path, suffixes: tuple[str, ...]) -> list[str]:
    offenders: list[str] = []
    for path in root.rglob("*"):
        if path.suffix not in suffixes:
            continue
        # Skip the regression test itself — it intentionally contains the
        # patterns as raw-string regexes in this file (and possibly other
        # _FORBIDDEN_PATTERNS authors). We allow-list by filename.
        if path.name in {
            "test_trading_routes.py",
            "test_recommendation_no_orders.py",
            "no-direct-ssi.test.ts",
        } or path.name in _PHASE_2_8_ALLOWED_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pat in _FORBIDDEN_CALL_PATTERNS + _FORBIDDEN_URL_PATTERNS:
            for m in re.finditer(pat, text):
                line = text[: m.start()].count("\n") + 1
                src_line = text.splitlines()[line - 1]
                lower = src_line.lstrip().lower()
                # Allow comments/docstrings (`# ...`, `// ...`, `"""..."""`).
                if lower.startswith(("#", "//", '"', "'", "*")):
                    continue
                # We INTENTIONALLY no longer allow string-literal exemptions —
                # they were a real bypass (an attacker / future contributor
                # could write `path = "/NewOrder"; client.post(path, ...)`).
                offenders.append(
                    f"{path.relative_to(root)}:{line}: {src_line.strip()}"
                )
    return offenders


def test_no_live_order_calls_in_source() -> None:
    """No source file under ``apps/api/src/`` may contain a live SSI order
    submission call OR a URL substring resembling one.
    """
    offenders = _sweep(_SRC_ROOT, (".py",))
    assert not offenders, (
        "Found live order submission references in backend:\n"
        + "\n".join(offenders)
    )


def test_no_live_order_calls_in_frontend() -> None:
    """The dashboard frontend must NEVER reference an order-submission URL
    or call a method whose name resembles one. This sweeps ``.ts``/``.tsx``
    under ``apps/web/src/`` — caught a real gap noted by reviewers.
    """
    if not _WEB_SRC_ROOT.exists():  # pragma: no cover
        pytest.skip("frontend tree not present")
    offenders = _sweep(_WEB_SRC_ROOT, (".ts", ".tsx"))
    assert not offenders, (
        "Found live order submission references in frontend:\n"
        + "\n".join(offenders)
    )
