"""WhatsApp phone_number_id on the tenant directory.

Revision ID: 20261114_phone
Revises: 20261113_pricing

The webhook reads this column. The simulator number is not stored here.
"""

from alembic import op

revision = "20261114_phone"
down_revision = "20261113_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant ADD COLUMN phone_number_id text")
    op.execute(
        "CREATE UNIQUE INDEX tenant_phone_number_id ON tenant (phone_number_id) WHERE phone_number_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS tenant_phone_number_id")
    op.execute("ALTER TABLE tenant DROP COLUMN IF EXISTS phone_number_id")
