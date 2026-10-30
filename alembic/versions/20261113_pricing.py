"""Rate-card unit and role, and the decision stored on each quote version.

Revision ID: 20261113_pricing
Revises: 20261112_inspection

Sheet prices are per square metre. A quote version keeps the rule that issued it.
"""

from alembic import op

revision = "20261113_pricing"
down_revision = "20261112_inspection"
branch_labels = None
depends_on = None

_FRAMEWORKS = "22222222-2222-4222-8222-222222222222"


def upgrade() -> None:
    op.execute("ALTER TABLE rate_card_item ADD COLUMN unit text NOT NULL DEFAULT 'each'")
    op.execute("ALTER TABLE rate_card_item ADD COLUMN role text NOT NULL DEFAULT 'product'")
    op.execute(f"SELECT set_config('app.current_tenant_id', '{_FRAMEWORKS}', true)")
    op.execute("UPDATE rate_card_item SET unit = 'per m²' WHERE item_code LIKE 'SHEET-%'")
    op.execute("ALTER TABLE quote_version ADD COLUMN outcome text NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE quote_version ADD COLUMN rule_id text NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE quote_version ADD COLUMN reasons text NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE quote_version ADD COLUMN policy_version text NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE quote_version ADD COLUMN facts_used text NOT NULL DEFAULT ''")


def downgrade() -> None:
    for column in ("facts_used", "policy_version", "reasons", "rule_id", "outcome"):
        op.execute(f"ALTER TABLE quote_version DROP COLUMN IF EXISTS {column}")
    op.execute("ALTER TABLE rate_card_item DROP COLUMN IF EXISTS role")
    op.execute("ALTER TABLE rate_card_item DROP COLUMN IF EXISTS unit")
