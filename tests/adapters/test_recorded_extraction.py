import socket
from decimal import Decimal

from quotedesk.adapters.outbound.models.recorded_extraction import RecordedEnricher, load_recording
from quotedesk.adapters.outbound.models.spark import SparkTurn
from quotedesk.infrastructure.config import get_settings
from quotedesk.infrastructure.demo import QuoteScript
from quotedesk.infrastructure.main import create_app

DATABASE_URL = "postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk"


def _env(monkeypatch, **values: str) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    for name in ("MODEL", "META_API_KEY", "META_BASE_URL", "SPARK_MODEL_ID"):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_tank_photo_reads_the_recorded_files(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("The recording must not open a socket.")

    monkeypatch.setattr(socket, "socket", refuse)
    result = load_recording("tank-on-base")
    assert result.summary == "A tank on a level base."
    assert result.objects == ("tank",)
    assert result.masks[0].label == "tank"
    assert result.masks[0].score == Decimal("0.91")
    assert result.blur is False
    assert result.darkness is False
    assert result.wrong_subject is False
    assert result.sam_error is False
    assert RecordedEnricher().for_image("any-photo") == result


def test_sam_error_fixture_is_a_failure(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("The recording must not open a socket.")

    monkeypatch.setattr(socket, "socket", refuse)
    result = load_recording("sam-error")
    assert result.sam_error is True
    assert result.masks == ()
    assert result.sam_sentence == "The segmenter did not return a result."


def test_install_uses_the_recorded_enricher(monkeypatch):
    _env(monkeypatch, MODEL="script")
    script_app = create_app(get_settings())
    assert isinstance(script_app.state.slot.model, QuoteScript)
    assert isinstance(script_app.state.turn.enricher, RecordedEnricher)

    _env(
        monkeypatch,
        MODEL="spark",
        META_API_KEY="test-key",
        SPARK_MODEL_ID="muse-spark-1.3-contributor",
    )
    spark_app = create_app(get_settings())
    assert isinstance(spark_app.state.slot.model, SparkTurn)
    assert isinstance(spark_app.state.turn.enricher, RecordedEnricher)
