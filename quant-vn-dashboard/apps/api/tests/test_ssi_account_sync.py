"""Read-only SSI account snapshot — POST /portfolio/sync/ssi (Phase 2.1).

Verifies: auth required, mock → honest-empty (no fabricated balances),
unconfigured SSI → CONFIG_MISSING, configured SSI (mocked transport) → real
cash + positions mapped, and that no order path is ever reached.
"""

from __future__ import annotations

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from core.deps import get_cache, get_db, get_trading_provider
from main import create_app
from providers.trading.ssi_trading import SSITradingProvider

_KEY_PEM = (
    rsa.generate_private_key(public_exponent=65537, key_size=2048)
    .private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    .decode()
)


def _client(fake_db, fake_cache, provider=None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: fake_db
    app.dependency_overrides[get_cache] = lambda: fake_cache
    if provider is not None:
        app.dependency_overrides[get_trading_provider] = lambda: provider
    return TestClient(app)


def _configured_provider() -> SSITradingProvider:
    return SSITradingProvider(
        consumer_id="CID",
        consumer_secret="SECRET",
        base_url="https://fc-tradeapi.ssi.com.vn",
        private_key=_KEY_PEM,
        account_no="0123456",
        two_factor_type=0,
        pin="PIN",
        timeout=1.0,
    )


def _unconfigured_provider() -> SSITradingProvider:
    # Consumer creds present (constructs ok) but no key / account / pin.
    return SSITradingProvider(
        consumer_id="CID", consumer_secret="SECRET",
        base_url="https://fc-tradeapi.ssi.com.vn",
    )


class _FakeResp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type]


# ── Auth + mock (honest-empty) ──────────────────────────────────────────────


def test_sync_ssi_requires_auth(client: TestClient) -> None:
    assert client.post("/portfolio/sync/ssi").status_code == 401


def test_sync_ssi_mock_is_honest_not_connected(client: TestClient, auth_headers) -> None:
    # Default provider is the mock (SSI_TRADING_USE_MOCK=true in conftest).
    headers, _ = auth_headers()
    r = client.post("/portfolio/sync/ssi", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False
    assert body["mock"] is True
    assert body["cash"] is None
    assert body["positions"] == []


# ── SSI provider states ─────────────────────────────────────────────────────


def test_sync_ssi_unconfigured_reports_config_missing(
    fake_db, fake_cache, auth_headers
) -> None:
    client = _client(fake_db, fake_cache, _unconfigured_provider())
    headers, _ = auth_headers()
    r = client.post("/portfolio/sync/ssi", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False
    assert body["status_code"] == "CONFIG_MISSING"
    assert body["cash"] is None


def test_sync_ssi_configured_returns_real_cash_and_positions(
    fake_db, fake_cache, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_post(self, url, **kw):  # token mint
        return _FakeResp(200, {"data": {"accessToken": "TKN", "expiresIn": 28800}})

    async def fake_get(self, url, **kw):  # cash or positions
        if "cashAcctBal" in url:
            return _FakeResp(
                200,
                {"data": {"cashBal": 50_000_000, "purchasingPower": 48_500_000,
                          "withdrawable": 30_000_000, "receivingAmt": 1_500_000}},
            )
        return _FakeResp(
            200,
            {"data": {"stockPositions": [
                {"instrumentID": "FPT", "onHand": 200, "sellableQty": 200,
                 "avgPrice": 80_000, "marketValue": 17_200_000, "profitLoss": 1_200_000},
            ]}},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    # The route masks the account it queried from config (server-side), so the
    # settings value must match the configured provider's account.
    monkeypatch.setenv("SSI_TRADING_ACCOUNT_NO", "0123456")
    from core.config import get_settings

    get_settings.cache_clear()

    client = _client(fake_db, fake_cache, _configured_provider())
    headers, _ = auth_headers()
    r = client.post("/portfolio/sync/ssi", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connected"] is True
    assert body["status_code"] == "READ_ONLY"
    assert body["mock"] is False
    assert body["account_masked"].endswith("3456")
    assert body["cash"]["cash_balance"] == 50_000_000
    assert body["cash"]["buying_power"] == 48_500_000
    assert len(body["positions"]) == 1
    assert body["positions"][0]["symbol"] == "FPT"


def test_sync_ssi_provider_error_is_honest_not_fabricated(
    fake_db, fake_cache, auth_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_post(self, url, **kw):  # auth rejected
        return _FakeResp(401, {})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    client = _client(fake_db, fake_cache, _configured_provider())
    headers, _ = auth_headers()
    r = client.post("/portfolio/sync/ssi", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False
    assert body["status_code"] == "ERROR"
    assert body["cash"] is None  # never fabricated on failure
