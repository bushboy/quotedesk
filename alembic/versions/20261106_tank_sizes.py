"""AquaSure tank sizes the customer can choose: 2500 L and 10000 L beside the 5000 L row.

Revision ID: 20261106_tank_sizes
Revises: 20261105_rate_card

An already-migrated database keeps TANK-5000 at position 0. The new rows share that
position or follow it, and the read orders by position then code, so the card lists
2500 L, 5000 L, then 10000 L.
"""

from alembic import op

revision = "20261106_tank_sizes"
down_revision = "20261105_rate_card"
branch_labels = None
depends_on = None

_AQUASURE = "11111111-1111-4111-8111-111111111111"


def upgrade() -> None:
    op.execute(f"SELECT set_config('app.current_tenant_id', '{_AQUASURE}', true)")
    op.execute(
        f"""
        INSERT INTO rate_card_item (tenant_id, item_code, description, unit_price, position)
        VALUES
            ('{_AQUASURE}', 'TANK-2500', '2500 L tank', 2850.00, 0),
            ('{_AQUASURE}', 'TANK-10000', '10000 L tank', 7900.00, 2)
        ON CONFLICT (tenant_id, item_code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(f"SELECT set_config('app.current_tenant_id', '{_AQUASURE}', true)")
    op.execute(
        f"""
        DELETE FROM rate_card_item
        WHERE tenant_id = '{_AQUASURE}'
          AND item_code IN ('TANK-2500', 'TANK-10000')
        """
    )
