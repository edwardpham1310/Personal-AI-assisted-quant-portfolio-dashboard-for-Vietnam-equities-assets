"""Watchlist DTOs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Exchange = Literal["HOSE", "HNX", "UPCOM"]


class WatchlistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=400)


class WatchlistItem(BaseModel):
    id: str
    watchlist_id: str
    symbol: str
    exchange: Exchange = "HOSE"
    display_order: int = 0
    created_at: str | None = None


class WatchlistItemCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    exchange: Exchange = "HOSE"
    display_order: int = 0


class Watchlist(BaseModel):
    id: str
    user_id: str
    name: str
    description: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class WatchlistWithItems(Watchlist):
    items: list[WatchlistItem] = []
