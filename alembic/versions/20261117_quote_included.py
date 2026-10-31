"""Names of the infrastructure a range includes in both ends.

Revision ID: 20261117_quote_included
Revises: 20261116_applies_to

A fixed quote stores those rows as lines. A range keeps lines empty and records
the shared descriptions here so the card can name them.
"""

from alembic import op

revision = "20261117_quote_included"
down_revision = "20261116_applies_to"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE quote_version ADD COLUMN included text NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE quote_version DROP COLUMN IF EXISTS included")
