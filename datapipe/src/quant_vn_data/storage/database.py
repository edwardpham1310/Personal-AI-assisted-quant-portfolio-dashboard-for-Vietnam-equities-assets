"""SQLAlchemy engine + declarative base."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str) -> None:
        self._url = url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, connect_args=connect_args, echo=False)
        self._SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        _enable_sqlite_wal(self.engine)

    def create_all(self) -> None:
        from . import migrations  # noqa: F401 — registers models
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        return self._SessionLocal()

    def dispose(self) -> None:
        self.engine.dispose()


def _enable_sqlite_wal(engine: Engine) -> None:
    if not engine.url.drivername.startswith("sqlite"):
        return

    @event.listens_for(engine, "connect")
    def set_wal(dbapi_conn, _conn_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


_db_instance: Database | None = None


def get_db(url: str | None = None) -> Database:
    global _db_instance
    if _db_instance is None:
        from quant_vn_data.config import get_settings
        resolved_url = url or get_settings().database_url
        _ensure_database_dir(resolved_url)
        db = Database(resolved_url)
        db.create_all()
        _db_instance = db
    return _db_instance


def _ensure_database_dir(url: str) -> None:
    if url.startswith("sqlite:///"):
        path = Path(url[len("sqlite:///"):])
        path.parent.mkdir(parents=True, exist_ok=True)
