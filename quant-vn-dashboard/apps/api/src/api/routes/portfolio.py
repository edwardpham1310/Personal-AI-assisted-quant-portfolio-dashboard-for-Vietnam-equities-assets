"""Manual portfolio routes.

MVP scope: users record their own accounts + positions. No live broker sync
yet, and absolutely no order placement.

Two route families live here:
* ``/portfolio/manual/*`` — the original CRUD surface (preserved as-is).
* ``/portfolio/{summary,positions,sync/ssi}`` — the Phase 1 valuation surface
  that uses the user's *default* account implicitly.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from core.deps import get_cache, get_db
from core.security import AuthContext, get_current_user
from schemas.portfolio import (
    EnrichedPosition,
    ManualAccount,
    ManualAccountCreate,
    ManualAccountWithPositions,
    ManualPortfolioSnapshot,
    ManualPosition,
    ManualPositionCreate,
    ManualPositionUpdate,
    PortfolioSummary,
    PositionCreate,
    PositionUpdate,
)
from services import market_cache, portfolio_valuation
from services.cache import Cache
from services.supabase_db import SupabaseDB

router = APIRouter()


DEFAULT_ACCOUNT_NAME = "Default"


async def _list_user_accounts(
    db: SupabaseDB, user: AuthContext
) -> list[dict[str, Any]]:
    return await db.select(
        "manual_portfolio_accounts",
        where={"user_id": user.user_id},
        user_jwt=user.raw_token,
    )


async def _get_default_account(
    db: SupabaseDB,
    user: AuthContext,
    *,
    create_if_missing: bool = False,
) -> dict[str, Any] | None:
    """Return the user's default (oldest) account, optionally auto-creating."""
    accounts = await _list_user_accounts(db, user)
    if accounts:
        # ``created_at`` may be missing in old fakes — fall back to id ordering.
        return sorted(accounts, key=lambda a: a.get("created_at") or a.get("id", ""))[0]
    if not create_if_missing:
        return None
    row = await db.insert(
        "manual_portfolio_accounts",
        {
            "user_id": user.user_id,
            "name": DEFAULT_ACCOUNT_NAME,
            "broker": "SSI",
            "currency": "VND",
        },
        user_jwt=user.raw_token,
    )
    return row


