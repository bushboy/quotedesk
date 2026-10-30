"""One process routes each WhatsApp number to its tenant."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from quotedesk.adapters.outbound.persistence.records import bind_tenant
from quotedesk.application.dto.agent import ModelReply
from quotedesk.infrastructure.config import Settings
from quotedesk.infrastructure.db import engine
from quotedesk.infrastructure.main import create_app

LIVE = "postgresql+psycopg://quotedesk:quotedesk@127.0.0.1:5432/quotedesk"
DEAD = "postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk"
AQUA = UUID("11111111-1111-4111-8111-111111111111")
FRAME = UUID("22222222-2222-4222-8222-222222222222")
AQUA_PHONE = "PHONE-AQUA"
FRAME_PHONE = "PHONE-FRAME"
AQUA_SENDER = "15558880001"
FRAME_SENDER = "15558880002"


class Quiet:
    def complete(self, prompt):
        return ModelReply(text="Noted.")


def test_infrastructure_contains_no_postgres_repository():
    from pathlib import Path

    root = Path("quotedesk/infrastructure")
    names = {path.name for path in root.glob("*.py")}
    assert names.isdisjoint({"stored.py", "commercial.py", "tenants.py", "rate_cards.py"})
    for path in root.glob("*.py"):
        assert "class Stored" not in path.read_text(encoding="utf-8")


def test_an_unknown_number_is_not_stored(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(Settings(database_url=DEAD, tenant="aquasure", model="script", store="memory"))
    app.state.slot.model = Quiet()
    app.state.tenants_by_phone = {"PHONE-1": app.state.tenant_id}
    with TestClient(app) as client:
        assert client.post("/whatsapp/webhook", json=_payload("GONE", "15558880009", "nobody")).status_code == 200
    assert app.state.conversations.heard(app.state.tenant_id) == ()


def test_two_phone_numbers_stay_behind_row_level_security():
    try:
        with engine(LIVE).connect():
            pass
    except OperationalError:
        pytest.skip("PostgreSQL is not listening on 127.0.0.1:5432.")
    app = create_app(Settings(database_url=LIVE, tenant="frameworks", model="script", store="postgres"))
    app.state.slot.model = Quiet()
    app.state.tenants_by_phone = {AQUA_PHONE: AQUA, FRAME_PHONE: FRAME}
    try:
        with TestClient(app) as client:
            assert client.post("/whatsapp/webhook", json=_payload(AQUA_PHONE, AQUA_SENDER, "aqua-only")).status_code == 200
            assert client.post("/whatsapp/webhook", json=_payload(FRAME_PHONE, FRAME_SENDER, "frame-only")).status_code == 200
        aqua = _bodies(AQUA)
        frame = _bodies(FRAME)
        assert "aqua-only" in aqua
        assert "frame-only" not in aqua
        assert "frame-only" in frame
        assert "aqua-only" not in frame
    finally:
        _forget(AQUA_SENDER)
        _forget(FRAME_SENDER)


def _payload(phone: str, wa_id: str, body: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone, "display_phone_number": "15550001111"},
                            "contacts": [{"wa_id": wa_id}],
                            "messages": [
                                {
                                    "from": wa_id,
                                    "id": f"wamid.{phone}.{wa_id}",
                                    "timestamp": "1761840000",
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    }


def _bodies(tenant: UUID) -> set[str]:
    with engine(LIVE).connect() as connection:
        bind_tenant(connection, tenant)
        rows = connection.execute(text("SELECT body FROM conversation_event")).scalars()
        return {row for row in rows if row}


def _forget(wa_id: str) -> None:
    for tenant in (AQUA, FRAME):
        with engine(LIVE).begin() as connection:
            bind_tenant(connection, tenant)
            ids = connection.execute(
                text("SELECT conversation_id FROM sender_bind WHERE wa_id = :wa_id"),
                {"wa_id": wa_id},
            ).scalars()
            for conversation_id in ids:
                for table in (
                    "conversation_event",
                    "inbound_message",
                    "assistant_reply",
                    "case_fact",
                    "case_file",
                    "quote",
                    "handover",
                    "inspection",
                ):
                    connection.execute(
                        text(f"DELETE FROM {table} WHERE conversation_id = :conversation_id"),
                        {"conversation_id": conversation_id},
                    )
                connection.execute(
                    text("DELETE FROM conversation WHERE conversation_id = :conversation_id"),
                    {"conversation_id": conversation_id},
                )
            connection.execute(text("DELETE FROM sender_bind WHERE wa_id = :wa_id"), {"wa_id": wa_id})
