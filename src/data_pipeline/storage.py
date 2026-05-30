import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import DUCKDB_PATH, SQLITE_PATH, ensure_data_dirs


@contextmanager
def sqlite_connection(path: Path = SQLITE_PATH) -> Iterator[sqlite3.Connection]:
    ensure_data_dirs()
    connection = sqlite3.connect(path)
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def duckdb_connection(path: Path = DUCKDB_PATH) -> Iterator[Any]:
    ensure_data_dirs()
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("duckdb is optional; install the datapipe package extras before use") from exc

    connection = duckdb.connect(str(path))
    try:
        yield connection
    finally:
        connection.close()
