"""DTOs for the fundamentals layer.

SSI FastConnect Data does NOT expose company fundamentals (ROE, net
profit, audit opinion). The guardrail upgrade therefore reads
fundamentals through a separate ``FundamentalDataProvider`` interface
backed by either a DB master row (operator-uploaded via CSV) or a
future paid vendor integration.

Every field is optional so a partially-populated row still works for
relaxed-mode evaluation. The strict-mode guardrail layer is the one
that turns missing fields into REJECT — never default a missing field
to a value that would pass a check.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


# Per-symbol availability flag the response surfaces so the UI can render
# a "fundamentals missing" badge without scanning rejection codes.
FundamentalDataStatus = Literal[
    "FUNDAMENTAL_DATA_AVAILABLE",
    "FUNDAMENTAL_DATA_MISSING",
    "FUNDAMENTAL_DATA_PARTIAL",
]


# Accepted normalised audit-opinion codes (case-insensitive on the
# input side; the provider normalises before persisting).
AuditOpinion = Literal[
    "UNQUALIFIED",            # canonical clean opinion
    "QUALIFIED",
    "ADVERSE",
    "DISCLAIMER",
]


# Source-of-record tag attached to derived or third-party fields. Used
# for forensic queries ("which provider gave us this market_cap?").
FundamentalSource = Literal[
    "SSI",
    "DERIVED_FROM_LISTED_SHARE_AND_LAST_PRICE",
    "CSV",
    "DB",
    "WICHART",
    "FIIN",
    "VIETSTOCK",
    "UNKNOWN",
]


class Fundamentals(BaseModel):
    """Per-symbol fundamentals snapshot.

    All fields are optional. A row with every field ``None`` is the
    same shape as a missing row — the provider returns ``None`` rather
    than an empty ``Fundamentals`` so callers can tell them apart.
    """

    symbol: str

    market_cap: float | None = None
    market_cap_source: FundamentalSource | None = None

    listed_share: float | None = None  # outstanding shares
    roe: float | None = Field(default=None, description="trailing-12m return on equity, percent")
    net_profit_last_4_quarters: list[float] | None = Field(
        default=None,
        description=(
            "Quarterly net profit for the trailing 4 quarters in chronological "
            "order (oldest first). Length 4 required for the guardrail check."
        ),
    )
    audit_opinion: AuditOpinion | None = None

    fiscal_period: str | None = None      # e.g. "2025-Q4" — most recent period covered
    fundamentals_source: FundamentalSource | None = None
    fundamentals_as_of: date | None = None

    # Universe-membership flags surfaced together with fundamentals
    # because the same master row carries them.
    is_vn30: bool | None = None
    is_vn100: bool | None = None


def compute_data_status(f: Fundamentals | None) -> FundamentalDataStatus:
    """Classify how much of the gate-relevant fundamentals we actually
    have. The strict guardrail layer uses this for rejection wording."""
    if f is None:
        return "FUNDAMENTAL_DATA_MISSING"
    gate_fields = (
        f.market_cap,
        f.roe,
        f.net_profit_last_4_quarters,
        f.audit_opinion,
    )
    have = sum(1 for v in gate_fields if v is not None)
    if have == 0:
        return "FUNDAMENTAL_DATA_MISSING"
    if have == len(gate_fields):
        return "FUNDAMENTAL_DATA_AVAILABLE"
    return "FUNDAMENTAL_DATA_PARTIAL"
