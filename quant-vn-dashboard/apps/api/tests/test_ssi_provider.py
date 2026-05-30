"""SSI provider unit tests.

These never reach the real SSI host. They exercise:
    * Construction with missing credentials → ProviderError(503).
    * Construction with non-HTTPS base_url → ProviderError(500).
    * Token-refresh failure messages do NOT leak the credential payload.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from providers.market_data import ProviderError, SSIFastConnectProvider


SECRET_VALUE = "SSI_SECRET_THAT_MUST_NOT_LEAK"
CONSUMER_ID = "SSI_CONSUMER_THAT_MUST_NOT_LEAK"


def _make_provider() -> SSIFastConnectProvider:
    return SSIFastConnectProvider(
        consumer_id=CONSUMER_ID,
        consumer_secret=SECRET_VALUE,
        base_url="https://fc-data.ssi.com.vn",
        timeout=1.0,
        max_retries=0,
    )


def test_missing_credentials_raises_503() -> None:
    with pytest.raises(ProviderError) as exc:
        SSIFastConnectProvider(
            consumer_id="",
            consumer_secret="",
            base_url="https://fc-data.ssi.com.vn",
            timeout=1.0,
            max_retries=0,
        )
    msg = str(exc.value)
    assert exc.value.status_code == 503
    assert "credentials" in msg.lower()
    # Defensive: empty strings can't leak, but make sure no other env names creep in.
    assert "consumerSecret" not in msg


def test_non_https_base_url_rejected() -> None:
    with pytest.raises(ProviderError) as exc:
        SSIFastConnectProvider(
            consumer_id="x",
            consumer_secret="y",
            base_url="http://insecure.example.com",
            timeout=1.0,
            max_retries=0,
        )
    assert exc.value.status_code == 500
    assert "HTTPS" in str(exc.value)


def test_token_refresh_error_does_not_leak_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """When SSI is unreachable, the resulting ProviderError must not echo the
    consumerSecret or consumerID from the request body."""

    async def fake_post(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("simulated connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    provider = _make_provider()
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider._refresh_token_locked())

    message = str(exc.value)
    assert SECRET_VALUE not in message
    assert CONSUMER_ID not in message
    assert "ConnectError" in message
    assert exc.value.status_code == 502


def test_get_request_error_does_not_leak_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same guarantee for GET calls — error messages stay safe under failure."""

    async def fake_get(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise httpx.ReadTimeout("simulated read timeout")

    # The implementation refreshes the token before issuing a GET; short-circuit
    # token retrieval so the GET path is what blows up.
    async def fake_token(self):  # type: ignore[no-untyped-def]
        return "stub-token"

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(SSIFastConnectProvider, "get_access_token", fake_token)

    provider = _make_provider()
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider._get("/api/v2/Market/Securities", {"pageSize": 1}))

    msg = str(exc.value)
    assert SECRET_VALUE not in msg
    assert CONSUMER_ID not in msg
    assert "ReadTimeout" in msg


def test_status_before_first_call() -> None:
    provider = _make_provider()
    status = asyncio.run(provider.status())
    assert status.name == "ssi"
    assert status.ready is True
    assert status.token_cached is False
    assert status.mock is False


@pytest.mark.asyncio
async def test_status_code_ready_when_creds_present_and_no_errors() -> None:
    """A fresh provider with creds and no recorded error reports READY."""
    from providers.market_data.ssi_fastconnect import SSIFastConnectProvider

    p = SSIFastConnectProvider(
        consumer_id="id",
        consumer_secret="secret",
        base_url="https://fc-data.ssi.com.vn",
        timeout=5.0,
        max_retries=0,
    )
    s = await p.status()
    assert s.status_code == "READY"
    assert s.ready is True
    assert s.mock is False


@pytest.mark.asyncio
async def test_status_code_auth_failed_after_token_refresh_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 401 from /AccessToken must surface as AUTH_FAILED on /status."""
    import httpx
    from providers.market_data.ssi_fastconnect import SSIFastConnectProvider
    from providers.market_data.base import ProviderError

    class _Resp:
        def __init__(self, code: int) -> None:
            self.status_code = code

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "err", request=None, response=None  # type: ignore[arg-type]
                )

        def json(self) -> dict:
            return {}

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def post(self, *_a, **_kw) -> _Resp:
            return _Resp(401)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    p = SSIFastConnectProvider(
        consumer_id="id",
        consumer_secret="secret",
        base_url="https://fc-data.ssi.com.vn",
        timeout=5.0,
        max_retries=0,
    )
    with pytest.raises(ProviderError):
        await p.get_access_token()
    s = await p.status()
    assert s.status_code == "AUTH_FAILED"
    assert s.ready is False


@pytest.mark.asyncio
async def test_status_code_provider_error_on_network_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A connection failure (not 401/403) must surface as PROVIDER_ERROR."""
    import httpx
    from providers.market_data.ssi_fastconnect import SSIFastConnectProvider
    from providers.market_data.base import ProviderError

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_a) -> None:
            return None

        async def post(self, *_a, **_kw):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    p = SSIFastConnectProvider(
        consumer_id="id",
        consumer_secret="secret",
        base_url="https://fc-data.ssi.com.vn",
        timeout=5.0,
        max_retries=0,
    )
    with pytest.raises(ProviderError):
        await p.get_access_token()
    s = await p.status()
    assert s.status_code == "PROVIDER_ERROR"
    assert s.ready is False


@pytest.mark.asyncio
async def test_status_code_stale_when_last_call_old() -> None:
    """``_last_call_ts`` older than 5 min must surface as STALE."""
    from datetime import datetime, timedelta, timezone
    from providers.market_data.ssi_fastconnect import SSIFastConnectProvider

    p = SSIFastConnectProvider(
        consumer_id="id",
        consumer_secret="secret",
        base_url="https://fc-data.ssi.com.vn",
        timeout=5.0,
        max_retries=0,
    )
    # Simulate a successful call more than 5 minutes ago.
    p._last_call_ts = datetime.now(timezone.utc) - timedelta(minutes=10)
    s = await p.status()
    assert s.status_code == "STALE"
    assert s.ready is False


def test_status_code_config_missing_via_status() -> None:
    """When creds are blank, __init__ refuses to construct (defence in
    depth), but if the caller bypassed the check, ``status()`` would also
    report CONFIG_MISSING. We use a manually-zeroed instance for the test.
    """
    from providers.market_data.ssi_fastconnect import SSIFastConnectProvider
    import asyncio

    # Construct a valid instance, then zero the creds to simulate the path.
    p = SSIFastConnectProvider(
        consumer_id="id",
        consumer_secret="secret",
        base_url="https://fc-data.ssi.com.vn",
        timeout=5.0,
        max_retries=0,
    )
    p._consumer_id = ""
    p._consumer_secret = ""
    s = asyncio.run(p.status())
    assert s.status_code == "CONFIG_MISSING"
    assert s.ready is False
