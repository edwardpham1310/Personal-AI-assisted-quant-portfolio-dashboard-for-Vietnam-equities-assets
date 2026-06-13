"""Regression lock: this product is recommend-only.

Fails loudly if a future change re-enables order placement or flips an
execution flag's default. Pure guard — no network, no provider.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from core.config import Settings


def test_order_endpoints_return_501(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    for path in ("/trading/new-order", "/trading/submit-order", "/trading/cancel-order"):
        r = client.post(path, headers=headers, json={})
        assert r.status_code == 501, f"{path} must be 501 (recommend-only), got {r.status_code}"


def test_execution_flags_default_off() -> None:
    f = Settings.model_fields
    # Every order/live/auto-trade execution switch defaults OFF.
    for name in (
        "ssi_trading_order_placement_enabled",
        "trading_live_order_enabled",
        "auto_trade_live_enabled",
        "auto_trade_order_placement_enabled",
    ):
        assert f[name].default is False, f"{name} must default False"
    # And the safety toggles default ON / dry-run.
    assert f["ssi_trading_read_only"].default is True
    assert f["trading_order_placement_dry_run"].default is True
    assert f["auto_trade_dry_run"].default is True
