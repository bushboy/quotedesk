import importlib

import pytest

from quotedesk.infrastructure.config import Settings, SettingsError, get_settings
from quotedesk.infrastructure.main import create_app

REQUIRED = "DATABASE_URL is required."


def test_settings_read_from_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SettingsError) as missing:
        get_settings()
    assert str(missing.value) == REQUIRED

    with pytest.raises(SettingsError) as blank:
        monkeypatch.setenv("DATABASE_URL", "")
        get_settings()
    assert str(blank.value) == REQUIRED

    first = "postgresql://from-the-environment/only"
    monkeypatch.setenv("DATABASE_URL", first)
    assert get_settings().database_url == first

    second = "postgresql://from-the-environment/changed"
    monkeypatch.setenv("DATABASE_URL", second)
    assert get_settings().database_url == second

    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SettingsError) as startup:
        create_app()
    assert str(startup.value) == REQUIRED


def test_importing_the_entrypoint_does_not_build_the_app(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import quotedesk.infrastructure.main as main

    importlib.reload(main)
    assert callable(main.create_app)
