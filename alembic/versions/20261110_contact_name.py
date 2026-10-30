"""A WhatsApp number can carry the name the customer gave.

Revision ID: 20261110_contact_name
Revises: 20261109_commercial

The console shows that name on the contact and on the quotes for their conversation.
"""

from alembic import op

revision = "20261110_contact_name"
down_revision = "20261109_commercial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sender_bind ADD COLUMN display_name text")


def downgrade() -> None:
    op.execute("ALTER TABLE sender_bind DROP COLUMN IF EXISTS display_name")
