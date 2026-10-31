"""Fact status, evidence, and confidence on case facts.

Revision ID: 20261115_fact_status
Revises: 20261114_phone

A photo fact can be inferred until the customer confirms it. The score is a
decimal, stored as numeric so it is not a float.
"""

from alembic import op

revision = "20261115_fact_status"
down_revision = "20261114_phone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE case_fact ADD COLUMN status text NOT NULL DEFAULT 'stated'")
    op.execute("ALTER TABLE case_fact ADD COLUMN evidence text NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE case_fact ADD COLUMN confidence numeric(8, 6)")


def downgrade() -> None:
    op.execute("ALTER TABLE case_fact DROP COLUMN IF EXISTS confidence")
    op.execute("ALTER TABLE case_fact DROP COLUMN IF EXISTS evidence")
    op.execute("ALTER TABLE case_fact DROP COLUMN IF EXISTS status")
