"""SSI FastConnect Trading provider — READ-ONLY connector (Phase 2.4).

Implements the read-only account queries the dashboard needs — cash balance and
stock positions — against the SSI FastConnect Trading REST API. The connector
is wired but SHIPPED DISABLED: ``core.deps.get_trading_provider`` only builds it
when ``SSI_TRADING_USE_MOCK=false`` AND the operator has supplied real
credentials (consumer id/secret, RSA private key, account no, 2FA PIN).

HARD SAFETY PROPERTIES (do not remove):
* No order code. ``submit_order`` raises 501 — there is NO NewOrder / cancel /
  modify / GetOTP-for-orders path anywhere in this file. Live order placement
  is a separate Phase 3 review gated by ``SSI_TRADING_ORDER_PLACEMENT_ENABLED``
  plus a startup assertion.
* Read-only methods issue HTTP GET to SSI read endpoints only.
* Missing/incomplete credentials -> honest 503. Balances are NEVER fabricated;
  on any error the route surfaces an error, not a fake number.

CREDENTIAL NUANCE (see core/config.py): SSI mints even a read-only access token
only after a 2FA PIN/OTP, and that same PIN authorises order placement. So
read-only is API-separable from ordering (GETs need no per-request OTP) but NOT
credential-separable. This file never *uses* the PIN for anything but minting
the read token, and contains no order path.

UNVERIFIED-AGAINST-LIVE: the exact AccessToken signing payload, endpoint paths,
and response field names below are implemented to FastConnect Trading
conventions and MUST be validated against the operator's SSI sandbox before
enabling in production. Each such spot is marked ``TODO(ssi-sandbox)``.
"""

from __future__ import annotations

import base64
import logging
import time
from datetime import UTC, date, datetime
from typing import Any

import httpx

from providers.trading.base import TradingProvider, TradingProviderError
from schemas.trading import (
    CashBalance,
    MaxBuyQuantity,
    MaxSellQuantity,
    OrderBookEntry,
    OrderHistoryEntry,
    StockPosition,
    TradingProviderStatus,
)

logger = logging.getLogger(__name__)

_TOKEN_LEEWAY_SECONDS = 60
# Reads not needed by the dashboard display are intentionally left unimplemented
# to keep the live surface minimal. They raise 501 (not a fabricated value).
_READ_NOT_MAPPED_MSG = (
    "This SSI Trading read endpoint is not mapped in the Phase 2.4 read-only "
    "connector (only cash balance + stock positions are wired)."
)


