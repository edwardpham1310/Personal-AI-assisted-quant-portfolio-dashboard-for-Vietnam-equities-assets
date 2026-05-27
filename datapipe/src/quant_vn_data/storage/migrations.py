"""ORM model definitions — import this module to register all tables with Base.metadata."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class SymbolRecord(Base):
    __tablename__ = "symbols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(200))
    isin: Mapped[Optional[str]] = mapped_column(String(20))
    type: Mapped[Optional[str]] = mapped_column(String(30))
    listed_date: Mapped[Optional[date]] = mapped_column(Date)
    delisted_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[Optional[str]] = mapped_column(String(20))
    source: Mapped[Optional[str]] = mapped_column(String(30))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("symbol", "exchange", "source", name="uq_symbol_exchange_source"),
    )


class OHLCVDailyRecord(Base):
    __tablename__ = "ohlcv_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    exchange: Mapped[Optional[str]] = mapped_column(String(10))
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Optional[float]] = mapped_column(Float)
    high: Mapped[Optional[float]] = mapped_column(Float)
    low: Mapped[Optional[float]] = mapped_column(Float)
    close: Mapped[Optional[float]] = mapped_column(Float)
    adjusted_close: Mapped[Optional[float]] = mapped_column(Float)
    volume: Mapped[Optional[int]] = mapped_column(BigInteger)
    value: Mapped[Optional[float]] = mapped_column(Float)
    reference_price: Mapped[Optional[float]] = mapped_column(Float)
    ceiling_price: Mapped[Optional[float]] = mapped_column(Float)
    floor_price: Mapped[Optional[float]] = mapped_column(Float)
    foreign_buy_volume: Mapped[Optional[int]] = mapped_column(BigInteger)
    foreign_sell_volume: Mapped[Optional[int]] = mapped_column(BigInteger)
    foreign_buy_value: Mapped[Optional[float]] = mapped_column(Float)
    foreign_sell_value: Mapped[Optional[float]] = mapped_column(Float)
    proprietary_buy_value: Mapped[Optional[float]] = mapped_column(Float)
    proprietary_sell_value: Mapped[Optional[float]] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    source_priority: Mapped[Optional[int]] = mapped_column(Integer)
    is_adjusted: Mapped[bool] = mapped_column(Boolean, default=False)
    ingestion_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    quality_status: Mapped[str] = mapped_column(String(20), default="OK")

    __table_args__ = (
        UniqueConstraint("symbol", "trading_date", "source", name="uq_ohlcv_symbol_date_source"),
        Index("ix_ohlcv_symbol_date", "symbol", "trading_date"),
        Index("ix_ohlcv_symbol_source", "symbol", "source"),
        Index("ix_ohlcv_date", "trading_date"),
        Index("ix_ohlcv_source", "source"),
        Index("ix_ohlcv_quality", "quality_status"),
    )


class CorporateActionRecord(Base):
    __tablename__ = "corporate_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(20))
    isin: Mapped[Optional[str]] = mapped_column(String(20))
    exchange: Mapped[Optional[str]] = mapped_column(String(10))
    announcement_date: Mapped[Optional[date]] = mapped_column(Date)
    record_date: Mapped[Optional[date]] = mapped_column(Date)
    ex_date: Mapped[Optional[date]] = mapped_column(Date)
    payment_date: Mapped[Optional[date]] = mapped_column(Date)
    action_type: Mapped[Optional[str]] = mapped_column(String(50))
    cash_dividend: Mapped[Optional[float]] = mapped_column(Float)
    cash_dividend_currency: Mapped[Optional[str]] = mapped_column(String(5))
    stock_dividend_ratio: Mapped[Optional[float]] = mapped_column(Float)
    bonus_share_ratio: Mapped[Optional[float]] = mapped_column(Float)
    rights_issue_ratio: Mapped[Optional[float]] = mapped_column(Float)
    rights_issue_price: Mapped[Optional[float]] = mapped_column(Float)
    split_ratio: Mapped[Optional[float]] = mapped_column(Float)
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[Optional[str]] = mapped_column(String(30))
    source_url: Mapped[Optional[str]] = mapped_column(String(500))
    ingestion_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    parse_status: Mapped[str] = mapped_column(String(20), default="PARSED")

    __table_args__ = (
        # Prevents duplicate rows on re-ingest; ex_date may be None for some action types
        UniqueConstraint("symbol", "action_type", "source", "announcement_date", name="uq_ca_symbol_action_source_ann"),
    )


class ProviderReconciliationRecord(Base):
    __tablename__ = "provider_reconciliation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    field_name: Mapped[str] = mapped_column(String(50), nullable=False)
    primary_source: Mapped[str] = mapped_column(String(30), nullable=False)
    secondary_source: Mapped[str] = mapped_column(String(30), nullable=False)
    primary_value: Mapped[Optional[float]] = mapped_column(Float)
    secondary_value: Mapped[Optional[float]] = mapped_column(Float)
    absolute_difference: Mapped[Optional[float]] = mapped_column(Float)
    percentage_difference: Mapped[Optional[float]] = mapped_column(Float)
    tolerance: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("symbol", "trading_date", "field_name", "primary_source", "secondary_source",
                         name="uq_recon_key"),
        Index("ix_recon_symbol_date", "symbol", "trading_date"),
    )


class DataQualityIssueRecord(Base):
    __tablename__ = "data_quality_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(20))
    trading_date: Mapped[Optional[date]] = mapped_column(Date)
    source: Mapped[Optional[str]] = mapped_column(String(30))
    issue_type: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    field_name: Mapped[Optional[str]] = mapped_column(String(50))
    observed_value: Mapped[Optional[str]] = mapped_column(String(200))
    expected_rule: Mapped[Optional[str]] = mapped_column(String(200))
    message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    __table_args__ = (
        Index("ix_dqi_symbol", "symbol"),
        Index("ix_dqi_severity", "severity"),
    )


class LiquidityFeatureRecord(Base):
    __tablename__ = "liquidity_features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    avg_volume_20d: Mapped[Optional[float]] = mapped_column(Float)
    avg_volume_60d: Mapped[Optional[float]] = mapped_column(Float)
    avg_value_20d: Mapped[Optional[float]] = mapped_column(Float)
    avg_value_60d: Mapped[Optional[float]] = mapped_column(Float)
    zero_volume_days_20d: Mapped[Optional[int]] = mapped_column(Integer)
    zero_volume_days_60d: Mapped[Optional[int]] = mapped_column(Integer)
    limit_up_days_20d: Mapped[Optional[int]] = mapped_column(Integer)
    limit_down_days_20d: Mapped[Optional[int]] = mapped_column(Integer)
    turnover_estimate: Mapped[Optional[float]] = mapped_column(Float)
    tradable_flag: Mapped[Optional[bool]] = mapped_column(Boolean)
    liquidity_bucket: Mapped[Optional[str]] = mapped_column(String(20))

    __table_args__ = (
        UniqueConstraint("symbol", "trading_date", name="uq_liquidity_symbol_date"),
        Index("ix_liquidity_symbol_date", "symbol", "trading_date"),
    )
