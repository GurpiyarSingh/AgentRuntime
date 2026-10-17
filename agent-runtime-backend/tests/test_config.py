from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime.config import Settings


def test_defaults_are_sane() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.openai_model == "gpt-4o"
    assert settings.max_steps >= 1
    assert settings.openai_api_key is None
    assert settings.pricing_overrides == {}


def test_workspace_defaults_allow_writes_inside_data_dir() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.workspace_dir == Path("data/workspace")
    assert settings.workspace_read_only is False
    assert settings.max_file_bytes > 1024 * 1024


def test_workspace_settings_read_from_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("WORKSPACE_DIR", "/srv/agent")
    monkeypatch.setenv("WORKSPACE_READ_ONLY", "true")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.workspace_dir == Path("/srv/agent")
    assert settings.workspace_read_only is True


def test_cors_origins_splits_and_strips() -> None:
    settings = Settings(_env_file=None, cors_allow_origins="https://a.com, https://b.com")  # type: ignore[call-arg]
    assert settings.cors_origins == ["https://a.com", "https://b.com"]


def test_api_key_is_secret_and_not_in_repr() -> None:
    settings = Settings(_env_file=None, api_key="super-secret")  # type: ignore[call-arg]
    assert "super-secret" not in repr(settings.api_key)
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == "super-secret"


def test_log_level_is_normalised_and_validated() -> None:
    assert Settings(_env_file=None, log_level="debug").log_level == "DEBUG"  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        Settings(_env_file=None, log_level="verbose")  # type: ignore[call-arg]


def test_blank_database_url_means_no_database() -> None:
    settings = Settings(_env_file=None, database_url="  ")  # type: ignore[call-arg]
    assert settings.database_url is None