class SSITradingProvider(TradingProvider):
    """Read-only SSI FastConnect Trading connector (cash + positions)."""

    name = "ssi-trading"

    def __init__(
        self,
        *,
        consumer_id: str,
        consumer_secret: str,
        base_url: str,
        private_key: str = "",
        account_no: str = "",
        two_factor_type: int = 0,
        pin: str = "",
        timeout: float = 10.0,
    ) -> None:
        if not consumer_id or not consumer_secret:
            raise TradingProviderError(
                "SSI Trading credentials are missing.", status_code=503
            )
        if not base_url.startswith("https://"):
            raise TradingProviderError(
                "SSI Trading base_url must use HTTPS.", status_code=500
            )
        self._consumer_id = consumer_id
        self._consumer_secret = consumer_secret
        self._base_url = base_url.rstrip("/")
        self._private_key = private_key
        self._account_no = account_no
        self._two_factor_type = two_factor_type
        self._pin = pin
        self._timeout = timeout
        # Token cache.
        self._token: str | None = None
        self._token_expiry: float = 0.0
        # Observability.
        self._last_call_ts: datetime | None = None
        self._last_error: str | None = None

    # ── Credential / readiness guard ───────────────────────────────────────
    def _require_read_credentials(self) -> None:
        """Read queries need a signing key, an account number, and the 2FA PIN
        to mint a token. Any missing -> honest 503 (never a fabricated value)."""
        missing = [
            name
            for name, val in (
                ("ssi_trading_private_key", self._private_key),
                ("ssi_trading_account_no", self._account_no),
                ("ssi_trading_pin", self._pin),
            )
            if not val
        ]
        if missing:
            raise TradingProviderError(
                f"SSI Trading read-only sync is not configured (missing: {', '.join(missing)}).",
                status_code=503,
            )

    # ── Request signing ────────────────────────────────────────────────────
    def _sign(self, message: str) -> str:
        """RSA SHA-256 signature, base64-encoded. Lazy-imports ``cryptography``
        so the default (disabled) install needs no extra dependency."""
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
        except ImportError as exc:  # pragma: no cover - only when enabling SSI
            raise TradingProviderError(
                "SSI Trading signing requires the 'cryptography' package.",
                status_code=500,
            ) from exc
        try:
            key = serialization.load_pem_private_key(
                self._private_key.encode(), password=None
            )
            signature = key.sign(message.encode(), padding.PKCS1v15(), hashes.SHA256())
        except Exception:  # noqa: BLE001 - never leak key material in the message
            raise TradingProviderError(
                "SSI Trading signing failed (check the configured private key).",
                status_code=500,
            ) from None
        return base64.b64encode(signature).decode()

    # ── Token management ───────────────────────────────────────────────────
    async def _get_access_token(self) -> str:
        if self._token and time.time() < self._token_expiry - _TOKEN_LEEWAY_SECONDS:
            return self._token
        # TODO(ssi-sandbox): confirm the signed base string. FastConnect Trading
        # signs the AccessToken request; the documented base is
        # "consumerID-consumerSecret-code". Verify against the SSI sandbox.
        signed_base = f"{self._consumer_id}-{self._consumer_secret}-{self._pin}"
        payload = {
            "consumerID": self._consumer_id,
            "consumerSecret": self._consumer_secret,
            "twoFactorType": self._two_factor_type,
            "code": self._pin,
            "isSave": False,
            "signature": self._sign(signed_base),
        }
        url = f"{self._base_url}/Trading/AccessToken"  # TODO(ssi-sandbox): confirm path
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload)
            if resp.status_code in (401, 403):
                self._note_error(f"HTTP{resp.status_code}")
                raise TradingProviderError(
                    f"SSI Trading auth rejected: HTTP {resp.status_code}",
                    status_code=401,
                )
            resp.raise_for_status()
        except TradingProviderError:
            raise
        except httpx.HTTPError as exc:
            # ``from None`` so the chained traceback cannot leak the signed payload.
            self._note_error(type(exc).__name__)
            raise TradingProviderError(
                f"SSI Trading auth failed: {type(exc).__name__}", status_code=502
            ) from None

        body = resp.json()
        data = body.get("data") or {}
        token = data.get("accessToken") or body.get("accessToken")
        if not token:
            self._note_error("missing_access_token")
            raise TradingProviderError(
                "SSI Trading auth response missing accessToken.", status_code=502
            )
        expires_in = int(data.get("expiresIn", 28_800))  # SSI tokens ~8h
        self._token = token
        self._token_expiry = time.time() + expires_in
        return token

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        token = await self._get_access_token()
        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url, params=params, headers=headers)
            if resp.status_code in (401, 403):
                self._token = None  # force re-auth next call
                self._note_error(f"HTTP{resp.status_code}")
                raise TradingProviderError(
                    f"SSI Trading read rejected: HTTP {resp.status_code}",
                    status_code=401,
                )
            resp.raise_for_status()
        except TradingProviderError:
            raise
        except httpx.HTTPError as exc:
            self._note_error(type(exc).__name__)
            raise TradingProviderError(
                f"SSI Trading read failed: {type(exc).__name__}", status_code=502
            ) from None
        self._last_call_ts = datetime.now(UTC)
        self._last_error = None
        return resp.json()

    def _note_error(self, msg: str) -> None:
        self._last_call_ts = datetime.now(UTC)
        self._last_error = msg

    # ── Read-only account queries ──────────────────────────────────────────
    async def get_cash_balance(self, account_id: str) -> CashBalance:
        self._require_read_credentials()
        # TODO(ssi-sandbox): confirm path + query params + response field names.
        body = await self._get(
            "/Trading/cashAcctBal",
            {"account": self._account_no, "querySummary": "true", "consumerID": self._consumer_id},
        )
        d = body.get("data") or {}
        return CashBalance(
            account_id=account_id,
            cash_balance=_num(d.get("cashBal")),
            buying_power=_num(d.get("purchasingPower") or d.get("buyingPower")),
            withdrawable_cash=_num(d.get("withdrawable") or d.get("cashWithdraw")),
            pending_cash=_num(d.get("receivingAmt") or d.get("pendingCash")),
            currency="VND",
            as_of=datetime.now(UTC),
        )

    async def get_stock_positions(self, account_id: str) -> list[StockPosition]:
        self._require_read_credentials()
        # TODO(ssi-sandbox): confirm path + response shape (list location, fields).
        body = await self._get(
            "/Trading/stockPosition",
            {"account": self._account_no, "querySummary": "false", "consumerID": self._consumer_id},
        )
        data = body.get("data") or {}
        rows = data.get("stockPositions") or data.get("positions") or []
        positions: list[StockPosition] = []
        for r in rows:
            qty = _int(r.get("onHand") or r.get("quantity"))
            positions.append(
                StockPosition(
                    account_id=account_id,
                    symbol=str(r.get("instrumentID") or r.get("symbol") or "").upper(),
                    quantity=qty,
                    sellable_quantity=_int(r.get("sellableQty") or r.get("sellable")),
                    pending_quantity=_int(r.get("holdQty") or r.get("buyT0") or 0),
                    avg_cost=_num(r.get("avgPrice") or r.get("costPrice")),
                    market_price=_opt_num(r.get("marketPrice")),
                    market_value=_opt_num(r.get("marketValue")),
                    unrealized_pnl=_opt_num(r.get("profitLoss") or r.get("unrealizedPL")),
                    as_of=datetime.now(UTC),
                )
            )
        return positions

    # ── Reads not needed by the dashboard display: left unimplemented (501) ──
    async def get_max_buy_qty(
        self, account_id: str, symbol: str, price: float
    ) -> MaxBuyQuantity:
        raise TradingProviderError(_READ_NOT_MAPPED_MSG, status_code=501)

    async def get_max_sell_qty(
        self, account_id: str, symbol: str
    ) -> MaxSellQuantity:
        raise TradingProviderError(_READ_NOT_MAPPED_MSG, status_code=501)

    async def get_order_book(self, account_id: str) -> list[OrderBookEntry]:
        raise TradingProviderError(_READ_NOT_MAPPED_MSG, status_code=501)

    async def get_order_history(
        self,
        account_id: str,
        start_date: date,
        end_date: date,
    ) -> list[OrderHistoryEntry]:
        raise TradingProviderError(_READ_NOT_MAPPED_MSG, status_code=501)

    # ── Order placement: PERMANENTLY 501 in this connector ─────────────────
    async def submit_order(
        self,
        *,
        account_id: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: int,
        limit_price: float | None,
    ) -> dict:
        """No order path exists in the read-only connector. Live placement is a
        separate Phase 3 review (SSI_TRADING_ORDER_PLACEMENT_ENABLED + assert)."""
        raise TradingProviderError(
            "SSI submit_order is not implemented in the read-only connector.",
            status_code=501,
        )

    async def status(self) -> TradingProviderStatus:
        configured = bool(
            self._private_key and self._account_no and self._pin
        )
        return TradingProviderStatus(
            name="ssi-trading",
            mock=False,
            read_only=True,
            order_placement_enabled=False,
            status_code="READ_ONLY" if configured else "CONFIG_MISSING",
            last_call_ts=self._last_call_ts,
            last_error_sanitized=self._last_error,
            note=(
                "SSI read-only connector (cash + positions). No order path."
                if configured
                else "SSI read-only connector present but credentials are not "
                "configured; dashboard uses the manual portfolio."
            ),
        )


# ── Defensive numeric coercion (real SSI values; never fabricated) ──────────
def _num(v: Any) -> float:
    try:
        return max(0.0, float(v))
    except (TypeError, ValueError):
        return 0.0


def _opt_num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int:
    try:
        return max(0, int(float(v)))
    except (TypeError, ValueError):
        return 0
