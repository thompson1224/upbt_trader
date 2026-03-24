from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Literal


class Settings(BaseSettings):
    # Application
    app_env: Literal["local", "staging", "prod"] = "local"
    app_name: str = "upbit-ai-trader"
    log_level: str = "INFO"

    # Database
    database_url: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret: str
    jwt_alg: str = "HS256"
    jwt_expire_min: int = 1440

    # Upbit API
    upbit_access_key: str = ""
    upbit_secret_key: str = ""

    # Groq API (무료 14,400 req/day)
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"

    # Risk Management
    risk_max_daily_loss_pct: float = 0.03
    risk_max_position_pct: float = 0.10
    risk_max_single_trade_pct: float = 0.01
    risk_default_stop_loss_pct: float = 0.03
    risk_default_take_profit_pct: float = 0.06

    # WebSocket
    ws_reconnect_min_sec: float = 1.0
    ws_reconnect_max_sec: float = 30.0
    ws_ping_interval_sec: float = 60.0

    # Backtesting
    backtest_default_fee_bps: float = 5.0
    backtest_default_slippage_bps: float = 3.0

    # Encryption
    encryption_key: str = ""

    @field_validator("database_url")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        if not v:
            raise ValueError("DATABASE_URL is required")
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
