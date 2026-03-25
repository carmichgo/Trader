"""Configuration loader -- reads config.yaml + .env, validates with Pydantic Settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_project_root() -> Path:
    """Walk up from this file until we find pyproject.toml."""
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    return current


PROJECT_ROOT: Path = _find_project_root()


def _load_yaml_config() -> dict[str, Any]:
    """Load config.yaml from the project root (if it exists)."""
    config_path = PROJECT_ROOT / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


_yaml_cfg: dict[str, Any] = _load_yaml_config()


# ---------------------------------------------------------------------------
# Sub-configs
# ---------------------------------------------------------------------------


class DatabaseConfig(BaseSettings):
    """PostgreSQL / TimescaleDB connection settings."""

    model_config = SettingsConfigDict(
        env_prefix="DB_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(default="localhost")
    port: int = Field(default=5432)
    name: str = Field(default="trader")
    user: str = Field(default="trader")
    password: str = Field(default="trader")
    pool_size: int = Field(default=10)
    max_overflow: int = Field(default=20)
    echo: bool = Field(default=False)

    @property
    def url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @model_validator(mode="before")
    @classmethod
    def _merge_yaml(cls, values: dict[str, Any]) -> dict[str, Any]:
        yaml_db = _yaml_cfg.get("database", {})
        for k, v in yaml_db.items():
            values.setdefault(k, v)
        return values


class RedisConfig(BaseSettings):
    """Redis connection settings."""

    model_config = SettingsConfigDict(
        env_prefix="REDIS_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(default="localhost")
    port: int = Field(default=6379)
    db: int = Field(default=0)
    password: str | None = Field(default=None)

    @property
    def url(self) -> str:
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"

    @model_validator(mode="before")
    @classmethod
    def _merge_yaml(cls, values: dict[str, Any]) -> dict[str, Any]:
        yaml_redis = _yaml_cfg.get("redis", {})
        for k, v in yaml_redis.items():
            values.setdefault(k, v)
        return values


class AIConfig(BaseSettings):
    """AI / LLM provider settings."""

    model_config = SettingsConfigDict(
        env_prefix="AI_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")
    default_model: str = Field(default="claude-sonnet-4-20250514")
    strategist_model: str = Field(default="claude-sonnet-4-20250514")
    analyst_model: str = Field(default="claude-sonnet-4-20250514")
    screener_model: str = Field(default="claude-haiku-4-20250414")
    max_tokens: int = Field(default=4096)
    temperature: float = Field(default=0.2)
    daily_cost_limit_usd: float = Field(default=50.0)

    @model_validator(mode="before")
    @classmethod
    def _merge_yaml(cls, values: dict[str, Any]) -> dict[str, Any]:
        yaml_ai = _yaml_cfg.get("ai", {})
        for k, v in yaml_ai.items():
            values.setdefault(k, v)
        return values


class GoalConfig(BaseSettings):
    """Trading goal parameters."""

    model_config = SettingsConfigDict(
        env_prefix="GOAL_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    starting_capital: float = Field(default=1000.0)
    target_capital: float = Field(default=10000.0)
    time_horizon_days: int = Field(default=90)
    max_drawdown_pct: float = Field(default=0.15)
    rebalance_interval_hours: int = Field(default=6)

    @field_validator("max_drawdown_pct")
    @classmethod
    def _validate_drawdown(cls, v: float) -> float:
        if not 0 < v < 1:
            raise ValueError("max_drawdown_pct must be between 0 and 1")
        return v

    @model_validator(mode="before")
    @classmethod
    def _merge_yaml(cls, values: dict[str, Any]) -> dict[str, Any]:
        yaml_goal = _yaml_cfg.get("goal", {})
        for k, v in yaml_goal.items():
            values.setdefault(k, v)
        return values


class MarketConfig(BaseSettings):
    """Market / exchange connection settings."""

    model_config = SettingsConfigDict(
        env_prefix="MARKET_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    crypto_exchange: str = Field(default="binance")
    crypto_api_key: str = Field(default="")
    crypto_api_secret: str = Field(default="")
    crypto_sandbox: bool = Field(default=True)

    alpaca_api_key: str = Field(default="")
    alpaca_api_secret: str = Field(default="")
    alpaca_base_url: str = Field(default="https://paper-api.alpaca.markets")

    polymarket_api_key: str = Field(default="")
    polymarket_api_secret: str = Field(default="")
    polymarket_funder_address: str = Field(default="")

    enabled_markets: list[str] = Field(default_factory=lambda: ["crypto", "stocks", "polymarket"])

    @model_validator(mode="before")
    @classmethod
    def _merge_yaml(cls, values: dict[str, Any]) -> dict[str, Any]:
        yaml_market = _yaml_cfg.get("market", {})
        for k, v in yaml_market.items():
            values.setdefault(k, v)
        return values


# ---------------------------------------------------------------------------
# Top-level system config
# ---------------------------------------------------------------------------


class SystemConfig(BaseSettings):
    """Root configuration aggregating all sub-configs.

    Usage::

        from packages.core.config import SystemConfig

        cfg = SystemConfig()
        print(cfg.database.url)
        print(cfg.ai.default_model)
    """

    model_config = SettingsConfigDict(
        env_prefix="SYSTEM_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = Field(default="development")
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    goal: GoalConfig = Field(default_factory=GoalConfig)
    market: MarketConfig = Field(default_factory=MarketConfig)

    @model_validator(mode="before")
    @classmethod
    def _merge_yaml(cls, values: dict[str, Any]) -> dict[str, Any]:
        yaml_system = _yaml_cfg.get("system", {})
        for k, v in yaml_system.items():
            values.setdefault(k, v)
        return values
