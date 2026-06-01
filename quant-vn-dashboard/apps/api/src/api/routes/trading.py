"""Phase 2.5 SSI Trading read-only + order-preview routes.

ALL routes here are either:
* Read-only views of broker state (accounts/cash/positions/orders), or
* The pure-calculation order preview, or
* Forbidden submission endpoints that ALWAYS return 501 + emit a
  security audit log. They never call SSI.

Nothing in this module instantiates an SSI submission path. The
TradingProvider ABC does not declare ``place_order`` — the type system
enforces the safety, not just policy.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from core.config import Settings, get_settings
from core.deps import (
    get_db,
    get_market_provider,
    get_trading_provider,
)
from core.logging import get_logger
from core.security import AuthContext, get_current_user
from providers.market_data import MarketDataProvider, ProviderError
from providers.trading import TradingProvider, TradingProviderError
from schemas.trading import (
    CashBalance,
    MaxBuyQuantity,
    MaxSellQuantity,
    OrderBookEntry,
    OrderHistoryEntry,
    OrderPreviewRequest,
    OrderPreviewResult,
    StockPosition,
    TradingAccount,
    TradingAccountCreate,
)
from schemas.live_orders import (
    ConfirmRequest,
    LiveOrderAuditAction,
    LiveOrderIntent,
    LiveOrderIntentCreate,
    LiveOrderIntentResult,
    LiveOrderIntentStatus,
    LiveOrderSubmission,
)
from services.auto_trade import reauth_is_fresh
from services.live_orders import (
    SubmitContext,
    compute_gate_status,
    is_legal_transition,
    revalidate_for_submit,
    sanitize_request_payload,
    synthetic_broker_response,
)
from services.order_preview import PreviewInputs, calculate_preview
from services.supabase_db import SupabaseDB

logger = get_logger(__name__)
router = APIRouter()


# ── Helpers ─────────────────────────────────────────────────────────────────


def _mask_account_number(raw: str) -> str:
    """Reduce ``123456789`` to ``****6789``. Never store the full number."""
    cleaned = "".join(ch for ch in raw if ch.isalnum())
    if len(cleaned) <= 4:
        return "****"
    return f"****{cleaned[-4:]}"


async def _audit_event(
    db: SupabaseDB,
    user: AuthContext,
    action: str,
    request: Request,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Best-effort persistent audit log + structured Python log.

    Never raises — audit failures must not block the user's request, but
    they MUST always log to stdout so they're discoverable in the
    operator's logs.
    """
    payload = {
        "user_id": user.user_id,
        "action": action,
        "metadata": metadata or {},
        "ip_address": (
            request.client.host if request.client else None
        ) if request else None,
        "user_agent": (
            request.headers.get("user-agent") if request else None
        ),
    }
    logger.info(
        "trading.audit user=%s action=%s metadata_keys=%s",
        user.user_id,
        action,
        list((metadata or {}).keys()),
    )
    try:
        await db.insert(
            "trading_audit_logs", payload, user_jwt=user.raw_token
        )
    except Exception as exc:  # pragma: no cover - audit must never block
        logger.warning(
            "trading.audit_persist_failed action=%s err=%s",
            action,
            type(exc).__name__,
        )


