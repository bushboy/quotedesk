from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from quotedesk.adapters.outbound.persistence.rate_cards import RateCardTables
from quotedesk.domain.services.price import RateCard, RateCardItem
from quotedesk.domain.shared.money import Money
from quotedesk.infrastructure.db import engine
from quotedesk.adapters.outbound.persistence.stored_rate_cards import StoredRateCards

URL = "postgresql+psycopg://quotedesk:quotedesk@127.0.0.1:5432/quotedesk"
AQUASURE = UUID("11111111-1111-4111-8111-111111111111")
FRAMEWORKS = UUID("22222222-2222-4222-8222-222222222222")


@pytest.fixture
def database():
    try:
        with engine(URL).connect():
            pass
    except OperationalError:
        pytest.skip("PostgreSQL is not listening on 127.0.0.1:5432.")
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.downgrade(config, "20261029_tenant")
    command.upgrade(config, "head")
    return engine(URL)


def test_the_migration_seeds_each_business_card(database):
    with database.begin() as connection:
        aquasure = RateCardTables().get(connection, AQUASURE)
    with database.begin() as connection:
        frameworks = RateCardTables().get(connection, FRAMEWORKS)

    from pathlib import Path

    from quotedesk.adapters.outbound.parsers.aquasure import load_rate_card

    root = Path("seeds")
    assert aquasure == load_rate_card(root / "aquasure.yaml")
    assert frameworks == load_rate_card(root / "frameworks.yaml")
    assert aquasure.site_visit_fee == Money("750.00")
    assert frameworks.items[-1].item_code == "SITE-MEASURE"
    assert frameworks.items[-1].unit_price == frameworks.site_visit_fee


def test_a_saved_card_reads_back_in_order_and_only_for_its_tenant(database):
    card = RateCard(
        vat_inclusive=False,
        site_visit_fee=Money("500.00"),
        items=(
            RateCardItem(item_code="PUMP-STD", description="Standard pump", unit_price=Money("1800.00")),
            RateCardItem(item_code="TANK-5000", description="5000 L tank", unit_price=Money("4400.50")),
        ),
    )
    store = StoredRateCards(URL)

    assert store.save(AQUASURE, card) is True
    assert store.load(AQUASURE) == card
    with database.begin() as connection:
        connection.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(FRAMEWORKS)})
        codes = connection.execute(text("SELECT item_code FROM rate_card_item ORDER BY item_code")).scalars().all()
    from quotedesk.adapters.outbound.parsers.aquasure import load_rate_card

    expected = sorted(item.item_code for item in load_rate_card(Path("seeds/frameworks.yaml")).items)
    assert codes == expected


def test_applies_to_round_trips(database):
    with database.begin() as connection:
        seeded = RateCardTables().get(connection, AQUASURE)
    assert seeded is not None
    assert seeded.items[0].item_code == "TANK-1000"
    assert seeded.items[0].applies_to == "both"

    card = RateCard(
        vat_inclusive=True,
        site_visit_fee=Money("750.00"),
        items=(
            RateCardItem(
                item_code="TANK-5000",
                description="5000 L tank",
                unit_price=Money("4250.00"),
                role="product",
                applies_to="both",
            ),
            RateCardItem(
                item_code="STAND",
                description="Stand and base",
                unit_price=Money("900.00"),
                role="frame",
                applies_to="new",
            ),
        ),
    )
    with database.begin() as connection:
        RateCardTables().save(connection, AQUASURE, card)
    with database.begin() as connection:
        loaded = RateCardTables().get(connection, AQUASURE)
    assert loaded is not None
    assert [(item.item_code, item.role, item.applies_to) for item in loaded.items] == [
        ("TANK-5000", "product", "both"),
        ("STAND", "frame", "new"),
    ]


def test_a_closed_database_is_not_reachable():
    store = StoredRateCards("postgresql+psycopg://quotedesk:quotedesk@127.0.0.1:1/quotedesk")
    assert store.load(AQUASURE) is None
    assert store.save(AQUASURE, RateCard(vat_inclusive=True, site_visit_fee=Money("0"), items=())) is False
    assert store.reachable is False
