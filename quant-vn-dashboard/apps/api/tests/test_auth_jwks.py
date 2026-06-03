"""JWT verification for Supabase asymmetric (RS256/ES256) signing keys + the
algorithm whitelist. The HS256 legacy path is covered by test_auth.py."""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException
from jose import jwk
from jose import jwt as jose_jwt

import core.security as sec
from core.config import Settings


def _rsa_keypair() -> tuple[str, dict]:
    """Return (private_pem, public_jwk_with_kid) for an ephemeral RSA key."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_jwk = jwk.construct(pub_pem, "RS256").to_dict()
    public_jwk["kid"] = "test-kid-001"
    public_jwk["alg"] = "RS256"
    public_jwk["use"] = "sig"
    return priv_pem, public_jwk


def _ec_keypair() -> tuple[str, dict]:
    """Return (private_pem, public_jwk_with_kid) for an ephemeral ES256 (P-256) key.

    Supabase's new JWT signing keys default to ECC P-256 (ES256), so this is the
    most likely production token type.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    priv = ec.generate_private_key(ec.SECP256R1())
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_jwk = jwk.construct(pub_pem, "ES256").to_dict()
    public_jwk["kid"] = "test-ec-kid-001"
    public_jwk["alg"] = "ES256"
    public_jwk["use"] = "sig"
    return priv_pem, public_jwk


def _claims(sub: str = "user-123") -> dict:
    return {
        "sub": sub,
        "aud": "authenticated",
        "email": "a@b.com",
        "role": "authenticated",
        "exp": int(time.time()) + 3600,
    }


def test_hs256_still_verifies() -> None:
    secret = "unit-secret"
    token = jose_jwt.encode(_claims(), secret, algorithm="HS256")
    settings = Settings(supabase_jwt_secret=secret)
    claims = sec.verify_supabase_jwt(token, settings)
    assert claims["sub"] == "user-123"


def test_rs256_token_verified_via_jwks(monkeypatch) -> None:
    priv_pem, public_jwk = _rsa_keypair()
    token = jose_jwt.encode(
        _claims("rsa-user"), priv_pem, algorithm="RS256", headers={"kid": "test-kid-001"}
    )
    # Serve the public key from the (monkeypatched) JWKS lookup — no network.
    monkeypatch.setattr(sec, "_jwks_key_for", lambda kid, url: public_jwk if kid == "test-kid-001" else None)
    settings = Settings(supabase_url="https://proj.supabase.co", supabase_jwt_secret="")
    claims = sec.verify_supabase_jwt(token, settings)
    assert claims["sub"] == "rsa-user"


def test_es256_token_verified_via_jwks(monkeypatch) -> None:
    """ES256 (ECC P-256) is Supabase's default new signing-key algorithm."""
    priv_pem, public_jwk = _ec_keypair()
    token = jose_jwt.encode(
        _claims("ec-user"), priv_pem, algorithm="ES256", headers={"kid": "test-ec-kid-001"}
    )
    monkeypatch.setattr(
        sec, "_jwks_key_for", lambda kid, url: public_jwk if kid == "test-ec-kid-001" else None
    )
    settings = Settings(supabase_url="https://proj.supabase.co", supabase_jwt_secret="")
    claims = sec.verify_supabase_jwt(token, settings)
    assert claims["sub"] == "ec-user"


def test_rs256_unknown_kid_returns_401(monkeypatch) -> None:
    priv_pem, _ = _rsa_keypair()
    token = jose_jwt.encode(
        _claims(), priv_pem, algorithm="RS256", headers={"kid": "rotated-out"}
    )
    monkeypatch.setattr(sec, "_jwks_key_for", lambda kid, url: None)  # kid not in JWKS
    settings = Settings(supabase_url="https://proj.supabase.co")
    with pytest.raises(HTTPException) as exc:
        sec.verify_supabase_jwt(token, settings)
    assert exc.value.status_code == 401
    assert "signing key not found" in exc.value.detail


@pytest.mark.parametrize("alg", ["HS384", "HS512"])
def test_unsupported_algorithm_rejected(alg: str) -> None:
    token = jose_jwt.encode(_claims(), "x", algorithm=alg)
    settings = Settings(supabase_jwt_secret="x")
    with pytest.raises(HTTPException) as exc:
        sec.verify_supabase_jwt(token, settings)
    assert exc.value.status_code == 401
    assert "unsupported algorithm" in exc.value.detail.lower()


def test_asymmetric_without_supabase_url_returns_503() -> None:
    priv_pem, _ = _rsa_keypair()
    token = jose_jwt.encode(
        _claims(), priv_pem, algorithm="RS256", headers={"kid": "k"}
    )
    settings = Settings(supabase_url="", supabase_jwt_secret="")
    with pytest.raises(HTTPException) as exc:
        sec.verify_supabase_jwt(token, settings)
    assert exc.value.status_code == 503


def test_malformed_token_returns_401() -> None:
    settings = Settings(supabase_jwt_secret="x")
    with pytest.raises(HTTPException) as exc:
        sec.verify_supabase_jwt("not.a.jwt", settings)
    assert exc.value.status_code == 401


def test_hs256_token_does_not_verify_with_jwks_path(monkeypatch) -> None:
    """Alg-confusion guard: an HS256 token always takes the secret path; an
    asymmetric public key is never used as the HS secret."""
    _, public_jwk = _rsa_keypair()
    # Even if JWKS would return a key, an HS256 token must verify against the
    # secret (and fail with the wrong secret), never against the JWK.
    monkeypatch.setattr(sec, "_jwks_key_for", lambda kid, url: public_jwk)
    token = jose_jwt.encode(_claims(), "real-secret", algorithm="HS256")
    settings = Settings(supabase_jwt_secret="WRONG-secret", supabase_url="https://p.supabase.co")
    with pytest.raises(HTTPException) as exc:
        sec.verify_supabase_jwt(token, settings)
    assert exc.value.status_code == 401  # bad signature, not silently JWKS-verified