async def _resolve_user_account(
    db: SupabaseDB, user: AuthContext, account_id: str
) -> dict[str, Any]:
    """Return the account row, 404 if not owned by ``user``.

    Account-id authorization is enforced THREE ways:
      1. RLS at the database layer (`auth.uid() = user_id`).
      2. The FakeSupabaseDB equivalent (``_owned_by``).
      3. An explicit ``user_id`` filter in the ``where`` clause below
         (belt-and-suspenders: protects against an operator dropping RLS
         in production or a Postgres misconfiguration). Without this
         line, a single RLS regression would silently bypass ownership.
    """
    rows = await db.select(
        "trading_accounts",
        where={"id": account_id, "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Trading account not found.")
    return rows[0]


def _trading_error_to_http(exc: TradingProviderError) -> HTTPException:
    """Convert a TradingProviderError into an HTTPException that NEVER
    contains the raw exception message. Operator detail is in the Python
    logs; the client sees only ``exc.client_safe_message`` (a short,
    pre-defined sanitized string keyed by status code).

    This is the single point of egress for provider error → HTTP. When
    Phase 3 wires the real SSI HTTP client, any upstream stack trace,
    HTTP-auth payload, or account-not-found message stays out of the
    response body.
    """
    logger.warning(
        "trading.provider_error status=%s exc_type=%s",
        exc.status_code,
        type(exc).__name__,
    )
    return HTTPException(status_code=exc.status_code, detail=exc.client_safe_message)


# ── Account registration ───────────────────────────────────────────────────


@router.get("", response_model=list[TradingAccount])
async def list_accounts(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> list[TradingAccount]:
    """All trading accounts the user has registered for read-only sync."""
    rows = await db.select(
        "trading_accounts", where={"user_id": user.user_id}, user_jwt=user.raw_token
    )
    return [TradingAccount(**r) for r in rows]


@router.post("/accounts", response_model=TradingAccount, status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: TradingAccountCreate,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> TradingAccount:
    """Register a broker account for READ-ONLY sync.

    The full account number is never persisted — only the last-4 masked
    form. Credentials remain server-side env vars; this endpoint never
    accepts them.
    """
    masked = _mask_account_number(payload.account_number)
    row = await db.insert(
        "trading_accounts",
        {
            "user_id": user.user_id,
            "broker": payload.broker,
            "account_number_masked": masked,
            "account_alias": payload.account_alias,
            "read_only_enabled": True,
            "trading_enabled": False,
        },
        user_jwt=user.raw_token,
    )
    await _audit_event(
        db, user, "trading.account_registered", request,
        {"account_id": row.get("id"), "broker": payload.broker},
    )
    return TradingAccount(**row)


# ── Read-only views ────────────────────────────────────────────────────────


@router.get("/cash", response_model=CashBalance)
async def get_cash(
    account_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    provider: TradingProvider = Depends(get_trading_provider),
) -> CashBalance:
    await _resolve_user_account(db, user, account_id)
    try:
        return await provider.get_cash_balance(account_id)
    except TradingProviderError as exc:
        raise _trading_error_to_http(exc)


@router.get("/positions", response_model=list[StockPosition])
async def get_positions(
    account_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    provider: TradingProvider = Depends(get_trading_provider),
) -> list[StockPosition]:
    await _resolve_user_account(db, user, account_id)
    try:
        return await provider.get_stock_positions(account_id)
    except TradingProviderError as exc:
        raise _trading_error_to_http(exc)


@router.get("/max-buy-qty", response_model=MaxBuyQuantity)
async def max_buy_qty(
    account_id: str,
    symbol: str,
    price: float,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    provider: TradingProvider = Depends(get_trading_provider),
) -> MaxBuyQuantity:
    if price <= 0:
        raise HTTPException(status_code=400, detail="price must be positive")
    await _resolve_user_account(db, user, account_id)
    try:
        return await provider.get_max_buy_qty(account_id, symbol, price)
    except TradingProviderError as exc:
        raise _trading_error_to_http(exc)


@router.get("/max-sell-qty", response_model=MaxSellQuantity)
async def max_sell_qty(
    account_id: str,
    symbol: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    provider: TradingProvider = Depends(get_trading_provider),
) -> MaxSellQuantity:
    await _resolve_user_account(db, user, account_id)
    try:
        return await provider.get_max_sell_qty(account_id, symbol)
    except TradingProviderError as exc:
        raise _trading_error_to_http(exc)


@router.get("/order-book", response_model=list[OrderBookEntry])
async def order_book(
    account_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    provider: TradingProvider = Depends(get_trading_provider),
) -> list[OrderBookEntry]:
    await _resolve_user_account(db, user, account_id)
    try:
        return await provider.get_order_book(account_id)
    except TradingProviderError as exc:
        raise _trading_error_to_http(exc)


@router.get("/order-history", response_model=list[OrderHistoryEntry])
async def order_history(
    account_id: str,
    start_date: date,
    end_date: date,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    provider: TradingProvider = Depends(get_trading_provider),
) -> list[OrderHistoryEntry]:
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")
    await _resolve_user_account(db, user, account_id)
    try:
        return await provider.get_order_history(account_id, start_date, end_date)
    except TradingProviderError as exc:
        raise _trading_error_to_http(exc)


# ── Order preview ──────────────────────────────────────────────────────────


async def _fetch_preview_context(
    *,
    market: MarketDataProvider,
    trading: TradingProvider,
    account_id: str,
    symbol: str,
) -> tuple[Any, Any, Any, Any]:
    """Best-effort: fetch quote, security, cash, position. Each failure is
    swallowed and turned into a warning by the calculator — preview never
    refuses to render.
    """
    quote = None
    security = None
    cash = None
    position = None
    try:
        quotes = await market.get_latest_quotes([symbol])
        quote = quotes[0] if quotes else None
    except ProviderError:
        pass
    try:
        security = await market.get_security_details(symbol)
    except ProviderError:
        pass
    try:
        cash = await trading.get_cash_balance(account_id)
    except TradingProviderError:
        pass
    try:
        positions = await trading.get_stock_positions(account_id)
        position = next(
            (p for p in positions if p.symbol.upper() == symbol.upper()), None
        )
    except TradingProviderError:
        pass
    return quote, security, cash, position


@router.post("/order-preview", response_model=OrderPreviewResult)
async def order_preview(
    payload: OrderPreviewRequest,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    market: MarketDataProvider = Depends(get_market_provider),
    trading: TradingProvider = Depends(get_trading_provider),
) -> OrderPreviewResult:
    """Compute a buy/sell preview. NEVER submits anything.

    Audited: every preview is logged + persisted (best-effort).
    """
    await _resolve_user_account(db, user, payload.account_id)
    quote, security, cash, position = await _fetch_preview_context(
        market=market,
        trading=trading,
        account_id=payload.account_id,
        symbol=payload.symbol,
    )
    result = calculate_preview(
        PreviewInputs(
            request=payload,
            quote=quote,
            security=security,
            cash=cash,
            position=position,
            avg_value_20d=None,  # Phase 2.5: liquidity left optional
        )
    )

    # Persist the preview as an audit row (best-effort).
    try:
        await db.insert(
            "order_previews",
            {
                "user_id": user.user_id,
                "account_id": payload.account_id,
                "symbol": result.symbol,
                "side": result.side,
                "order_type": result.order_type,
                "quantity": result.quantity,
                "limit_price": result.limit_price,
                "estimated_value": result.estimated_value,
                "estimated_fees": result.estimated_fees,
                "estimated_tax": result.estimated_tax,
                "estimated_vat": result.estimated_vat,
                "estimated_slippage": result.estimated_slippage,
                "total_cash_required": result.total_cash_required,
                "net_sell_proceeds": result.net_sell_proceeds,
                "validation_status": result.validation_status,
                "warnings": result.warnings,
                "rejection_reasons": result.rejection_reasons,
            },
            user_jwt=user.raw_token,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "trading.preview_persist_failed err=%s", type(exc).__name__
        )

    await _audit_event(
        db, user, "trading.order_previewed", request,
        {
            "account_id": payload.account_id,
            "symbol": result.symbol,
            "side": result.side,
            "quantity": result.quantity,
            "validation_status": result.validation_status,
        },
    )
    return result


# ── Status (read-only observability) ───────────────────────────────────────


@router.get("/status")
async def trading_status(
    user: AuthContext = Depends(get_current_user),
    provider: TradingProvider = Depends(get_trading_provider),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Trading provider snapshot — for the data-quality dashboard."""
    snapshot = await provider.status()
    return {
        **snapshot.model_dump(),
        "ssi_trading_use_mock": settings.ssi_trading_use_mock,
        "ssi_trading_read_only": settings.ssi_trading_read_only,
        "ssi_trading_order_placement_enabled": (
            settings.ssi_trading_order_placement_enabled
        ),
    }


# ── Forbidden submission endpoints (501 + audit) ───────────────────────────
# These EXIST so any AUTHENTICATED client (or future internal caller) that
# tries to submit an order gets a clean, documented 501 + a recorded
# audit event.
#
# NOTE on audit semantics: FastAPI resolves ``Depends(get_current_user)``
# BEFORE the route body runs. An unauthenticated request to these paths
# therefore returns ``401 Unauthorized`` and the audit log is NOT
# written — the user has no identity to attribute the row to. This is the
# correct trade-off for our threat model: an anonymous probe gets a 401
# (no signal returned to the prober) while an authenticated abuser is
# recorded in ``trading_audit_logs`` for later review. If we ever need
# anonymous-probe telemetry, add a request-level middleware that logs
# the path + IP separately from this user-scoped audit table.
#
# They do NOT call SSI. They do NOT accept payloads — adding a request
# body would prime someone to fill them in.


_FORBIDDEN_DETAIL = (
    "Live order submission is disabled in Phase 2.5. Use POST "
    "/trading/order-preview to compute a preview without contacting SSI."
)


async def _reject_submission(
    action: str, request: Request, user: AuthContext, db: SupabaseDB
) -> None:
    await _audit_event(
        db, user, action, request,
        {"reason": "PHASE_2_5_LIVE_TRADING_DISABLED"},
    )


@router.post("/new-order", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def new_order_forbidden(
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> dict[str, Any]:
    await _reject_submission(
        "trading.new_order_attempt_blocked", request, user, db
    )
    raise HTTPException(status_code=501, detail=_FORBIDDEN_DETAIL)


@router.post("/submit-order", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def submit_order_forbidden(
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> dict[str, Any]:
    await _reject_submission(
        "trading.submit_order_attempt_blocked", request, user, db
    )
    raise HTTPException(status_code=501, detail=_FORBIDDEN_DETAIL)


@router.post("/cancel-order", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def cancel_order_forbidden(
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> dict[str, Any]:
    await _reject_submission(
        "trading.cancel_order_attempt_blocked", request, user, db
    )
    raise HTTPException(status_code=501, detail=_FORBIDDEN_DETAIL)


# ── Phase 2.8 — Manual-confirm live trading intents ────────────────────────
#
# Every route in this section requires auth + ownership. The actual
# safety decisions live in ``services.live_orders``; this layer just
# persists state changes and writes audit rows. There is NO background
# submission path and NO auto-submit — every state transition requires
# an explicit HTTP request from the user.


async def _live_audit(
    db: SupabaseDB,
    user: AuthContext,
    action: LiveOrderAuditAction,
    request: Request | None,
    account_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Best-effort persistent audit log + structured Python log.

    Same pattern as the Phase 2.5/2.7 audit helpers — never raises so
    audit failure can't block the user's request, but always logs to
    stdout for operator-side observability.
    """
    logger.info(
        "live_order.audit user=%s action=%s account=%s",
        user.user_id, action, account_id,
    )
    try:
        await db.insert(
            "trading_audit_logs",
            {
                "user_id": user.user_id,
                "account_id": account_id,
                "action": action,
                "metadata": metadata or {},
                "ip_address": (
                    request.client.host if request and request.client else None
                ),
                "user_agent": (
                    request.headers.get("user-agent") if request else None
                ),
            },
            user_jwt=user.raw_token,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "live_order.audit_persist_failed action=%s err=%s",
            action, type(exc).__name__,
        )


async def _resolve_intent(
    db: SupabaseDB, user: AuthContext, intent_id: str
) -> dict[str, Any]:
    rows = await db.select(
        "live_order_intents",
        where={"id": intent_id, "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Live order intent not found.")
    return rows[0]


async def _transition_or_404(
    db: SupabaseDB,
    user: AuthContext,
    intent_id: str,
    *,
    current: LiveOrderIntentStatus,
    target: LiveOrderIntentStatus,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a state transition under the matrix. Raises 409 if the
    transition is illegal — mirrors what the DB-side trigger would do.

    Phase 2.8 review fix (HIGH TOCTOU):
    The WHERE clause now includes ``status=current`` so a concurrent
    cancel/transition can't race past us. If the row has already moved
    on, the UPDATE returns zero rows and we raise 409. Combined with
    the DB trigger, this gives us two independent guards against the
    race: the trigger catches an illegal transition direction; this
    check catches concurrent changes in the user's own session.
    """
    if not is_legal_transition(current, target):
        raise HTTPException(
            status_code=409,
            detail=f"Illegal transition {current} → {target}",
        )
    patch = {"status": target, "updated_at": datetime.now(timezone.utc).isoformat()}
    if extra:
        patch.update(extra)
    updated = await db.update(
        "live_order_intents", patch,
        where={"id": intent_id, "user_id": user.user_id, "status": current},
        user_jwt=user.raw_token,
    )
    if not updated:
        raise HTTPException(
            status_code=409,
            detail=(
                f"State changed concurrently — expected {current}, "
                "another request raced ahead."
            ),
        )
    return updated[0]


def _gate_status_dict(settings: Settings) -> dict[str, Any]:
    return compute_gate_status(settings).to_dict()


@router.post(
    "/live-order-intents",
    response_model=LiveOrderIntent,
    status_code=status.HTTP_201_CREATED,
)
async def create_live_order_intent(
    payload: LiveOrderIntentCreate,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> LiveOrderIntent:
    await _resolve_user_account(db, user, payload.account_id)
    row = await db.insert(
        "live_order_intents",
        {
            "user_id": user.user_id,
            "account_id": payload.account_id,
            "source_type": payload.source_type,
            "source_id": payload.source_id,
            "symbol": payload.symbol.upper(),
            "side": payload.side,
            "order_type": payload.order_type,
            "quantity": payload.quantity,
            "limit_price": payload.limit_price,
            "status": "DRAFT",
        },
        user_jwt=user.raw_token,
    )
    await _live_audit(
        db, user, "LIVE_ORDER_INTENT_CREATED", request,
        account_id=payload.account_id,
        metadata={"intent_id": row["id"], "symbol": payload.symbol},
    )
    return LiveOrderIntent(**row)


@router.get("/live-order-intents", response_model=list[LiveOrderIntent])
async def list_live_order_intents(
    account_id: str | None = None,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> list[LiveOrderIntent]:
    where: dict[str, Any] = {"user_id": user.user_id}
    if account_id:
        where["account_id"] = account_id
    rows = await db.select(
        "live_order_intents", where=where, user_jwt=user.raw_token,
    )
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return [LiveOrderIntent(**r) for r in rows]


@router.get("/live-order-intents/{intent_id}", response_model=LiveOrderIntent)
async def get_live_order_intent(
    intent_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> LiveOrderIntent:
    row = await _resolve_intent(db, user, intent_id)
    return LiveOrderIntent(**row)


async def _build_preview_context(
    *,
    market: MarketDataProvider,
    trading: TradingProvider,
    intent: dict[str, Any],
) -> tuple[Any, Any, Any, Any]:
    """Same defensive pattern as Phase 2.5 ``_fetch_preview_context`` —
    each provider call's failure is swallowed and surfaces as a warning
    or DATA_UNAVAILABLE in the calculator. Never raises."""
    quote = None
    security = None
    cash = None
    position = None
    try:
        quotes = await market.get_latest_quotes([intent["symbol"]])
        quote = quotes[0] if quotes else None
    except ProviderError:
        pass
    try:
        security = await market.get_security_details(intent["symbol"])
    except ProviderError:
        pass
    try:
        cash = await trading.get_cash_balance(intent["account_id"])
    except TradingProviderError:
        pass
    try:
        positions = await trading.get_stock_positions(intent["account_id"])
        position = next(
            (p for p in positions if p.symbol.upper() == intent["symbol"].upper()),
            None,
        )
    except TradingProviderError:
        pass
    return quote, security, cash, position


@router.post(
    "/live-order-intents/{intent_id}/preview",
    response_model=LiveOrderIntentResult,
)
async def preview_live_order_intent(
    intent_id: str,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    market: MarketDataProvider = Depends(get_market_provider),
    trading: TradingProvider = Depends(get_trading_provider),
    settings: Settings = Depends(get_settings),
) -> LiveOrderIntentResult:
    intent = await _resolve_intent(db, user, intent_id)
    if intent["status"] not in ("DRAFT", "PREVIEWED"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot preview from state {intent['status']}",
        )

    quote, security, cash, position = await _build_preview_context(
        market=market, trading=trading, intent=intent,
    )
    req = OrderPreviewRequest(
        account_id=intent["account_id"],
        symbol=intent["symbol"],
        side=intent["side"],
        quantity=int(intent["quantity"]),
        limit_price=float(
            intent.get("limit_price")
            or (quote.price if quote and quote.price else 0)
        ),
        order_type=intent.get("order_type") or "LIMIT",
    )
    preview = calculate_preview(
        PreviewInputs(
            request=req, quote=quote, security=security,
            cash=cash, position=position, avg_value_20d=None,
        )
    )

    updated = await _transition_or_404(
        db, user, intent_id, current=intent["status"], target="PREVIEWED",
        extra={
            "validation_snapshot": preview.model_dump(),
            "warnings": preview.warnings,
            "rejection_reasons": preview.rejection_reasons,
        },
    )
    await _live_audit(
        db, user, "LIVE_ORDER_PREVIEWED", request,
        account_id=intent["account_id"],
        metadata={
            "intent_id": intent_id,
            "validation_status": preview.validation_status,
        },
    )
    return LiveOrderIntentResult(
        intent=LiveOrderIntent(**updated),
        validation_status=preview.validation_status,
        rejection_reasons=preview.rejection_reasons,
        warnings=preview.warnings,
        is_live_submission_performed=False,
        is_dry_run=settings.trading_order_placement_dry_run,
        gate_status=_gate_status_dict(settings),
    )


@router.post(
    "/live-order-intents/{intent_id}/request-confirmation",
    response_model=LiveOrderIntentResult,
)
async def request_confirmation(
    intent_id: str,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LiveOrderIntentResult:
    intent = await _resolve_intent(db, user, intent_id)
    if intent["status"] != "PREVIEWED":
        raise HTTPException(
            status_code=409,
            detail="Confirmation can be requested only from PREVIEWED.",
        )
    # If the preview itself already had REJECTED reasons we refuse to
    # advance — the user must re-preview after fixing inputs.
    rej = intent.get("rejection_reasons") or []
    if rej:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot request confirmation while preview has rejections: {rej}",
        )
    updated = await _transition_or_404(
        db, user, intent_id,
        current=intent["status"], target="CONFIRM_REQUIRED",
    )
    await _live_audit(
        db, user, "LIVE_ORDER_CONFIRMATION_REQUESTED", request,
        account_id=intent["account_id"],
        metadata={"intent_id": intent_id},
    )
    return LiveOrderIntentResult(
        intent=LiveOrderIntent(**updated),
        validation_status="VALID",
        is_live_submission_performed=False,
        is_dry_run=settings.trading_order_placement_dry_run,
        gate_status=_gate_status_dict(settings),
    )


@router.post(
    "/live-order-intents/{intent_id}/confirm",
    response_model=LiveOrderIntentResult,
)
async def confirm_live_order_intent(
    intent_id: str,
    payload: ConfirmRequest,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LiveOrderIntentResult:
    intent = await _resolve_intent(db, user, intent_id)
    if intent["status"] != "CONFIRM_REQUIRED":
        raise HTTPException(
            status_code=409,
            detail=f"Confirm requires CONFIRM_REQUIRED state; got {intent['status']}",
        )
    if not payload.risk_acknowledged:
        # Phase 2.8 review fix: a confirm-step rejection is NOT a submit
        # rejection. The dedicated CONFIRM_REJECTED action lets auditors
        # filter cleanly. The intent stays in CONFIRM_REQUIRED so the
        # user can retry (still inside the reauth window).
        await _live_audit(
            db, user, "LIVE_ORDER_CONFIRM_REJECTED", request,
            account_id=intent["account_id"],
            metadata={
                "intent_id": intent_id,
                "reason": "RISK_ACK_REQUIRED",
            },
        )
        raise HTTPException(
            status_code=400,
            detail="risk_acknowledged must be true to confirm.",
        )
    # Verify re-auth freshness here too so a stale JWT can't sneak
    # through with risk_acknowledged=true. Phase 2.8 review fix: use
    # the stamped ``last_reauth_at`` (via auto_trade_settings) too, so
    # the confirm-time and submit-time policies are CONSISTENT — a user
    # who refreshed their stamp in the Phase 2.6 re-auth flow doesn't
    # face a different policy here than at submit time.
    last_reauth = await _last_reauth_at_for(db, user, intent["account_id"])
    if settings.trading_require_reauth and not reauth_is_fresh(
        settings=settings, jwt_claims=user.claims,
        last_reauth_at=last_reauth,
        max_age_seconds=settings.trading_reauth_max_age_seconds,
    ):
        await _live_audit(
            db, user, "LIVE_ORDER_REAUTH_FAILED", request,
            account_id=intent["account_id"],
            metadata={"intent_id": intent_id},
        )
        raise HTTPException(
            status_code=401,
            detail="Recent re-authentication required.",
        )
    now = datetime.now(timezone.utc).isoformat()
    updated = await _transition_or_404(
        db, user, intent_id,
        current=intent["status"], target="CONFIRMED",
        extra={"confirmed_at": now},
    )
    await _live_audit(
        db, user, "LIVE_ORDER_CONFIRMED", request,
        account_id=intent["account_id"],
        metadata={"intent_id": intent_id},
    )
    return LiveOrderIntentResult(
        intent=LiveOrderIntent(**updated),
        validation_status="VALID",
        is_live_submission_performed=False,
        is_dry_run=settings.trading_order_placement_dry_run,
        gate_status=_gate_status_dict(settings),
    )


@router.post(
    "/live-order-intents/{intent_id}/cancel",
    response_model=LiveOrderIntentResult,
)
async def cancel_live_order_intent(
    intent_id: str,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LiveOrderIntentResult:
    intent = await _resolve_intent(db, user, intent_id)
    if intent["status"] in ("SUBMITTED", "REJECTED", "CANCELLED", "FAILED"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel from terminal state {intent['status']}",
        )
    updated = await _transition_or_404(
        db, user, intent_id,
        current=intent["status"], target="CANCELLED",
    )
    await _live_audit(
        db, user, "LIVE_ORDER_CANCELLED", request,
        account_id=intent["account_id"],
        metadata={"intent_id": intent_id, "previous_state": intent["status"]},
    )
    return LiveOrderIntentResult(
        intent=LiveOrderIntent(**updated),
        validation_status="VALID",
        is_live_submission_performed=False,
        is_dry_run=settings.trading_order_placement_dry_run,
        gate_status=_gate_status_dict(settings),
    )


async def _last_reauth_at_for(
    db: SupabaseDB, user: AuthContext, account_id: str
) -> datetime | None:
    """Look up the Phase 2.6 ``auto_trade_settings.last_reauth_at`` if
    the user has stamped one for this account. Best-effort — missing
    row is acceptable (the JWT iat path still works)."""
    rows = await db.select(
        "auto_trade_settings",
        where={"user_id": user.user_id, "account_id": account_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        return None
    val = rows[0].get("last_reauth_at")
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(val, datetime):
        return val
    return None


async def _orders_today_for(
    db: SupabaseDB, user: AuthContext, account_id: str
) -> int:
    """Count this user+account's submission rows dated today.

    Phase 2.8 review fix (HIGH): previously, an unparseable timestamp
    was silently dropped (``except ValueError: pass``), which would
    let a poisoned row bypass the daily-order ceiling. The fail-closed
    policy now counts unparseable rows toward the limit so a
    malformed timestamp tightens the gate rather than loosening it.
    """
    rows = await db.select(
        "live_order_submissions",
        where={"user_id": user.user_id, "account_id": account_id},
        user_jwt=user.raw_token,
    )
    today = datetime.now(timezone.utc).date()
    count = 0
    for r in rows:
        ts = r.get("submitted_at") or r.get("created_at")
        if isinstance(ts, str):
            try:
                d = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
                if d == today:
                    count += 1
            except ValueError:
                # Fail-closed: count it. An attacker who poisons
                # ``submitted_at`` to an unparseable string cannot bypass
                # the daily ceiling.
                count += 1
        elif isinstance(ts, datetime):
            if ts.date() == today:
                count += 1
        else:
            # Missing or non-string non-datetime — fail-closed.
            count += 1
    return count


async def _auto_trade_mode_for(
    db: SupabaseDB, user: AuthContext, account_id: str
) -> str:
    rows = await db.select(
        "auto_trade_settings",
        where={"user_id": user.user_id, "account_id": account_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        return "OFF"
    return str(rows[0].get("mode") or "OFF")


@router.post(
    "/live-order-intents/{intent_id}/submit",
    response_model=LiveOrderIntentResult,
)
async def submit_live_order_intent(
    intent_id: str,
    request: Request,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    market: MarketDataProvider = Depends(get_market_provider),
    trading: TradingProvider = Depends(get_trading_provider),
    settings: Settings = Depends(get_settings),
) -> LiveOrderIntentResult:
    """Final step — runs the submit-time gauntlet, then either does a
    dry-run synthetic submission OR calls the SSI provider's
    submit_order (which itself currently 501s in Phase 2.8 — see
    providers/trading/ssi_trading.py).
    """
    intent = await _resolve_intent(db, user, intent_id)
    gate = compute_gate_status(settings)
    await _live_audit(
        db, user, "LIVE_ORDER_SUBMIT_ATTEMPTED", request,
        account_id=intent["account_id"],
        metadata={"intent_id": intent_id, "gate": gate.to_dict()},
    )

    # Phase 2.8 review fix (CRITICAL): hard 409 if the intent is not in
    # CONFIRMED. Previously the orchestrator rejected with NOT_CONFIRMED
    # but the route still wrote a submission row attributed to a
    # never-confirmed intent — polluting the daily-order counter and
    # giving an attacker a cheap way to lock out the limit.
    if intent["status"] != "CONFIRMED":
        await _live_audit(
            db, user, "LIVE_ORDER_SUBMIT_REJECTED", request,
            account_id=intent["account_id"],
            metadata={
                "intent_id": intent_id,
                "reason": "NOT_CONFIRMED",
                "current_status": intent["status"],
            },
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Submit requires CONFIRMED state; got {intent['status']}. "
                "Walk the preview → request-confirmation → confirm flow first."
            ),
        )

    # Assemble re-validation context.
    quote, security, cash, position = await _build_preview_context(
        market=market, trading=trading, intent=intent,
    )
    last_reauth = await _last_reauth_at_for(
        db, user, intent["account_id"],
    )
    auto_mode = await _auto_trade_mode_for(
        db, user, intent["account_id"],
    )
    auto_settings_rows = await db.select(
        "auto_trade_settings",
        where={"user_id": user.user_id, "account_id": intent["account_id"]},
        user_jwt=user.raw_token,
    )
    orders_today = await _orders_today_for(
        db, user, intent["account_id"],
    )
    # Phase 2.8 review fix: read the per-account live-trading flag from
    # ``trading_accounts``. This is the defence-in-depth check that the
    # orchestrator runs alongside the 5-flag global env gate.
    trading_account_rows = await db.select(
        "trading_accounts",
        where={"id": intent["account_id"], "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    trading_account_enabled = bool(
        trading_account_rows
        and trading_account_rows[0].get("trading_enabled")
    )
    ctx = SubmitContext(
        intent_row=intent,
        settings=settings,
        jwt_claims=user.claims,
        last_reauth_at=last_reauth,
        quote=quote, security=security, cash=cash, position=position,
        avg_value_20d=None,
        auto_trade_mode=auto_mode,
        auto_trade_settings_row=auto_settings_rows[0] if auto_settings_rows else None,
        orders_today=orders_today,
        trading_account_enabled=trading_account_enabled,
    )
    status_outcome, rejection_reasons, warnings, snapshot = revalidate_for_submit(ctx)

    if status_outcome == "REJECTED":
        await _transition_or_404(
            db, user, intent_id,
            current=intent["status"], target="REJECTED",
            extra={
                "validation_snapshot": snapshot,
                "rejection_reasons": rejection_reasons,
                "warnings": warnings,
            },
        )
        await db.insert(
            "live_order_submissions",
            {
                "user_id": user.user_id,
                "account_id": intent["account_id"],
                "live_order_intent_id": intent_id,
                "broker": "SSI",
                "request_payload_sanitized": sanitize_request_payload(intent),
                "response_payload_sanitized": {"rejection_reasons": rejection_reasons},
                "status": "REJECTED_BY_GATE",
            },
            user_jwt=user.raw_token,
        )
        await _live_audit(
            db, user, "LIVE_ORDER_SUBMIT_REJECTED", request,
            account_id=intent["account_id"],
            metadata={"intent_id": intent_id, "reasons": rejection_reasons},
        )
        return LiveOrderIntentResult(
            intent=LiveOrderIntent(**await _resolve_intent(db, user, intent_id)),
            validation_status="REJECTED",
            rejection_reasons=rejection_reasons,
            warnings=warnings,
            is_live_submission_performed=False,
            is_dry_run=settings.trading_order_placement_dry_run,
            gate_status=gate.to_dict(),
        )

    # ── Dispatch: dry-run vs live ──
    if not gate.all_open:
        # Any gate closed → dry-run, regardless of operator intent.
        response_payload = synthetic_broker_response(intent_row=intent, quote=quote)
        submission_status = "DRY_RUN_OK"
        is_live = False
    else:
        # Phase 2.8 review fix (CRITICAL): the per-account
        # ``trading_accounts.trading_enabled`` flag is the per-account
        # kill switch alongside the global 5-flag gate. Only block the
        # LIVE path — dry-run doesn't need it.
        if not trading_account_enabled:
            await _transition_or_404(
                db, user, intent_id,
                current=intent["status"], target="REJECTED",
                extra={
                    "rejection_reasons": ["ACCOUNT_NOT_LIVE_ENABLED"],
                    "validation_snapshot": snapshot,
                },
            )
            await db.insert(
                "live_order_submissions",
                {
                    "user_id": user.user_id,
                    "account_id": intent["account_id"],
                    "live_order_intent_id": intent_id,
                    "broker": "SSI",
                    "request_payload_sanitized": sanitize_request_payload(intent),
                    "response_payload_sanitized": {
                        "rejection_reasons": ["ACCOUNT_NOT_LIVE_ENABLED"],
                    },
                    "status": "REJECTED_BY_GATE",
                },
                user_jwt=user.raw_token,
            )
            await _live_audit(
                db, user, "LIVE_ORDER_SUBMIT_REJECTED", request,
                account_id=intent["account_id"],
                metadata={
                    "intent_id": intent_id,
                    "reasons": ["ACCOUNT_NOT_LIVE_ENABLED"],
                },
            )
            return LiveOrderIntentResult(
                intent=LiveOrderIntent(**await _resolve_intent(db, user, intent_id)),
                validation_status="REJECTED",
                rejection_reasons=["ACCOUNT_NOT_LIVE_ENABLED"],
                warnings=warnings,
                is_live_submission_performed=False,
                is_dry_run=False,
                gate_status=gate.to_dict(),
            )
        # All gates open → call the provider. Phase 2.8 implementations
        # raise 501 NOT_IMPLEMENTED by design; Phase 3 will wire real
        # SSI HTTP. We catch the 501 and surface as BROKER_ERROR (the
        # intent goes to FAILED, not SUBMITTED) so operators can see
        # the wiring gap.
        try:
            response_payload = await trading.submit_order(
                account_id=intent["account_id"],
                symbol=intent["symbol"],
                side=intent["side"],
                order_type=intent.get("order_type") or "LIMIT",
                quantity=int(intent["quantity"]),
                limit_price=intent.get("limit_price"),
            )
            submission_status = "LIVE_OK"
            is_live = True
        except Exception as raw_exc:
            # Phase 2.8 review fix (CRITICAL): previously only
            # ``TradingProviderError`` was caught. Any other exception
            # (asyncio.TimeoutError, httpx.ConnectError, RuntimeError,
            # KeyError on a non-dict response, …) would bubble as a
            # 500 with the intent stuck in CONFIRMED — letting the
            # user retry the submit and potentially DOUBLE-SEND once
            # Phase 3 wires real SSI HTTP. Normalise non-Trading
            # errors to a TradingProviderError(502) so they go through
            # the same FAILED transition path below.
            if not isinstance(raw_exc, TradingProviderError):
                logger.exception(
                    "live_order.submit_unhandled_exception intent=%s err=%s",
                    intent_id, type(raw_exc).__name__,
                )
                exc = TradingProviderError(
                    f"Unhandled {type(raw_exc).__name__} during submit.",
                    status_code=502,
                )
            else:
                exc = raw_exc
            # Phase 2.8 always lands here today.
            await _transition_or_404(
                db, user, intent_id,
                current=intent["status"], target="FAILED",
                extra={
                    "rejection_reasons": [
                        f"BROKER_ERROR_{exc.status_code}"
                    ],
                    "validation_snapshot": snapshot,
                },
            )
            await db.insert(
                "live_order_submissions",
                {
                    "user_id": user.user_id,
                    "account_id": intent["account_id"],
                    "live_order_intent_id": intent_id,
                    "broker": "SSI",
                    "request_payload_sanitized": sanitize_request_payload(intent),
                    "response_payload_sanitized": {
                        "error_class": type(exc).__name__,
                        "status_code": exc.status_code,
                    },
                    "status": "BROKER_ERROR",
                },
                user_jwt=user.raw_token,
            )
            await _live_audit(
                db, user, "LIVE_ORDER_SUBMIT_BROKER_ERROR", request,
                account_id=intent["account_id"],
                metadata={
                    "intent_id": intent_id,
                    "status_code": exc.status_code,
                },
            )
            return LiveOrderIntentResult(
                intent=LiveOrderIntent(**await _resolve_intent(db, user, intent_id)),
                validation_status="REJECTED",
                rejection_reasons=[f"BROKER_ERROR_{exc.status_code}"],
                warnings=warnings,
                is_live_submission_performed=False,
                is_dry_run=False,
                gate_status=gate.to_dict(),
            )

    await _transition_or_404(
        db, user, intent_id,
        current=intent["status"], target="SUBMITTED",
        extra={
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "validation_snapshot": snapshot,
            "warnings": warnings,
        },
    )
    await db.insert(
        "live_order_submissions",
        {
            "user_id": user.user_id,
            "account_id": intent["account_id"],
            "live_order_intent_id": intent_id,
            "broker": "SSI",
            "broker_order_id": response_payload.get("broker_order_id"),
            "request_payload_sanitized": sanitize_request_payload(intent),
            "response_payload_sanitized": response_payload,
            "status": submission_status,
        },
        user_jwt=user.raw_token,
    )
    action: LiveOrderAuditAction = (
        "LIVE_ORDER_SUBMIT_LIVE_OK" if is_live
        else "LIVE_ORDER_SUBMIT_DRY_RUN_OK"
    )
    await _live_audit(
        db, user, action, request,
        account_id=intent["account_id"],
        metadata={"intent_id": intent_id, "status": submission_status},
    )
    return LiveOrderIntentResult(
        intent=LiveOrderIntent(**await _resolve_intent(db, user, intent_id)),
        validation_status="VALID" if not warnings else "WARN",
        warnings=warnings,
        is_live_submission_performed=is_live,
        is_dry_run=not is_live,
        gate_status=gate.to_dict(),
    )
