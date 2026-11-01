import importlib
from pathlib import Path

import pytest

from quotedesk.infrastructure.config import SettingsError, get_settings
from quotedesk.infrastructure.main import create_app

REQUIRED = "DATABASE_URL is required."


def test_settings_read_from_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for name in (
        "MODEL",
        "META_API_KEY",
        "META_BASE_URL",
        "SPARK_MODEL_ID",
        "TENANT",
        "AGENT_PROVIDER",
        "IMAGE_PROVIDER",
        "BASETEN_API_KEY",
        "BASETEN_BASE_URL",
        "BASETEN_MODEL_ID",
        "BASETEN_IMAGE_MODEL_ID",
        "SAM_MODEL_ID",
        "CARPORT_PICTURE",
        "PICTURE_MODEL_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SettingsError) as missing:
        get_settings()
    assert str(missing.value) == REQUIRED

    with pytest.raises(SettingsError) as blank:
        monkeypatch.setenv("DATABASE_URL", "")
        get_settings()
    assert str(blank.value) == REQUIRED

    first = "postgresql://from-the-environment/only"
    monkeypatch.setenv("DATABASE_URL", first)
    with pytest.raises(SettingsError) as missing_key:
        get_settings()
    assert str(missing_key.value) == "META_API_KEY is required when MODEL is spark."
    monkeypatch.setenv("META_API_KEY", "test-key")
    monkeypatch.setenv("SPARK_MODEL_ID", "muse-spark-1.3")
    assert get_settings().database_url == first
    assert get_settings().model == "spark"
    assert get_settings().agent_provider == "meta"
    assert get_settings().image_provider == "meta"
    assert get_settings().sam_model_id == "sam-3.1"
    assert get_settings().picture_model_id == "muse-image-1.0"
    assert get_settings().carport_picture is False
    assert get_settings().tenant == "aquasure"
    monkeypatch.setenv("SAM_MODEL_ID", "sam-3.1-preview")
    assert get_settings().sam_model_id == "sam-3.1-preview"
    monkeypatch.setenv("PICTURE_MODEL_ID", "other-picture-model")
    assert get_settings().picture_model_id == "other-picture-model"
    monkeypatch.setenv("PICTURE_MODEL_ID", "")
    assert get_settings().picture_model_id == "muse-image-1.0"
    monkeypatch.setenv("SAM_MODEL_ID", "")
    monkeypatch.setenv("TENANT", "no-such-business")
    with pytest.raises(SettingsError) as unknown:
        get_settings()
    assert str(unknown.value) == "TENANT is aquasure or frameworks."
    monkeypatch.setenv("TENANT", "frameworks")
    assert get_settings().tenant == "frameworks"
    monkeypatch.setenv("TENANT", "aquasure")

    second = "postgresql://from-the-environment/changed"
    monkeypatch.setenv("DATABASE_URL", second)
    assert get_settings().database_url == second

    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SettingsError) as startup:
        create_app()
    assert str(startup.value) == REQUIRED


def test_carport_picture_is_off_until_switched_on(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://from-the-environment/only")
    monkeypatch.setenv("MODEL", "script")
    monkeypatch.delenv("CARPORT_PICTURE", raising=False)
    assert get_settings().carport_picture is False
    monkeypatch.setenv("CARPORT_PICTURE", "on")
    assert get_settings().carport_picture is True
    monkeypatch.setenv("CARPORT_PICTURE", "off")
    assert get_settings().carport_picture is False
    monkeypatch.setenv("CARPORT_PICTURE", "yes")
    with pytest.raises(SettingsError) as unknown:
        get_settings()
    assert str(unknown.value) == "CARPORT_PICTURE is on or off."
    root = Path(__file__).resolve().parents[2]
    for relative in (
        "quotedesk/application/use_cases/conversation/run_agent_turn.py",
        "quotedesk/application/use_cases/tools/get_quote.py",
        "quotedesk/domain/services/plan.py",
        "quotedesk/application/prompts.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "muse-image" not in text
        assert "carport_picture" not in text


def test_importing_the_entrypoint_does_not_build_the_app(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import quotedesk.infrastructure.main as main

    importlib.reload(main)
    assert callable(main.create_app)
