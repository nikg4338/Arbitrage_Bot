from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Cross-Exchange Mispricing Detector"
    env: str = "dev"
    log_level: str = "INFO"

    database_url: str = "sqlite:///./mispricing.db"

    poly_gamma_base_url: str = "https://gamma-api.polymarket.com"
    poly_clob_base_url: str = "https://clob.polymarket.com"
    poly_clob_ws_url: str = "wss://clob.polymarket.com/ws"
    poly_api_key: str | None = None
    poly_private_key: str | None = None
    poly_passphrase: str | None = None

    kalshi_rest_base_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    kalshi_ws_url: str = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    kalshi_key_id: str | None = None
    kalshi_private_key_path: str | None = None

    min_edge: float = 0.008
    slippage_k: float = 0.20
    max_notional_per_event: float = 250.0
    depth_multiplier: float = 1.5
    min_seconds_to_start: int = 300

    enable_soccer: bool = True
    enable_nba: bool = True

    fee_poly_bps: float = 40.0
    fee_kalshi_bps: float = 35.0

    discovery_interval_sec: int = 180
    signal_interval_sec: int = 2
    ws_broadcast_interval_sec: float = 1.0

    market_discovery_limit: int = 500
    request_timeout_sec: float = 15.0

    overrides_path: Path = Path("./overrides.yml")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
