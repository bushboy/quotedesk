"""A tenant directory the running process can read before it picks a business.

Revision ID: 20261029_tenant
Revises: 20261031_persistence

This table has no row-level security. Startup reads it to learn who is active,
then sets app.current_tenant_id for every other table.
"""

from alembic import op

revision = "20261029_tenant"
down_revision = "20261031_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant (
            tenant_id uuid PRIMARY KEY,
            slug text NOT NULL UNIQUE,
            display_name text NOT NULL,
            trade text NOT NULL,
            area text NOT NULL,
            about text NOT NULL
        )
        """
    )
    op.execute(
        """
        INSERT INTO tenant (tenant_id, slug, display_name, trade, area, about)
        VALUES
            (
                '11111111-1111-4111-8111-111111111111',
                'aquasure',
                'AquaSure',
                'water tanks and pumps',
                'Johannesburg',
                'AquaSure installs and replaces household water tanks and pumps.'
            ),
            (
                '22222222-2222-4222-8222-222222222222',
                'frameworks',
                'FrameWorks',
                'carports and sheeting',
                'Pretoria',
                'FrameWorks builds carports and replaces sheeting and windows.'
            )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE tenant")
