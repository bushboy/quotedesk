"""The speech score stored with a voice-note transcript.

Revision ID: 20261119_transcript_confidence
Revises: 20261118_rate_card_rows

A missing score is null. The turn then treats a spoken yes as unsure.
"""

from alembic import op

revision = "20261119_transcript_confidence"
down_revision = "20261118_rate_card_rows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE inbound_message ADD COLUMN transcript_confidence numeric")


def downgrade() -> None:
    op.execute("ALTER TABLE inbound_message DROP COLUMN IF EXISTS transcript_confidence")
