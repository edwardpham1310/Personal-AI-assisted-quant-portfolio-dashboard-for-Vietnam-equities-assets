"""Tests for corporate action normalization and validation."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from quant_vn_data.normalization.normalize_corporate_actions import normalize_corporate_actions
from quant_vn_data.validation.corporate_action_checks import validate_corporate_actions


def _ca(**kwargs):
    defaults = {
        "symbol": "FPT",
        "announcement_date": "2024-01-10",
        "record_date": "2024-02-15",
        "action_type": "cash_dividend",
        "cash_dividend": 2000.0,
        "source": "vsdc",
    }
    defaults.update(kwargs)
    return defaults


def test_cash_dividend_parsed():
    df = pd.DataFrame([_ca()])
    result = normalize_corporate_actions(df, source="vsdc")
    assert not result.empty
    assert result["action_type"].iloc[0] == "CASH_DIVIDEND"


def test_stock_dividend_parsed():
    df = pd.DataFrame([_ca(action_type="stock_dividend", stock_dividend_ratio=0.1)])
    result = normalize_corporate_actions(df, source="vsdc")
    assert result["action_type"].iloc[0] == "STOCK_DIVIDEND"


def test_unparsed_stored_safely():
    df = pd.DataFrame([{
        "symbol": "FPT",
        "action_type": "unknown_special_event",
        "raw_text": "Some corporate event text",
        "parse_status": "RAW_ONLY",
        "source": "vsdc",
    }])
    result = normalize_corporate_actions(df, source="vsdc")
    assert not result.empty
    assert result["raw_text"].iloc[0] is not None


def test_future_announcement_separation():
    """Corporate action announcement and ex_date fields must be separate — no merging."""
    df = pd.DataFrame([_ca(
        announcement_date="2024-01-10",
        ex_date="2024-02-20",
        record_date="2024-02-15",
        payment_date="2024-03-01",
    )])
    result = normalize_corporate_actions(df, source="vsdc")
    assert result["announcement_date"].iloc[0] == date(2024, 1, 10)
    assert result["ex_date"].iloc[0] == date(2024, 2, 20)
    assert result["record_date"].iloc[0] == date(2024, 2, 15)
    assert result["payment_date"].iloc[0] == date(2024, 3, 1)


def test_validate_record_before_announcement():
    df = pd.DataFrame([_ca(
        announcement_date="2024-02-15",
        record_date="2024-01-10",  # record before announcement — suspicious
    )])
    normalized = normalize_corporate_actions(df, source="vsdc")
    issues = validate_corporate_actions(normalized)
    types = [i.issue_type for i in issues]
    assert "CA_RECORD_BEFORE_ANNOUNCEMENT" in types


def test_validate_no_symbol():
    df = pd.DataFrame([_ca(symbol=None)])
    normalized = normalize_corporate_actions(df, source="vsdc")
    issues = validate_corporate_actions(normalized)
    types = [i.issue_type for i in issues]
    assert "CA_MISSING_SYMBOL" in types


def test_validate_suspicious_dividend():
    df = pd.DataFrame([_ca(cash_dividend=200_000.0)])  # 200,000 VND/share — suspicious
    normalized = normalize_corporate_actions(df, source="vsdc")
    issues = validate_corporate_actions(normalized)
    types = [i.issue_type for i in issues]
    assert "CA_SUSPICIOUS_DIVIDEND" in types


def test_validate_clean_row_no_issues():
    df = pd.DataFrame([_ca()])
    normalized = normalize_corporate_actions(df, source="vsdc")
    issues = validate_corporate_actions(normalized)
    high_issues = [i for i in issues if i.severity in ("CRITICAL", "HIGH")]
    assert not high_issues
