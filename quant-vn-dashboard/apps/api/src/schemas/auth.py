"""Auth DTOs."""

from __future__ import annotations

from pydantic import BaseModel


class AuthMeResponse(BaseModel):
    user_id: str
    email: str | None = None
    role: str
