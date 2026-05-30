"""User settings DTOs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Theme = Literal["dark", "light"]
RiskProfile = Literal["conservative", "moderate", "aggressive"]


class UserSettings(BaseModel):
    id: str | None = None
    user_id: str | None = None
    default_broker: str = "SSI"
    risk_profile: RiskProfile = "moderate"
    default_watchlist_id: str | None = None
    theme: Theme = "dark"
    created_at: str | None = None
    updated_at: str | None = None


class UserSettingsUpdate(BaseModel):
    default_broker: str | None = Field(default=None, max_length=32)
    risk_profile: RiskProfile | None = None
    default_watchlist_id: str | None = None
    theme: Theme | None = None
