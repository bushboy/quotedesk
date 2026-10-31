"""The migration, the built-in cards, and the seeds describe the same prices."""

from pathlib import Path

from quotedesk.adapters.outbound.parsers.aquasure import load_rate_card
from quotedesk.infrastructure.demo import bundle_for, published_bundle

ROOT = Path(__file__).resolve().parents[3]


def test_the_built_in_cards_match_the_seeds():
    aqua = load_rate_card(ROOT / "seeds" / "aquasure.yaml")
    frames = load_rate_card(ROOT / "seeds" / "frameworks.yaml")
    assert published_bundle().rate_card == aqua
    assert bundle_for("frameworks").rate_card == frames
    assert aqua.site_visit_fee == next(item.unit_price for item in aqua.items if item.item_code == "SITE-VISIT")
    assert frames.site_visit_fee == next(item.unit_price for item in frames.items if item.item_code == "SITE-MEASURE")
    migration = (ROOT / "alembic" / "versions" / "20261118_rate_card_rows.py").read_text(encoding="utf-8")
    assert "load_rate_card" in migration
    assert "aquasure" in migration and "frameworks" in migration
