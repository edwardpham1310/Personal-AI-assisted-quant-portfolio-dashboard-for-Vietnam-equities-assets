"""Application settings loaded from environment variables and config files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # SSI FastConnect
    ssi_consumer_id: str = ""
    ssi_consumer_secret: str = ""
    ssi_base_url: str = "https://fc-data.ssi.com.vn"

    # Storage
    data_dir: Path = Path("./data")
    database_url: str = "sqlite:///data/database/quant_vn_data.sqlite"
    duckdb_path: Path = Path("./data/database/quant_vn_data.duckdb")

    # Logging
    log_level: str = "INFO"

    @field_validator("data_dir", "duckdb_path", mode="before")
    @classmethod
    def to_path(cls, v: object) -> Path:
        return Path(str(v))

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def database_dir(self) -> Path:
        return self.data_dir / "database"

    def has_ssi_credentials(self) -> bool:
        return bool(self.ssi_consumer_id and self.ssi_consumer_secret)

    def require_ssi_credentials(self) -> None:
        if not self.has_ssi_credentials():
            raise EnvironmentError(
                "SSI credentials are not configured. "
                "Set SSI_CONSUMER_ID and SSI_CONSUMER_SECRET in your .env file. "
                "Copy .env.example to .env and fill in your credentials."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
