"""Typed application settings, loaded from the environment and `.env`."""

from __future__ import annotations

from functools import lru_cache
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

    # --- Email -------------------------------------------------------------
    # The address every email is sent from. The agent never chooses this:
    # a model that could pick its own From line could impersonate anyone
    # the SMTP server will relay for.
    email_from: str = ""
    email_from_name: str = ""
    # Safe by default. Nothing leaves the process until this is turned off
    # deliberately, so a first run (or a misconfigured one) cannot mail
    # real people by accident.
    email_dry_run: bool = True
    # A ceiling on recipients per send, so one bad instruction can't turn
    # into a mass mailing.
    email_max_recipients: int = Field(default=5, ge=1, le=50)
    # Optional allowlist, e.g. "example.com,team.example.com". Empty means
    # any domain is permitted.
    email_allowed_domains: str = ""

    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_timeout_s: float = Field(default=30.0, gt=0)

    # --- YouTube -----------------------------------------------------------
    # A Data API v3 key: https://console.cloud.google.com/apis/credentials
    # Without one the YouTube agent still appears, but says search is
    # unavailable rather than inventing links.
    youtube_api_key: SecretStr | None = None
    youtube_max_results: int = Field(default=5, ge=1, le=25)
    # Hard ceiling, whatever the model asks for.
    youtube_result_ceiling: int = Field(default=10, ge=1, le=50)
    youtube_timeout_s: float = Field(default=15.0, gt=0)

    # --- Agent loop budget ---------------------------------------------------
    max_steps: int = Field(default=8, ge=1, le=50)
    tool_timeout_s: float = Field(default=20.0, gt=0)
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
    def _upper(cls, value: str) -> str:
        return value.upper()

    @field_validator("openai_model")
    @classmethod
    def _known_model(cls, value: str) -> str:
        # Fail at startup on a typo'd OPENAI_MODEL rather than on the first
        # request, when it would surface as an opaque provider error.
        return resolve_model_id(value)

    @property
    def pricing_overrides(self) -> dict[str, ModelPricing]:
        """Per-model price corrections from `MODEL_PRICING_JSON` (empty by default)."""
        return parse_pricing_overrides(self.model_pricing_json)

    @property
    def allowed_email_domains(self) -> frozenset[str]:
        """Recipient domains the runtime will send to (empty = no restriction)."""
        return frozenset(
            domain.strip().lower()
            for domain in self.email_allowed_domains.split(",")
            if domain.strip()
        )

    @property
    def can_send_email(self) -> bool:
        """True when real delivery is both configured and switched on."""
        return bool(self.smtp_host and self.email_from) and not self.email_dry_run

    @property
    def can_search_youtube(self) -> bool:
        """True when a YouTube API key is available."""
        return self.youtube_api_key is not None

    @property
    def cors_origins(self) -> list[str]:
        """CORS origins as a list (comma-separated in the environment)."""
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton (cached; call `.cache_clear()` in tests)."""
    return Settings()
