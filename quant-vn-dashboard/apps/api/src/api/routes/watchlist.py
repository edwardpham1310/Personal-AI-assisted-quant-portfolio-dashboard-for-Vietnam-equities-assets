"""Watchlist routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from core.deps import get_cache, get_db
from core.security import AuthContext, get_current_user
from schemas.alerts import AlertListResponse
from schemas.watchlist import (
    Watchlist,
    WatchlistCreate,
    WatchlistItem,
    WatchlistItemCreate,
    WatchlistUpdate,
    WatchlistWithItems,
)
from services import alerts as alert_eval
from services.cache import Cache
from services.supabase_db import SupabaseDB

router = APIRouter()


@router.get(
    "",
    response_model=list[WatchlistWithItems],
    summary="List the current user's watchlists (with items)",
)
async def list_watchlists(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> list[WatchlistWithItems]:
    lists = await db.select(
        "watchlists", where={"user_id": user.user_id}, user_jwt=user.raw_token
    )
    if not lists:
        return []
    # Items belonging to the user (RLS filters) — group by watchlist.
    items = await db.select("watchlist_items", user_jwt=user.raw_token)
    grouped: dict[str, list[WatchlistItem]] = {}
    for row in items:
        grouped.setdefault(row["watchlist_id"], []).append(WatchlistItem.model_validate(row))
    return [
        WatchlistWithItems(**wl, items=grouped.get(wl["id"], []))
        for wl in lists
    ]


@router.post(
    "",
    response_model=Watchlist,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new watchlist",
)
async def create_watchlist(
    payload: WatchlistCreate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> Watchlist:
    # user_id always comes from the verified JWT — never from the request body.
    row = await db.insert(
        "watchlists",
        {
            "user_id": user.user_id,
            "name": payload.name,
            "description": payload.description,
        },
        user_jwt=user.raw_token,
    )
    return Watchlist.model_validate(row)


@router.get(
    "/{watchlist_id}",
    response_model=WatchlistWithItems,
    summary="Get one watchlist (with items)",
)
async def get_watchlist(
    watchlist_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> WatchlistWithItems:
    rows = await db.select(
        "watchlists",
        where={"id": watchlist_id, "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found."
        )
    items = await db.select(
        "watchlist_items", where={"watchlist_id": watchlist_id}, user_jwt=user.raw_token
    )
    return WatchlistWithItems(
        **rows[0], items=[WatchlistItem.model_validate(i) for i in items]
    )


@router.get(
    "/{watchlist_id}/alerts",
    response_model=AlertListResponse,
    summary="Alerts on this watchlist's symbols (evaluated; research only)",
)
async def watchlist_alerts(
    watchlist_id: str,
    user: AuthContext = Depends(get_current_user),
    cache: Cache = Depends(get_cache),
    db: SupabaseDB = Depends(get_db),
) -> AlertListResponse:
    """The user's alerts whose symbol is in this watchlist, evaluated against
    the latest cached quote. Ownership-gated; honest-empty when none match."""
    parent = await db.select(
        "watchlists", where={"id": watchlist_id, "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not parent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found."
        )
    items = await db.select(
        "watchlist_items", where={"watchlist_id": watchlist_id}, user_jwt=user.raw_token
    )
    syms = {str(it["symbol"]).upper() for it in items}
    rows = await db.select("alerts", where={"user_id": user.user_id}, user_jwt=user.raw_token)
    rows = [r for r in rows if str(r.get("symbol", "")).upper() in syms]
    return await alert_eval.build_alert_list(rows, cache=cache)


@router.patch(
    "/{watchlist_id}",
    response_model=Watchlist,
    summary="Rename / update a watchlist",
)
async def update_watchlist(
    watchlist_id: str,
    payload: WatchlistUpdate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> Watchlist:
    patch = payload.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty update payload."
        )
    rows = await db.update(
        "watchlists",
        patch,
        where={"id": watchlist_id, "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found."
        )
    return Watchlist.model_validate(rows[0])


@router.delete(
    "/{watchlist_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a watchlist (and its items)",
)
async def delete_watchlist(
    watchlist_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> None:
    # Remove items first so the delete works whether or not the DB cascades;
    # both deletes are RLS-scoped to the owner.
    await db.delete(
        "watchlist_items", where={"watchlist_id": watchlist_id}, user_jwt=user.raw_token
    )
    deleted = await db.delete(
        "watchlists",
        where={"id": watchlist_id, "user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found."
        )


@router.post(
    "/{watchlist_id}/symbols",
    response_model=WatchlistItem,
    status_code=status.HTTP_201_CREATED,
    summary="Add a symbol to a watchlist (by symbol; rejects duplicates)",
)
async def add_watchlist_symbol(
    watchlist_id: str,
    payload: WatchlistItemCreate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> WatchlistItem:
    parent = await db.select(
        "watchlists", where={"id": watchlist_id, "user_id": user.user_id}, user_jwt=user.raw_token
    )
    if not parent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found."
        )
    sym = payload.symbol.upper()
    existing = await db.select(
        "watchlist_items",
        where={"watchlist_id": watchlist_id, "symbol": sym},
        user_jwt=user.raw_token,
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Symbol already in watchlist."
        )
    try:
        row = await db.insert(
            "watchlist_items",
            {
                "watchlist_id": watchlist_id,
                "symbol": sym,
                "exchange": payload.exchange,
                "display_order": payload.display_order,
            },
            user_jwt=user.raw_token,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return WatchlistItem.model_validate(row)


@router.delete(
    "/{watchlist_id}/symbols/{symbol}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a symbol from a watchlist (by symbol)",
)
async def remove_watchlist_symbol(
    watchlist_id: str,
    symbol: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> None:
    deleted = await db.delete(
        "watchlist_items",
        where={"watchlist_id": watchlist_id, "symbol": symbol.upper()},
        user_jwt=user.raw_token,
    )
    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Symbol not found in watchlist."
        )


@router.post(
    "/{watchlist_id}/items",
    response_model=WatchlistItem,
    status_code=status.HTTP_201_CREATED,
    summary="Add a symbol to a watchlist",
)
async def add_watchlist_item(
    watchlist_id: str,
    payload: WatchlistItemCreate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> WatchlistItem:
    # Confirm the watchlist exists *and* belongs to this user. RLS would
    # block the insert anyway; returning 404 here makes intent explicit.
    parent = await db.select(
        "watchlists", where={"id": watchlist_id, "user_id": user.user_id}, user_jwt=user.raw_token
    )
    if not parent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist not found."
        )
    try:
        row = await db.insert(
            "watchlist_items",
            {
                "watchlist_id": watchlist_id,
                "symbol": payload.symbol.upper(),
                "exchange": payload.exchange,
                "display_order": payload.display_order,
            },
            user_jwt=user.raw_token,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return WatchlistItem.model_validate(row)


@router.delete(
    "/{watchlist_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a symbol from a watchlist",
)
async def remove_watchlist_item(
    watchlist_id: str,
    item_id: str,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> None:
    deleted = await db.delete(
        "watchlist_items",
        where={"id": item_id, "watchlist_id": watchlist_id},
        user_jwt=user.raw_token,
    )
    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found."
        )
