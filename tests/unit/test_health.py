from fastapi.testclient import TestClient

from quotedesk.infrastructure.config import Settings
from quotedesk.infrastructure.main import create_app

_DOWN = "postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk"


def test_health_reports_an_explicit_memory_store(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(Settings(database_url=_DOWN, store="memory"))

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "store": "memory"}


def test_health_is_unavailable_when_postgres_is_down(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(Settings(database_url=_DOWN))

    response = TestClient(app).get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "store": "down"}
