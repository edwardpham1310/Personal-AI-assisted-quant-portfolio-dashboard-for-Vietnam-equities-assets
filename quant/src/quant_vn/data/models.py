"""Pydantic data models for OHLCV bars and validation results."""

from __future__ import annotations

import datetime
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator


class OHLCVBar(BaseModel):
    """Single daily OHLCV bar for one symbol."""

    model_config = {"frozen": True}

    symbol: str
    date: datetime.date
    open: float
    high: float
    low: float
    close: float
    volume: int
    exchange: str = "HOSE"
    is_adjusted: bool = False

    @field_validator("symbol")
    @classmethod
    def symbol_upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("exchange")
    @classmethod
    def exchange_upper(cls, v: str) -> str:
        val = v.strip().upper()
        if val not in ("HOSE", "HNX", "UPCOM"):
            raise ValueError(f"exchange must be HOSE, HNX, or UPCOM, got '{v}'")
        return val

    @field_validator("open", "high", "low", "close")
    @classmethod
    def price_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Price must be positive")
        return v

    @field_validator("volume")
    @classmethod
    def volume_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Volume must be non-negative")
        return v

    @model_validator(mode="after")
    def ohlc_relationships(self) -> "OHLCVBar":
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) < low ({self.low})")
        if self.high < self.open or self.high < self.close:
            raise ValueError("high must be >= open and close")
        if self.low > self.open or self.low > self.close:
            raise ValueError("low must be <= open and close")
        return self


class ValidationIssue(BaseModel):
    """Describes a single data quality issue found during validation."""

    symbol: str
    date: Optional[datetime.date] = None
    issue_type: str
    description: str
    severity: str = "warning"  # warning | error


class DataQualityReport(BaseModel):
    """Summary of data quality for a symbol or dataset."""

    symbol: str
    total_rows: int
    first_date: Optional[datetime.date] = None
    last_date: Optional[datetime.date] = None
    missing_dates: int = 0
    duplicate_rows: int = 0
    invalid_ohlc_rows: int = 0
    zero_volume_days: int = 0
    price_spike_count: int = 0
    issues: list[ValidationIssue] = []

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    def summary_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "total_rows": self.total_rows,
            "first_date": str(self.first_date) if self.first_date else None,
            "last_date": str(self.last_date) if self.last_date else None,
            "missing_dates": self.missing_dates,
            "duplicate_rows": self.duplicate_rows,
            "invalid_ohlc_rows": self.invalid_ohlc_rows,
            "zero_volume_days": self.zero_volume_days,
            "price_spike_count": self.price_spike_count,
            "issue_count": len(self.issues),
            "has_errors": self.has_errors,
        }
