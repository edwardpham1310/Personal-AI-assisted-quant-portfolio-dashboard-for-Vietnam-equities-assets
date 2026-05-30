"""Lightweight data-pipeline interfaces for AI-agent-safe development."""

from .config import (
    CACHE_DATA_DIR,
    DATA_DIR,
    DB_DIR,
    DUCKDB_PATH,
    PROCESSED_DATA_DIR,
    RAW_DATA_DIR,
    SAMPLES_DATA_DIR,
    SQLITE_PATH,
    ensure_data_dirs,
)
from .schemas import CorporateAction, PriceBar, Transaction, ValidationIssue, ValidationResult
from .validation import validate_price_bars, validate_transactions

__all__ = [
    "CACHE_DATA_DIR",
    "DATA_DIR",
    "DB_DIR",
    "DUCKDB_PATH",
    "PROCESSED_DATA_DIR",
    "RAW_DATA_DIR",
    "SAMPLES_DATA_DIR",
    "SQLITE_PATH",
    "CorporateAction",
    "PriceBar",
    "Transaction",
    "ValidationIssue",
    "ValidationResult",
    "ensure_data_dirs",
    "validate_price_bars",
    "validate_transactions",
]
