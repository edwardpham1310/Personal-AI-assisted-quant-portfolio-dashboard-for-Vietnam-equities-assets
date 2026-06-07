"""Alert DTOs.

An alert is a research notification rule (price / daily-change threshold on a
symbol). It is decision-support only — evaluating an alert NEVER places an
order. Thresholds: a price in VND for ``price_*``; a daily-change FRACTION
(0.03 = +3%) for ``pct_change_*``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Exchange = Literal["HOSE", "HNX", "UPCOM"]

AlertCondition = Literal[
    "price_above",
    "price_below",
    "pct_change_above",
    "pct_change_below",
]


class AlertCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    condition: AlertCondition
    threshold: float
    exchange: Exchange = "HOSE"
    note: str | None = Field(default=None, max_length=280)


class AlertUpdate(BaseModel):
    condition: AlertCondition | None = None
    threshold: float | None = None
    note: str | None = Field(default=None, max_length=280)
    is_active: bool | None = None


class Alert(BaseModel):
    id: str
    user_id: str
    symbol: str
    exchange: Exchange = "HOSE"
    condition: AlertCondition
    threshold: float
    note: str | None = None
    is_active: bool = True
    last_triggered_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AlertWithStatus(Alert):
    """Alert plus a point-in-time evaluation against the latest cached quote."""

    evaluated: bool = False          # False when no quote was available
    currently_triggered: bool | None = None
    observed_price: float | None = None
    observed_change_pct: float | None = None
    quote_stale: bool = False
    quote_as_of: str | None = None


class AlertListResponse(BaseModel):
    alerts: list[AlertWithStatus] = Field(default_factory=list)
    count: int = 0
    triggered_count: int = 0
    as_of: str | None = None
    disclaimer: str = (
        "Alerts are research notifications — decision support only, not "
        "financial advice. No orders are placed."
    )
