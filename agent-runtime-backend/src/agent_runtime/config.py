"""Typed application settings, loaded from the environment and `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_runtime.models import (
    DEFAULT_MODEL_ID,
    ModelPricing,
    parse_pricing_overrides,
    resolve_model_id,
)

Environment = Literal["local", "dev", "staging", "prod"]

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class Settings(BaseSettings):
    """All runtime configuration in one place.

    Values are read from process environment first, then `.env`. Anything
    security-sensitive is wrapped in `SecretStr` so it never leaks into logs
    or error messages by accident.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Identity ------------------------------------------------------------
    app_name: str = "agent-runtime"
    environment: Environment = "local"

    # --- Model ---------------------------------------------------------------
    openai_api_key: SecretStr | None = None
    # The default model; callers may pick any other id from the catalog
    # per request (see `agent_runtime.models.MODEL_CATALOG`).
    openai_model: str = DEFAULT_MODEL_ID
    # Optional per-1M-token price corrections, as JSON. Provider prices move;
    # this is the escape hatch that doesn't need a code change.
    model_pricing_json: str | None = None
    model_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    model_max_output_tokens: int = Field(default=2048, ge=64, le=32_768)
    model_timeout_s: float = Field(default=60.0, gt=0)
    model_max_retries: int = Field(default=2, ge=0, le=5)

    # --- Workspace ---------------------------------------------------------
    # The only directory the agent's file tools can see. Paths that resolve
    # outside it (absolute paths, `..`, symlinks) are refused.
    workspace_dir: Path = Path("data/workspace")
    # When true, the agent gets no tool that creates or changes files.
    workspace_read_only: bool = False
    # Largest file the agent may read, or a client may upload.
    max_file_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    # Most characters of a file handed to the model per read_file call;
    # longer files are paged and the model is told how to continue.
    read_max_chars: int = Field(default=40_000, ge=1_000, le=500_000)
    # Images are scaled to fit this many pixels on their longest side.
    image_max_dimension: int = Field(default=2048, ge=256, le=8192)

    # --- Agent loop budget ---------------------------------------------------
    max_steps: int = Field(default=8, ge=1, le=50)
    tool_timeout_s: float = Field(default=60.0, gt=0)
    run_timeout_s: float = Field(default=180.0, gt=0)
    max_parallel_tool_calls: int = Field(default=4, ge=1, le=16)
    stream_tokens: bool = True

    # --- Sessions ------------------------------------------------------------
    session_ttl_s: float = Field(default=3600.0, gt=0)
    session_max_messages: int = Field(default=40, ge=2, le=500)

    # --- Server --------------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    reload: bool = False
    log_level: str = "INFO"
    log_json: bool = False
    cors_allow_origins: str = "*"

    # --- Optional inbound auth ----------------------------------------------
    api_key: SecretStr | None = None

    @field_validator("log_level")
    @classmethod
    def _log_level(cls, value: str) -> str:
        """Accept any case for LOG_LEVEL, but only names `logging` knows."""
        level = value.upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {', '.join(_LOG_LEVELS)}")
        return level

    @field_validator("openai_model")
    @classmethod
    def _known_model(cls, value: str) -> str:
        """Reject an OPENAI_MODEL outside the catalog."""
        # Fail at startup on a typo'd OPENAI_MODEL rather than on the first
        # request, when it would surface as an opaque provider error.
        return resolve_model_id(value)

    @property
    def pricing_overrides(self) -> dict[str, ModelPricing]:
        """Per-model price corrections from `MODEL_PRICING_JSON` (empty by default)."""
        return parse_pricing_overrides(self.model_pricing_json)

    @property
    def cors_origins(self) -> list[str]:
        """CORS origins as a list (comma-separated in the environment)."""
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def is_prod(self) -> bool:
        """True in production, where error details are withheld from clients."""
        return self.environment == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton (cached; call `.cache_clear()` in tests)."""
    return Settings()
