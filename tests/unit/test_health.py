from fastapi.testclient import TestClient

from quotedesk.infrastructure.config import Settings
from quotedesk.infrastructure.main import create_app


def test_health(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings(database_url="postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk")
    app = create_app(settings)

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
