"""Watchlist routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from core.deps import get_db
from core.security import AuthContext, get_current_user
from schemas.watchlist import (
    Watchlist,
    WatchlistCreate,
    WatchlistItem,
    WatchlistItemCreate,
    WatchlistWithItems,
)
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
        "watchlists", where={"id": watchlist_id}, user_jwt=user.raw_token
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
