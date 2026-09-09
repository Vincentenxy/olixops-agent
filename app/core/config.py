"""Validated application configuration loaded from the environment."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OLIXOPS_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    mode: Literal["debug", "release"] = "debug"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    docs_enabled: bool = False
    database_url: SecretStr = SecretStr("postgresql+psycopg://olixops@127.0.0.1:15432/olixops")
    database_timeout_seconds: float = Field(default=3, gt=0, le=30)
    redis_url: SecretStr | None = None
    pulumi_cli: str = "pulumi"
    jwt_private_key_path: Path = Path("runtime/keys/jwt-private.pem")
    jwt_public_key_path: Path = Path("runtime/keys/jwt-public.pem")
    jwt_public_key: SecretStr | None = None
    jwt_issuer: str = "olixops-agent"
    jwt_audience: str = "olixops-agent-web"
    access_token_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_token_seconds: int = Field(default=604800, ge=300, le=2592000)
    refresh_cookie_secure: bool = False
    browser_origins: list[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5175",
        "http://localhost:5175",
    ]
    login_failure_limit: int = Field(default=5, ge=2, le=20)
    login_lock_seconds: int = Field(default=30, ge=1, le=600)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith(
            ("postgresql+psycopg://", "sqlite+aiosqlite://")
        ):
            raise ValueError("Database must use PostgreSQL psycopg or SQLite for tests")
        return value

    @field_validator("browser_origins")
    @classmethod
    def validate_origins(cls, value: list[str]) -> list[str]:
        from urllib.parse import urlsplit

        for origin in value:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
            ):
                raise ValueError("Browser origins must be exact HTTP(S) origins")
        return value
