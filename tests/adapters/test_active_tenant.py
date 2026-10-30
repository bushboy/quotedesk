from uuid import UUID

from fastapi.testclient import TestClient

from quotedesk.application.use_cases.conversation.run_agent_turn import task_for
from quotedesk.infrastructure.config import Settings
from quotedesk.infrastructure.main import create_app

_URL = "postgresql://quotedesk:quotedesk@127.0.0.1:1/quotedesk"
_AQUASURE = UUID("11111111-1111-4111-8111-111111111111")
_FRAMEWORKS = UUID("22222222-2222-4222-8222-222222222222")


def test_the_process_starts_as_one_business(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    aqua = create_app(Settings(database_url=_URL, tenant="aquasure"))
    works = create_app(Settings(database_url=_URL, tenant="frameworks"))
    assert aqua.state.tenant_id == _AQUASURE
    assert works.state.tenant_id == _FRAMEWORKS
    assert aqua.state.tenant.display_name == "AquaSure"
    assert works.state.tenant.display_name == "FrameWorks"
    assert "AquaSure" in TestClient(aqua).get("/chat").text
    assert "FrameWorks" in TestClient(works).get("/chat").text
    assert aqua.state.policies.published(_AQUASURE).policy.version.value == "water-policy-v1.0"
    assert works.state.policies.published(_FRAMEWORKS).policy.version.value == "fab-policy-v1.0"
    assert aqua.state.turn._business.name == "AquaSure"
    assert works.state.turn._business.about.startswith("FrameWorks")
    assert "tank size" in task_for(aqua.state.turn._business)
    assert "tank" not in task_for(works.state.turn._business).casefold()
