"""User settings routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from core.deps import get_db
from core.security import AuthContext, get_current_user
from schemas.settings import UserSettings, UserSettingsUpdate
from services.supabase_db import SupabaseDB

router = APIRouter()


def _to_settings(row: dict) -> UserSettings:
    return UserSettings.model_validate(row)


@router.get("", response_model=UserSettings, summary="Get the current user's settings")
async def get_settings(
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> UserSettings:
    rows = await db.select(
        "user_settings",
        where={"user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if rows:
        return _to_settings(rows[0])

    # In production, the on_auth_user_created trigger creates this row. If a
    # row is somehow missing (e.g. user predates the trigger), create the default.
    created = await db.insert(
        "user_settings",
        {"user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    return _to_settings(created)


@router.put("", response_model=UserSettings, summary="Update the current user's settings")
async def update_settings(
    payload: UserSettingsUpdate,
    user: AuthContext = Depends(get_current_user),
    db: SupabaseDB = Depends(get_db),
) -> UserSettings:
    patch = payload.model_dump(exclude_none=True)
    if not patch:
        # Nothing to do — return current state.
        return await get_settings(user=user, db=db)

    rows = await db.update(
        "user_settings",
        patch,
        where={"user_id": user.user_id},
        user_jwt=user.raw_token,
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Settings row not found.",
        )
    return _to_settings(rows[0])