@router.get(
    "/manual",
    response_model=ManualPortfolioSnapshot,
    summary="List the current user's manual portfolio (accounts + positions)",
)
async def list_manual_portfolio(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> ManualPortfolioSnapshot:
    accounts = await db.select(
        "manual_portfolio_accounts",
        where={"user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not accounts:
        return ManualPortfolioSnapshot(accounts=[])
    positions = await db.select("manual_positions", user_jwt=user.raw_token)
    by_account: dict[str, list[ManualPosition]] = {}
    for row in positions:
        by_account.setdefault(row["account_id"], []).append(
            ManualPosition.model_validate(row)
        )
    return ManualPortfolioSnapshot(
        accounts=[
            ManualAccountWithPositions(**acc, positions=by_account.get(acc["id"], []))
            for acc in accounts
        ]
    )


@router.post(
    "/manual/accounts",
    response_model=ManualAccount,
    status_code=status.HTTP_201_CREATED,
    summary="Create a manual portfolio account",
)
async def create_account(
    payload: ManualAccountCreate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> ManualAccount:
    row = await db.insert(
        "manual_portfolio_accounts",
        {
            "user_id": user.user_id,
            "name": payload.name,
            "broker": payload.broker,
            "currency": payload.currency,
        },
        user_jwt=user.raw_token,
    )
    return ManualAccount.model_validate(row)


@router.post(
    "/manual/positions",
    response_model=ManualPosition,
    status_code=status.HTTP_201_CREATED,
    summary="Record a manual position in an account you own",
)
async def create_position(
    payload: ManualPositionCreate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> ManualPosition:
    parent = await db.select(
        "manual_portfolio_accounts",
        where={"id": payload.account_id},
        user_jwt=user.raw_token,
    )
    if not parent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found."
        )
    try:
        row = await db.insert(
            "manual_positions",
            {
                "account_id": payload.account_id,
                "symbol": payload.symbol.upper(),
                "exchange": payload.exchange,
                "quantity": payload.quantity,
                "avg_cost": payload.avg_cost,
                "strategy_tag": payload.strategy_tag,
                "note": payload.note,
            },
            user_jwt=user.raw_token,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return ManualPosition.model_validate(row)


@router.put(
    "/manual/positions/{position_id}",
    response_model=ManualPosition,
    summary="Update a manual position",
)
async def update_position(
    position_id: str,
    payload: ManualPositionUpdate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> ManualPosition:
    patch = payload.model_dump(exclude_none=True)
    if "symbol" in patch:
        patch["symbol"] = patch["symbol"].upper()
    if not patch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty update payload."
        )
    rows = await db.update(
        "manual_positions",
        patch,
        where={"id": position_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Position not found."
        )
    return ManualPosition.model_validate(rows[0])


@router.delete(
    "/manual/positions/{position_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a manual position",
)
async def delete_position(
    position_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> None:
    deleted = await db.delete(
        "manual_positions",
        where={"id": position_id},
        user_jwt=user.raw_token,
    )
    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Position not found."
        )


# ─── Phase 1 valuation surface ────────────────────────────────────────────────


async def _load_positions_for_user(
    db: SupabaseDB,
    user: AuthContext,
    account_id: str,
) -> list[dict[str, Any]]:
    return await db.select(
        "manual_positions",
        where={"account_id": account_id},
        user_jwt=user.raw_token,
    )


@router.get(
    "/summary",
    response_model=PortfolioSummary,
    summary="Portfolio valuation summary (research only — not financial advice)",
)
async def get_portfolio_summary(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    cache: Cache = Depends(get_cache),
) -> PortfolioSummary:
    account = await _get_default_account(db, user)
    if account is None:
        return PortfolioSummary()
    positions = await _load_positions_for_user(db, user, account["id"])
    if not positions:
        return PortfolioSummary()
    symbols = [str(p["symbol"]).upper() for p in positions]
    quotes = await market_cache.get_quotes(cache, symbols)
    summary, _ = portfolio_valuation.compute_summary(positions, quotes)
    return summary


@router.get(
    "/positions",
    response_model=list[EnrichedPosition],
    summary="Enriched positions for the default account",
)
async def list_enriched_positions(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
    cache: Cache = Depends(get_cache),
) -> list[EnrichedPosition]:
    account = await _get_default_account(db, user)
    if account is None:
        return []
    positions = await _load_positions_for_user(db, user, account["id"])
    if not positions:
        return []
    symbols = [str(p["symbol"]).upper() for p in positions]
    quotes = await market_cache.get_quotes(cache, symbols)
    _, enriched = portfolio_valuation.compute_summary(positions, quotes)
    return enriched


@router.post(
    "/positions",
    response_model=ManualPosition,
    status_code=status.HTTP_201_CREATED,
    summary="Add a position to the default account (auto-creates one on first use)",
)
async def create_position_default(
    payload: PositionCreate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> ManualPosition:
    account = await _get_default_account(db, user, create_if_missing=True)
    if account is None:
        # Should never happen — create_if_missing=True guarantees a row.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not resolve default account.",
        )
    try:
        row = await db.insert(
            "manual_positions",
            {
                "account_id": account["id"],
                "symbol": payload.symbol.upper(),
                "exchange": payload.exchange,
                "quantity": payload.quantity,
                "avg_cost": payload.avg_cost,
                "strategy_tag": payload.strategy_tag,
                "note": payload.note,
            },
            user_jwt=user.raw_token,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return ManualPosition.model_validate(row)


@router.put(
    "/positions/{position_id}",
    response_model=ManualPosition,
    summary="Update a position on the default account",
)
async def update_position_default(
    position_id: str,
    payload: PositionUpdate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> ManualPosition:
    patch = payload.model_dump(exclude_none=True)
    if "symbol" in patch:
        patch["symbol"] = patch["symbol"].upper()
    if not patch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty update payload."
        )
    rows = await db.update(
        "manual_positions",
        patch,
        where={"id": position_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Position not found."
        )
    return ManualPosition.model_validate(rows[0])


@router.delete(
    "/positions/{position_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a position on the default account",
)
async def delete_position_default(
    position_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> None:
    deleted = await db.delete(
        "manual_positions",
        where={"id": position_id},
        user_jwt=user.raw_token,
    )
    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Position not found."
        )


@router.post(
    "/sync/ssi",
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    summary="SSI sync placeholder — Phase 2",
)
async def sync_ssi_placeholder(
    _user: AuthContext = Depends(get_current_user),
) -> JSONResponse:
    # Body shape is fixed per PM brief — do not nest under "detail".
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={"detail": "SSI sync coming in Phase 2", "status": "placeholder"},
    )
