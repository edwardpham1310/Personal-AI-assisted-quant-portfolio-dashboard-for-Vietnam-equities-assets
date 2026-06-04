"""SSI Trading READ-ONLY connector tests (Phase 2.4).

These never reach the real SSI host. They verify:
  * Missing credentials -> honest 503 (NEVER a fabricated balance).
  * submit_order stays 501 even with full credentials (no order path).
  * cash + position responses map to the schemas.
  * auth failures surface 401 without leaking the PIN / secret.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from providers.trading.base import TradingProviderError
from providers.trading.ssi_trading import SSITradingProvider

# A throwaway 2048-bit key so _sign() runs without a real SSI key.
_KEY_PEM = (
    rsa.generate_private_key(public_exponent=65537, key_size=2048)
    .private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    .decode()
)

_PIN = "PIN_THAT_MUST_NOT_LEAK"
_SECRET = "SECRET_THAT_MUST_NOT_LEAK"


class _FakeResp:
    def __init__(self, status_code: int = 200, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type]


def _full_provider() -> SSITradingProvider:
    return SSITradingProvider(
        consumer_id="CID",
        consumer_secret=_SECRET,
        base_url="https://fc-tradeapi.ssi.com.vn",
        private_key=_KEY_PEM,
        account_no="0123456",
        two_factor_type=0,
        pin=_PIN,
        timeout=1.0,
    )


def _patch_http(monkeypatch, *, token_status=200, read_body=None, read_status=200):
    async def fake_post(self, url, **kw):  # token mint
        return _FakeResp(token_status, {"data": {"accessToken": "TKN", "expiresIn": 28800}})

    async def fake_get(self, url, **kw):  # read query
        return _FakeResp(read_status, read_body or {})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


# ── Credential gating (no fabrication) ──────────────────────────────────────


def test_missing_read_credentials_returns_503() -> None:
    # consumer creds present (construction ok) but no private key / account / pin.
    provider = SSITradingProvider(
        consumer_id="CID",
        consumer_secret=_SECRET,
        base_url="https://fc-tradeapi.ssi.com.vn",
    )
    with pytest.raises(TradingProviderError) as exc:
        asyncio.run(provider.get_cash_balance("acc-1"))
    assert exc.value.status_code == 503
    assert "not configured" in str(exc.value).lower()


def test_missing_consumer_credentials_rejected_at_construction() -> None:
    with pytest.raises(TradingProviderError) as exc:
        SSITradingProvider(
            consumer_id="", consumer_secret="", base_url="https://fc-tradeapi.ssi.com.vn"
        )
    assert exc.value.status_code == 503


# ── Order path is permanently closed ────────────────────────────────────────


def test_submit_order_is_501_even_with_full_credentials() -> None:
    provider = _full_provider()
    with pytest.raises(TradingProviderError) as exc:
        asyncio.run(
            provider.submit_order(
                account_id="acc-1", symbol="FPT", side="BUY",
                order_type="LIMIT", quantity=100, limit_price=90000,
            )
        )
    assert exc.value.status_code == 501


# ── Read mapping (real-shaped responses, mocked transport) ──────────────────


def test_cash_balance_maps_ssi_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(
        monkeypatch,
        read_body={
            "data": {
                "cashBal": 50_000_000,
                "purchasingPower": 48_500_000,
                "withdrawable": 30_000_000,
                "receivingAmt": 1_500_000,
            }
        },
    )
    cash = asyncio.run(_full_provider().get_cash_balance("acc-1"))
    assert cash.account_id == "acc-1"
    assert cash.cash_balance == 50_000_000
    assert cash.buying_power == 48_500_000
    assert cash.withdrawable_cash == 30_000_000
    assert cash.pending_cash == 1_500_000
    assert cash.currency == "VND"


def test_stock_positions_map_ssi_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(
        monkeypatch,
        read_body={
            "data": {
                "stockPositions": [
                    {
                        "instrumentID": "fpt",
                        "onHand": 200,
                        "sellableQty": 200,
                        "avgPrice": 80_000,
                        "marketPrice": 86_000,
                        "marketValue": 17_200_000,
                        "profitLoss": 1_200_000,
                    }
                ]
            }
        },
    )
    positions = asyncio.run(_full_provider().get_stock_positions("acc-1"))
    assert len(positions) == 1
    p = positions[0]
    assert p.symbol == "FPT"
    assert p.quantity == 200
    assert p.sellable_quantity == 200
    assert p.avg_cost == 80_000
    assert p.market_value == 17_200_000
    assert p.unrealized_pnl == 1_200_000


def test_empty_positions_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(monkeypatch, read_body={"data": {"stockPositions": []}})
    assert asyncio.run(_full_provider().get_stock_positions("acc-1")) == []


# ── Auth failure: surfaced, sanitized ───────────────────────────────────────


def test_auth_failure_does_not_leak_pin_or_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_http(monkeypatch, token_status=401)
    provider = _full_provider()
    with pytest.raises(TradingProviderError) as exc:
        asyncio.run(provider.get_cash_balance("acc-1"))
    assert exc.value.status_code == 401
    msg = str(exc.value)
    assert _PIN not in msg
    assert _SECRET not in msg


# ── Status reflects configuration without a network call ────────────────────


def test_status_reports_configured_vs_not() -> None:
    configured = asyncio.run(_full_provider().status())
    assert configured.mock is False
    assert configured.order_placement_enabled is False
    assert configured.status_code == "READ_ONLY"

    bare = SSITradingProvider(
        consumer_id="CID", consumer_secret=_SECRET,
        base_url="https://fc-tradeapi.ssi.com.vn",
    )
    st = asyncio.run(bare.status())
    assert st.status_code == "CONFIG_MISSING"
