from __future__ import annotations

from agent_runtime.config import Settings


def test_defaults_are_sane() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.openai_model == "gpt-4o"
    assert settings.max_steps >= 1
    assert settings.openai_api_key is None
    assert settings.pricing_overrides == {}


def test_email_is_dry_run_until_deliberately_configured() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    # Safe by default: no sender, no SMTP host, dry run on.
    assert settings.email_dry_run is True
    assert settings.can_send_email is False

    # Turning off dry run is not enough on its own.
    half = Settings(_env_file=None, email_dry_run=False)  # type: ignore[call-arg]
    assert half.can_send_email is False

    live = Settings(  # type: ignore[call-arg]
        _env_file=None,
        email_dry_run=False,
        email_from="bot@example.com",
        smtp_host="smtp.example.com",
    )
    assert live.can_send_email is True


def test_allowed_email_domains_are_split_and_lowercased() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, email_allowed_domains="Example.com, TEAM.example.org ,"
    )
    assert settings.allowed_email_domains == frozenset({"example.com", "team.example.org"})
    assert Settings(_env_file=None).allowed_email_domains == frozenset()  # type: ignore[call-arg]


def test_smtp_password_is_secret() -> None:
    settings = Settings(_env_file=None, smtp_password="hunter2")  # type: ignore[call-arg]
    assert "hunter2" not in repr(settings.smtp_password)
    assert settings.smtp_password is not None
    assert settings.smtp_password.get_secret_value() == "hunter2"


def test_cors_origins_splits_and_strips() -> None:
    settings = Settings(_env_file=None, cors_allow_origins="https://a.com, https://b.com")  # type: ignore[call-arg]
    assert settings.cors_origins == ["https://a.com", "https://b.com"]


def test_api_key_is_secret_and_not_in_repr() -> None:
    settings = Settings(_env_file=None, api_key="super-secret")  # type: ignore[call-arg]
    assert "super-secret" not in repr(settings.api_key)
    assert settings.api_key.get_secret_value() == "super-secret"
