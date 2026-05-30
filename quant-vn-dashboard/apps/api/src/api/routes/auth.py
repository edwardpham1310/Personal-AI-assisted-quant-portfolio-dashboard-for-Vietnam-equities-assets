"""Auth routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core.security import AuthContext, get_current_user
from schemas.auth import AuthMeResponse

router = APIRouter()


@router.get(
    "/me",
    response_model=AuthMeResponse,
    summary="Return the authenticated user (verified from JWT)",
)
def me(user: AuthContext = Depends(get_current_user)) -> AuthMeResponse:
    return AuthMeResponse(user_id=user.user_id, email=user.email, role=user.role)
