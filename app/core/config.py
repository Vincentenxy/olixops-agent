"""Validated application configuration loaded from the environment."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OLIXOPS_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    mode: Literal["debug", "release"] = "debug"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    docs_enabled: bool = False
