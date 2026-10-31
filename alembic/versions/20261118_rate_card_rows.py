"""Job type and condition on each rate-card row, and the wider demo cards.

Revision ID: 20261118_rate_card_rows
Revises: 20261117_quote_included

An empty job_types list means every job. An empty when means the row always
applies. The inserted rows are the same cards as seeds/aquasure.yaml and
seeds/frameworks.yaml.
"""

from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "20261118_rate_card_rows"
down_revision = "20261117_quote_included"
branch_labels = None
depends_on = None

_TENANTS = (
    ("11111111-1111-4111-8111-111111111111", "aquasure"),
    ("22222222-2222-4222-8222-222222222222", "frameworks"),
)


def upgrade() -> None:
    op.execute("ALTER TABLE rate_card_item ADD COLUMN job_types text NOT NULL DEFAULT ''")
    op.execute('ALTER TABLE rate_card_item ADD COLUMN "when" text NOT NULL DEFAULT \'\'')
    from quotedesk.adapters.outbound.parsers.aquasure import load_rate_card
    import json

    root = Path(__file__).resolve().parents[2] / "seeds"
    bind = op.get_bind()
    for tenant_id, slug in _TENANTS:
        card = load_rate_card(root / f"{slug}.yaml")
        bind.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )
        bind.execute(text("DELETE FROM rate_card_item WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        bind.execute(
            text("UPDATE rate_card SET site_visit_fee = :fee WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id, "fee": card.site_visit_fee.amount},
        )
        for position, item in enumerate(card.items):
            bind.execute(
                text(
                    """
                    INSERT INTO rate_card_item (
                        tenant_id, item_code, description, unit_price, position, unit, role, applies_to,
                        job_types, "when"
                    )
                    VALUES (
                        :tenant_id, :item_code, :description, :unit_price, :position, :unit, :role, :applies_to,
                        :job_types, :when
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "item_code": item.item_code,
                    "description": item.description,
                    "unit_price": item.unit_price.amount,
                    "position": position,
                    "unit": item.unit,
                    "role": item.role,
                    "applies_to": item.applies_to,
                    "job_types": ",".join(item.job_types),
                    "when": ""
                    if item.when is None
                    else json.dumps(item.when.model_dump(mode="json"), separators=(",", ":")),
                },
            )


def downgrade() -> None:
    op.execute('ALTER TABLE rate_card_item DROP COLUMN IF EXISTS "when"')
    op.execute("ALTER TABLE rate_card_item DROP COLUMN IF EXISTS job_types")
