"""Tests for RawStore — path safety, hash dedup, meta.json, secret redaction."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from quant_vn_data.ingestion.raw_store import RawStore, _safe_component


def test_store_and_read(tmp_path):
    store = RawStore(tmp_path)
    payload = {"rows": [{"symbol": "FPT", "close": 86500}]}
    path = store.store("ssi", "ohlcv", "FPT", payload, as_of=date(2024, 1, 2))
    assert path is not None
    assert path.exists()
    raw = store.read("ssi", "ohlcv", "FPT", as_of=date(2024, 1, 2))
    assert raw is not None
    assert b"FPT" in raw


def test_unchanged_hash_returns_none(tmp_path):
    store = RawStore(tmp_path)
    payload = {"rows": [{"symbol": "FPT"}]}
    p1 = store.store("ssi", "ohlcv", "FPT", payload, as_of=date(2024, 1, 2))
    assert p1 is not None
    p2 = store.store("ssi", "ohlcv", "FPT", payload, as_of=date(2024, 1, 2))
    assert p2 is None  # unchanged hash → skip


def test_changed_data_writes_again(tmp_path):
    store = RawStore(tmp_path)
    p1 = store.store("ssi", "ohlcv", "FPT", {"v": 1}, as_of=date(2024, 1, 2))
    p2 = store.store("ssi", "ohlcv", "FPT", {"v": 2}, as_of=date(2024, 1, 2))
    assert p1 is not None
    assert p2 is not None  # data changed → new write


def test_sensitive_params_redacted_in_meta(tmp_path):
    store = RawStore(tmp_path)
    store.store(
        "ssi", "ohlcv", "FPT", {"rows": []},
        request_params={"consumerID": "secret123", "pageIndex": 1},
        as_of=date(2024, 1, 2),
    )
    meta_path = tmp_path / "ssi" / "ohlcv" / "FPT" / "2024" / "01" / "02" / "meta.json"
    meta = json.loads(meta_path.read_text())
    assert meta["request_params"]["consumerID"] == "***"
    assert meta["request_params"]["pageIndex"] == 1


def test_path_traversal_rejected():
    with pytest.raises(ValueError, match="Unsafe path component"):
        _safe_component("../etc/passwd")


def test_path_traversal_with_slash_rejected():
    with pytest.raises(ValueError, match="Unsafe path component"):
        _safe_component("ssi/../../secret")


def test_safe_symbols_accepted():
    assert _safe_component("FPT") == "FPT"
    assert _safe_component("VN30-Index") == "VN30-Index"
    assert _safe_component("ohlcv_daily") == "ohlcv_daily"


def test_meta_json_written(tmp_path):
    store = RawStore(tmp_path)
    store.store("csv", "ohlcv", "VCB", [1, 2, 3], as_of=date(2024, 3, 1))
    meta_path = tmp_path / "csv" / "ohlcv" / "VCB" / "2024" / "03" / "01" / "meta.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta["provider"] == "csv"
    assert meta["symbol"] == "VCB"
    assert "response_hash" in meta
    assert "ingestion_timestamp" in meta


def test_read_missing_returns_none(tmp_path):
    store = RawStore(tmp_path)
    result = store.read("ssi", "ohlcv", "MISSING", as_of=date(2024, 1, 1))
    assert result is None
