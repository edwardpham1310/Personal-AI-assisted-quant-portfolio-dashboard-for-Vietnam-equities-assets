"""SQLAlchemy ORM models and storage repository for quant-vn."""

from __future__ import annotations

import datetime
import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import pandas as pd
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)


# ── ORM Models ─────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class PriceBar(Base):
    __tablename__ = "price_bars"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False)
    exchange = Column(String(6), nullable=False, default="HOSE")
    date = Column(Date, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Integer, nullable=False)
    is_adjusted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("symbol", "date", "is_adjusted", name="uq_price_bar"),
        Index("ix_price_symbol_date", "symbol", "date"),
        Index("ix_price_date", "date"),
    )


class SymbolInfo(Base):
    __tablename__ = "symbols"

    symbol = Column(String(10), primary_key=True)
    exchange = Column(String(6), nullable=False, default="HOSE")
    name = Column(String(200))
    sector = Column(String(100))
    listed_date = Column(Date)
    delisted_date = Column(Date)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class CorporateAction(Base):
    __tablename__ = "corporate_actions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False)
    ex_date = Column(Date, nullable=False)
    action_type = Column(String(20), nullable=False)  # DIVIDEND | SPLIT | BONUS
    ratio = Column(Float)
    cash_amount = Column(Float)
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_ca_symbol_date", "symbol", "ex_date"),
    )


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    strategy_name = Column(String(50), nullable=False)
    params_json = Column(Text, nullable=False)
    symbol = Column(String(50), nullable=False)  # can be comma-sep for portfolio
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    initial_capital = Column(Float)
    total_return = Column(Float)
    cagr = Column(Float)
    sharpe = Column(Float)
    max_drawdown = Column(Float)
    win_rate = Column(Float)
    n_trades = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_bt_strategy_symbol", "strategy_name", "symbol"),
    )


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(BigInteger, nullable=False)
    symbol = Column(String(10), nullable=False)
    entry_date = Column(Date, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_date = Column(Date)
    exit_price = Column(Float)
    quantity = Column(Float, nullable=False)
    gross_pnl = Column(Float)
    net_pnl = Column(Float)
    cost = Column(Float)
    holding_days = Column(Integer)
    return_pct = Column(Float)
    exit_reason = Column(String(50))

    __table_args__ = (
        Index("ix_trade_run_id", "run_id"),
        Index("ix_trade_symbol", "symbol"),
    )


class BacktestEquityCurve(Base):
    __tablename__ = "backtest_equity_curve"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(BigInteger, nullable=False)
    date = Column(Date, nullable=False)
    equity = Column(Float, nullable=False)
    cash = Column(Float)
    position_value = Column(Float)
    drawdown = Column(Float)

    __table_args__ = (
        Index("ix_eq_run_date", "run_id", "date"),
    )


# ── Database Manager ────────────────────────────────────────────────────────────

class Database:
    """Manages SQLAlchemy engine and session lifecycle."""

    def __init__(self, url: str):
        # Ensure parent directory exists for SQLite
        if url.startswith("sqlite:///"):
            db_path = Path(url.replace("sqlite:///", ""))
            db_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(
            url,
            connect_args={"check_same_thread": False} if "sqlite" in url else {},
        )
        self._SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def init_db(self) -> None:
        """Create all tables if they don't exist."""
        Base.metadata.create_all(self.engine)
        logger.info("Database initialised at %s", self.engine.url)

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        sess = self._SessionLocal()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()


# ── Price Repository ─────────────────────────────────────────────────────────

class PriceRepository:
    """High-level operations for OHLCV price data."""

    def __init__(self, db: Database):
        self.db = db

    def upsert_ohlcv(self, df: pd.DataFrame, exchange: str = "HOSE") -> int:
        """
        Insert or update OHLCV rows from a DataFrame.
        Returns number of rows written.
        """
        if df.empty:
            return 0

        required = {"symbol", "date", "open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame missing columns: {missing}")

        rows_written = 0
        with self.db.session() as sess:
            for _, row in df.iterrows():
                is_adj = bool(row.get("is_adjusted", False))
                sym = str(row["symbol"]).upper()
                date_val = row["date"]
                if isinstance(date_val, str):
                    date_val = datetime.date.fromisoformat(date_val)
                elif hasattr(date_val, "date"):
                    date_val = date_val.date()

                # Upsert: try to find existing row
                existing = sess.execute(
                    select(PriceBar).where(
                        PriceBar.symbol == sym,
                        PriceBar.date == date_val,
                        PriceBar.is_adjusted == is_adj,
                    )
                ).scalar_one_or_none()

                if existing:
                    existing.open = float(row["open"])
                    existing.high = float(row["high"])
                    existing.low = float(row["low"])
                    existing.close = float(row["close"])
                    existing.volume = int(row["volume"])
                    existing.exchange = exchange
                else:
                    sess.add(PriceBar(
                        symbol=sym,
                        exchange=exchange,
                        date=date_val,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=int(row["volume"]),
                        is_adjusted=is_adj,
                    ))
                    rows_written += 1

        return rows_written

    def get_ohlcv(
        self,
        symbol: str,
        start_date: str | datetime.date,
        end_date: str | datetime.date,
        is_adjusted: bool = False,
    ) -> pd.DataFrame:
        """Load OHLCV from DB as a DataFrame indexed by date."""
        if isinstance(start_date, str):
            start_date = datetime.date.fromisoformat(start_date)
        if isinstance(end_date, str):
            end_date = datetime.date.fromisoformat(end_date)

        with self.db.session() as sess:
            rows = sess.execute(
                select(PriceBar).where(
                    PriceBar.symbol == symbol.upper(),
                    PriceBar.date >= start_date,
                    PriceBar.date <= end_date,
                    PriceBar.is_adjusted == is_adjusted,
                ).order_by(PriceBar.date)
            ).scalars().all()

        if not rows:
            return pd.DataFrame(
                columns=["date", "open", "high", "low", "close", "volume"]
            )

        data = [
            {
                "date": r.date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows
        ]
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        return df

    def get_available_symbols(self) -> list[str]:
        with self.db.session() as sess:
            result = sess.execute(
                select(PriceBar.symbol).distinct().order_by(PriceBar.symbol)
            ).scalars().all()
        return list(result)

    def get_date_range(self, symbol: str) -> tuple[datetime.date | None, datetime.date | None]:
        with self.db.session() as sess:
            result = sess.execute(
                select(func.min(PriceBar.date), func.max(PriceBar.date)).where(
                    PriceBar.symbol == symbol.upper()
                )
            ).one()
        return result[0], result[1]


# ── Backtest Repository ───────────────────────────────────────────────────────

class BacktestRepository:
    """Store and retrieve backtest runs, trades, and equity curves."""

    def __init__(self, db: Database):
        self.db = db

    def save_run(
        self,
        strategy_name: str,
        params: dict,
        symbol: str,
        start_date: datetime.date,
        end_date: datetime.date,
        metrics: dict,
        initial_capital: float,
    ) -> int:
        """Save a backtest run and return its ID."""
        with self.db.session() as sess:
            run = BacktestRun(
                strategy_name=strategy_name,
                params_json=json.dumps(params),
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                total_return=metrics.get("total_return"),
                cagr=metrics.get("cagr"),
                sharpe=metrics.get("sharpe"),
                max_drawdown=metrics.get("max_drawdown"),
                win_rate=metrics.get("win_rate"),
                n_trades=metrics.get("n_trades"),
            )
            sess.add(run)
            sess.flush()
            run_id = run.id
        return run_id

    def save_trades(self, run_id: int, trades_df: pd.DataFrame) -> None:
        if trades_df.empty:
            return
        with self.db.session() as sess:
            for _, row in trades_df.iterrows():
                sess.add(BacktestTrade(
                    run_id=run_id,
                    symbol=str(row.get("symbol", "")),
                    entry_date=row.get("entry_date"),
                    entry_price=float(row.get("entry_price", 0)),
                    exit_date=row.get("exit_date"),
                    exit_price=float(row.get("exit_price", 0)) if row.get("exit_price") else None,
                    quantity=float(row.get("quantity", 0)),
                    gross_pnl=float(row.get("gross_pnl", 0)),
                    net_pnl=float(row.get("net_pnl", 0)),
                    cost=float(row.get("cost", 0)),
                    holding_days=int(row.get("holding_days", 0)),
                    return_pct=float(row.get("return_pct", 0)),
                    exit_reason=str(row.get("exit_reason", "")),
                ))

    def save_equity_curve(self, run_id: int, equity_df: pd.DataFrame) -> None:
        if equity_df.empty:
            return
        with self.db.session() as sess:
            for date_val, row in equity_df.iterrows():
                d = date_val.date() if hasattr(date_val, "date") else date_val
                sess.add(BacktestEquityCurve(
                    run_id=run_id,
                    date=d,
                    equity=float(row.get("equity", 0)),
                    cash=float(row.get("cash", 0)) if "cash" in row else None,
                    position_value=float(row.get("position_value", 0)) if "position_value" in row else None,
                    drawdown=float(row.get("drawdown", 0)) if "drawdown" in row else None,
                ))

    def list_runs(self, strategy_name: str | None = None, symbol: str | None = None) -> pd.DataFrame:
        with self.db.session() as sess:
            q = select(BacktestRun)
            if strategy_name:
                q = q.where(BacktestRun.strategy_name == strategy_name)
            if symbol:
                q = q.where(BacktestRun.symbol == symbol.upper())
            q = q.order_by(BacktestRun.created_at.desc())
            rows = sess.execute(q).scalars().all()

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame([{
            "id": r.id,
            "strategy_name": r.strategy_name,
            "symbol": r.symbol,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "total_return": r.total_return,
            "cagr": r.cagr,
            "sharpe": r.sharpe,
            "max_drawdown": r.max_drawdown,
            "win_rate": r.win_rate,
            "n_trades": r.n_trades,
            "created_at": r.created_at,
        } for r in rows])
