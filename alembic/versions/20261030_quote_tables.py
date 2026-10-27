"""Quote tables for the committed quote models.

Revision ID: 20261030_quote
Revises:
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op

revision = "20261030_quote"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quote",
        sa.Column("quote_id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
    )
    op.create_table(
        "quote_version",
        sa.Column("quote_id", sa.Text(), sa.ForeignKey("quote.quote_id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("quote_id", "number"),
    )
    op.create_table(
        "quote_line",
        sa.Column("quote_id", sa.Text(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("item_code", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("unit_price", sa.Numeric(), nullable=False),
        sa.Column("total", sa.Numeric(), nullable=False),
        sa.ForeignKeyConstraint(["quote_id", "number"], ["quote_version.quote_id", "quote_version.number"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("quote_id", "number", "position"),
    )
    op.create_table(
        "quote_condition",
        sa.Column("quote_id", sa.Text(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("clause_id", sa.Text(), nullable=False),
        sa.Column("clause_version", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("if_not_true", sa.Text(), nullable=False),
        sa.Column("variation_item_code", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["quote_id", "number"], ["quote_version.quote_id", "quote_version.number"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("quote_id", "number", "position"),
    )
    op.create_table(
        "quote_evidence",
        sa.Column("quote_id", sa.Text(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["quote_id", "number"], ["quote_version.quote_id", "quote_version.number"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("quote_id", "number", "evidence_id"),
    )
    op.create_table(
        "quote_approval",
        sa.Column("quote_id", sa.Text(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("applies_to_version", sa.Integer(), nullable=False),
        sa.Column("approver", sa.Text(), nullable=True),
        sa.Column("change", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["quote_id", "number"], ["quote_version.quote_id", "quote_version.number"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("quote_id", "number", "applies_to_version"),
    )


def downgrade() -> None:
    op.drop_table("quote_approval")
    op.drop_table("quote_evidence")
    op.drop_table("quote_condition")
    op.drop_table("quote_line")
    op.drop_table("quote_version")
    op.drop_table("quote")
