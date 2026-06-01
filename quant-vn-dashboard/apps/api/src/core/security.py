"""Supabase JWT verification + the FastAPI auth dependency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from core.config import Settings, get_settings

_HS256 = "HS256"
_DEFAULT_AUDIENCE = "authenticated"


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    """Resolved authenticated user. Always derived from a verified JWT."""

    user_id: str
    email: str | None
    role: str
    raw_token: str
    claims: dict[str, Any]


def verify_supabase_jwt(token: str, settings: Settings) -> dict[str, Any]:
    """Verify a Supabase access token's HS256 signature locally.

    Raises:
        HTTPException 503 — when the API has no JWT secret configured.
        HTTPException 401 — when the token is malformed, expired, or has a bad signature.
    """
    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SUPABASE_JWT_SECRET is not configured on the API.",
        )
    try:
        claims = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=[_HS256],
            audience=_DEFAULT_AUDIENCE,
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if not claims.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing 'sub' claim.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    """Resolve the authenticated user from the Authorization header.

    The ``user_id`` returned here is the canonical identity for every
    downstream call. Routes MUST NOT trust ``user_id`` values supplied in
    request bodies.
    """
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = verify_supabase_jwt(creds.credentials, settings)
    return AuthContext(
        user_id=str(claims["sub"]),
        email=claims.get("email"),
        role=str(claims.get("role", "authenticated")),
        raw_token=creds.credentials,
        claims=claims,
    )
