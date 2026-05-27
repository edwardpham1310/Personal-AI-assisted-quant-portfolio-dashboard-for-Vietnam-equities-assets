"""Pydantic schemas for validated normalized records."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import math

from pydantic import BaseModel, Field, field_validator, model_validator


class OHLCVRow(BaseModel):
    symbol: str
    exchange: Optional[str] = None
    trading_date: date
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    adjusted_close: Optional[float] = None
    volume: Optional[int] = None
    value: Optional[float] = None
    reference_price: Optional[float] = None
    ceiling_price: Optional[float] = None
    floor_price: Optional[float] = None
    foreign_buy_volume: Optional[int] = None
    foreign_sell_volume: Optional[int] = None
    foreign_buy_value: Optional[float] = None
    foreign_sell_value: Optional[float] = None
    proprietary_buy_value: Optional[float] = None
    proprietary_sell_value: Optional[float] = None
    source: str
    source_priority: Optional[int] = None
    is_adjusted: bool = False
    quality_status: str = "OK"

    @field_validator("trading_date", mode="before")
    @classmethod
    def parse_date(cls, v: object) -> date:
        if isinstance(v, date):
            return v
        return date.fromisoformat(str(v)[:10])

    @field_validator("volume", mode="before")
    @classmethod
    def to_int_volume(cls, v: object) -> Optional[int]:
        if v is None:
            return None
        try:
            return int(float(str(v)))
        except (ValueError, TypeError):
            return None

    @field_validator("open", "high", "low", "close", "adjusted_close",
                     "reference_price", "ceiling_price", "floor_price",
                     "value", "foreign_buy_value", "foreign_sell_value",
                     "proprietary_buy_value", "proprietary_sell_value", mode="before")
    @classmethod
    def to_float_or_none(cls, v: object) -> Optional[float]:
        if v is None or v == "" or (isinstance(v, float) and math.isnan(v)):
            return None
        try:
            return float(str(v))
        except (ValueError, TypeError):
            return None


class SymbolRow(BaseModel):
    symbol: str
    exchange: str
    name: Optional[str] = None
    isin: Optional[str] = None
    type: Optional[str] = None
    listed_date: Optional[date] = None
    delisted_date: Optional[date] = None
    status: Optional[str] = "LISTED"
    source: str

    @field_validator("listed_date", "delisted_date", mode="before")
    @classmethod
    def parse_date(cls, v: object) -> Optional[date]:
        if v is None or v == "":
            return None
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            return None


class CorporateActionRow(BaseModel):
    symbol: Optional[str] = None
    isin: Optional[str] = None
    exchange: Optional[str] = None
    announcement_date: Optional[date] = None
    record_date: Optional[date] = None
    ex_date: Optional[date] = None
    payment_date: Optional[date] = None
    action_type: Optional[str] = None
    cash_dividend: Optional[float] = None
    cash_dividend_currency: Optional[str] = "VND"
    stock_dividend_ratio: Optional[float] = None
    bonus_share_ratio: Optional[float] = None
    rights_issue_ratio: Optional[float] = None
    rights_issue_price: Optional[float] = None
    split_ratio: Optional[float] = None
    raw_text: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    parse_status: str = "PARSED"

    @field_validator(
        "announcement_date", "record_date", "ex_date", "payment_date", mode="before"
    )
    @classmethod
    def parse_date(cls, v: object) -> Optional[date]:
        if v is None or v == "":
            return None
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            return None

    @field_validator(
        "cash_dividend", "stock_dividend_ratio", "bonus_share_ratio",
        "rights_issue_ratio", "rights_issue_price", "split_ratio", mode="before"
    )
    @classmethod
    def to_float_or_none(cls, v: object) -> Optional[float]:
        if v is None or v == "":
            return None
        try:
            return float(str(v))
        except (ValueError, TypeError):
            return None
