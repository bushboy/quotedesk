"""Whether a rate-card row applies to a swap, a new installation, or both.

Revision ID: 20261116_applies_to
Revises: 20261115_fact_status

Rows saved before this column existed apply to both. The owner sets a narrower
value from the console.
"""

from alembic import op

revision = "20261116_applies_to"
down_revision = "20261115_fact_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE rate_card_item ADD COLUMN applies_to text NOT NULL DEFAULT 'both'")


def downgrade() -> None:
    op.execute("ALTER TABLE rate_card_item DROP COLUMN IF EXISTS applies_to")
