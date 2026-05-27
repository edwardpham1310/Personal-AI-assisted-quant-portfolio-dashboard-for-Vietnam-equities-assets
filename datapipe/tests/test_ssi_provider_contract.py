"""SSI provider contract tests — tests run without real credentials using stubs."""

from __future__ import annotations

import pytest

from quant_vn_data.providers.base import ProviderError
from quant_vn_data.providers.ssi_fastconnect import SSIFastConnectProvider


def test_missing_credentials_raises():
    with pytest.raises(ProviderError, match="credentials"):
        SSIFastConnectProvider(consumer_id="", consumer_secret="")


def test_provider_name():
    with pytest.raises(ProviderError):
        p = SSIFastConnectProvider(consumer_id="", consumer_secret="")
    # Name is a class attribute, can be checked without instantiation
    assert SSIFastConnectProvider.name == "ssi"


def test_date_format():
    from quant_vn_data.providers.ssi_fastconnect import _fmt_date
    assert _fmt_date("2024-01-15") == "15/01/2024"
    assert _fmt_date("2024-12-31") == "31/12/2024"
