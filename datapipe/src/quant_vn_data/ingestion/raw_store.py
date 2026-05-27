"""Write raw provider responses to disk before any normalization."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SENSITIVE_PARAM_KEYS = frozenset({
    "consumerID", "consumerSecret", "consumer_id", "consumer_secret",
    "apiKey", "api_key", "token", "password", "secret",
})

_SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


def _safe_component(value: str) -> str:
    """Raise if a path component contains directory traversal characters."""
    if not _SAFE_COMPONENT_RE.match(value):
        raise ValueError(
            f"Unsafe path component rejected: {value!r}. "
            "Only alphanumeric, dash, underscore, and dot are allowed."
        )
    return value


class RawStore:
    """Persist raw provider responses in a content-addressed directory tree.

    Path format:
        {raw_dir}/{provider}/{dataset}/{symbol}/{yyyy}/{mm}/{dd}/raw.{ext}
    """

    def __init__(self, raw_dir: str | Path) -> None:
        self.raw_dir = Path(raw_dir)

    def store(
        self,
        provider: str,
        dataset: str,
        symbol: str,
        data: Any,
        ext: str = "json",
        request_params: dict[str, Any] | None = None,
        source_url: str | None = None,
        as_of: date | None = None,
    ) -> Path | None:
        """Persist raw data to disk.

        Returns the path written, or None if skipped (unchanged hash).
        """
        today = as_of or datetime.now(timezone.utc).date()
        dir_path = (
            self.raw_dir
            / _safe_component(provider)
            / _safe_component(dataset)
            / _safe_component(symbol)
            / str(today.year)
            / f"{today.month:02d}"
            / f"{today.day:02d}"
        )
        dir_path.mkdir(parents=True, exist_ok=True)

        raw_bytes = _serialize(data, ext)
        content_hash = hashlib.sha256(raw_bytes).hexdigest()

        raw_path = dir_path / f"raw.{ext}"
        meta_path = dir_path / "meta.json"

        # Skip if hash unchanged
        existing_meta = _read_meta(meta_path)
        if existing_meta and existing_meta.get("response_hash") == content_hash:
            logger.debug("RawStore: unchanged hash for %s/%s/%s — skipping", provider, dataset, symbol)
            return None

        raw_path.write_bytes(raw_bytes)

        safe_params = {
            k: "***" if k in _SENSITIVE_PARAM_KEYS else v
            for k, v in (request_params or {}).items()
        }
        meta: dict[str, Any] = {
            "provider": provider,
            "dataset": dataset,
            "symbol": symbol,
            "request_params": safe_params,
            "ingestion_timestamp": datetime.now(timezone.utc).isoformat(),
            "response_hash": content_hash,
            "ext": ext,
        }
        if source_url:
            meta["source_url"] = source_url

        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        logger.debug("RawStore: wrote %s", raw_path)
        return raw_path

    def read(self, provider: str, dataset: str, symbol: str, as_of: date | None = None) -> bytes | None:
        today = as_of or datetime.now(timezone.utc).date()
        dir_path = (
            self.raw_dir
            / _safe_component(provider)
            / _safe_component(dataset)
            / _safe_component(symbol)
            / str(today.year)
            / f"{today.month:02d}"
            / f"{today.day:02d}"
        )
        for ext in ("json", "html", "csv", "txt"):
            p = dir_path / f"raw.{ext}"
            if p.exists():
                return p.read_bytes()
        return None


def _serialize(data: Any, ext: str) -> bytes:
    if ext == "json":
        if isinstance(data, (dict, list)):
            return json.dumps(data, ensure_ascii=False, default=str).encode()
        return str(data).encode()
    if isinstance(data, bytes):
        return data
    return str(data).encode()


def _read_meta(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        logger.warning("RawStore: meta.json unreadable at %s — treating as missing (%s)", path, exc)
        return None
