"""Supabase JWT verification + the FastAPI auth dependency.

Supports both Supabase token signing schemes:
  * Legacy shared-secret HS256 (verified with ``SUPABASE_JWT_SECRET``).
  * Asymmetric RS256/ES256 (the newer "JWT signing keys"), verified against
    the project's public JWKS at ``{SUPABASE_URL}/auth/v1/.well-known/jwks.json``.

The signing algorithm is read from the token header and strictly whitelisted;
the verification key is chosen by the server per algorithm class, so an
asymmetric public key is never fed into HS256 verification (alg-confusion safe).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_HS256 = "HS256"
_SYMMETRIC_ALGS = frozenset({_HS256})
_ASYMMETRIC_ALGS = frozenset({"RS256", "ES256"})
_ALLOWED_ALGS = _SYMMETRIC_ALGS | _ASYMMETRIC_ALGS
_DEFAULT_AUDIENCE = "authenticated"

# In-memory JWKS cache (kid -> JWK dict). Refreshed on TTL expiry or on a kid
# cache-miss (handles key rotation without waiting for the TTL).
_JWKS_TTL_SECONDS = 3600.0
_jwks_keys: dict[str, dict[str, Any]] = {}
_jwks_fetched_at: float = 0.0
_jwks_url: str | None = None


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    """Resolved authenticated user. Always derived from a verified JWT."""

    user_id: str
    email: str | None
    role: str
    raw_token: str
    claims: dict[str, Any]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _jwks_endpoint(supabase_url: str) -> str:
    return f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


def _fetch_jwks(supabase_url: str) -> dict[str, dict[str, Any]]:
    """Fetch the Supabase JWKS. Raises HTTPException(503) on a fetch failure so a
    transient Supabase outage logs users out with a retryable error, not a 401."""
    url = _jwks_endpoint(supabase_url)
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 (trusted https Supabase URL)
            payload = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.error("jwks_fetch_failed url=%s err=%s", url, type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth signing keys are temporarily unavailable.",
        ) from exc
    return {k["kid"]: k for k in payload.get("keys", []) if k.get("kid")}


def _jwks_key_for(kid: str, supabase_url: str) -> dict[str, Any] | None:
    """Return the JWK for ``kid``, fetching/refreshing the cache as needed."""
    global _jwks_keys, _jwks_fetched_at, _jwks_url
    now = time.monotonic()
    cache_fresh = (
        _jwks_url == _jwks_endpoint(supabase_url)
        and bool(_jwks_keys)
        and (now - _jwks_fetched_at) < _JWKS_TTL_SECONDS
    )
    if cache_fresh and kid in _jwks_keys:
        return _jwks_keys[kid]
    # Cold cache, TTL expiry, or unknown kid (possible rotation) -> (re)fetch once.
    _jwks_keys = _fetch_jwks(supabase_url)
    _jwks_fetched_at = time.monotonic()
    _jwks_url = _jwks_endpoint(supabase_url)
    return _jwks_keys.get(kid)


def verify_supabase_jwt(token: str, settings: Settings) -> dict[str, Any]:
    """Verify a Supabase access token (HS256 secret or RS256/ES256 via JWKS).

    Raises:
        HTTPException 503 — when the required key material/config is absent.
        HTTPException 401 — when the token is malformed, uses a disallowed
            algorithm, is signed by an unknown key, or fails verification.
    """
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise _unauthorized(f"Invalid token: {exc}") from exc

    alg = header.get("alg", "")
    # Whitelist BEFORE selecting any key — rejects "none", HS384/512, PS*, etc.
    if alg not in _ALLOWED_ALGS:
        raise _unauthorized(f"Invalid token: unsupported algorithm {alg!r}.")

    if alg in _SYMMETRIC_ALGS:
        if not settings.supabase_jwt_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SUPABASE_JWT_SECRET is not configured on the API.",
            )
        key: Any = settings.supabase_jwt_secret
    else:  # RS256 / ES256 — verify with the project's public JWKS key.
        kid = header.get("kid", "")
        if not kid:
            raise _unauthorized("Invalid token: missing 'kid' for asymmetric key.")
        if not settings.supabase_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SUPABASE_URL is not configured; cannot verify asymmetric tokens.",
            )
        key = _jwks_key_for(kid, settings.supabase_url)
        if key is None:
            raise _unauthorized("Invalid token: signing key not found.")

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[alg],  # pin to the single header alg — never the whole whitelist
            audience=_DEFAULT_AUDIENCE,
        )
    except JWTError as exc:
        raise _unauthorized(f"Invalid token: {exc}") from exc

    if not claims.get("sub"):
        raise _unauthorized("Token missing 'sub' claim.")
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
