"""Alert routes — user-defined research notification rules.

All auth-required and RLS-scoped to the owner. Alerts are evaluated against the
latest cached quote on read; they NEVER place an order. Endpoints:

* ``GET    /alerts``        — list (with live evaluation).
* ``POST   /alerts``        — create.
* ``PATCH  /alerts/{id}``   — edit / enable / disable.
* ``DELETE /alerts/{id}``   — delete.

Watchlist-scoped reads live on the watchlist router (``GET
/watchlists/{id}/alerts``) and reuse the same evaluation service.
"""

from __future__ import annotations

import math
import re

from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.deps import get_cache, get_db
from core.security import AuthContext, get_current_user
from schemas.alerts import Alert, AlertCreate, AlertListResponse, AlertUpdate
from services import alerts as alert_eval
from services.cache import Cache
from services.supabase_db import SupabaseDB

router = APIRouter()

_SYMBOL_RE = re.compile(r"^[A-Z0-9_]{1,20}$")


def _normalize_symbol(symbol: str) -> str:
    sym = symbol.strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid symbol: {symbol!r}"
        )
    return sym


def _validate_threshold(value: float) -> None:
    if not math.isfinite(value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Threshold must be finite."
        )


@router.get("", response_model=AlertListResponse, summary="List the user's alerts (evaluated)")
async def list_alerts(
    active_only: bool = Query(default=False),
    symbol: str | None = Query(default=None),
    user: AuthContext = Depends(get_current_user),
    cache: Cache = Depends(get_cache),
    db: SupabaseDB = Depends(get_db),
) -> AlertListResponse:
    rows = await db.select("alerts", where={"user_id": user.user_id}, user_jwt=user.raw_token)
    if active_only:
        rows = [r for r in rows if r.get("is_active", True)]
    if symbol:
        want = symbol.strip().upper()
        rows = [r for r in rows if str(r.get("symbol", "")).upper() == want]
    return await alert_eval.build_alert_list(rows, cache=cache)


@router.post(
    "",
    response_model=Alert,
    status_code=status.HTTP_201_CREATED,
    summary="Create an alert",
)
async def create_alert(
    payload: AlertCreate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> Alert:
    _validate_threshold(payload.threshold)
    sym = _normalize_symbol(payload.symbol)
    try:
        row = await db.insert(
            "alerts",
            {
                "user_id": user.user_id,
                "symbol": sym,
                "exchange": payload.exchange,
                "condition": payload.condition,
                "threshold": payload.threshold,
                "note": payload.note,
                "is_active": True,
            },
            user_jwt=user.raw_token,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return Alert.model_validate(row)


@router.patch(
    "/{alert_id}",
    response_model=Alert,
    summary="Edit / enable / disable an alert",
)
async def update_alert(
    alert_id: str,
    payload: AlertUpdate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> Alert:
    patch = payload.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty update payload."
        )
    if "threshold" in patch:
        _validate_threshold(patch["threshold"])
    rows = await db.update(
        "alerts",
        patch,
        where={"id": alert_id, "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found."
        )
    return Alert.model_validate(rows[0])


@router.delete(
    "/{alert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an alert",
)
async def delete_alert(
    alert_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> None:
    deleted = await db.delete(
        "alerts",
        where={"id": alert_id, "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found."
        )
