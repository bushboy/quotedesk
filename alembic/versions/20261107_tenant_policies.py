"""Each business keeps its own published policy id.

Revision ID: 20261107_tenant_policies
Revises: 20261106_tank_sizes

AquaSure stays on water-policy-v1.0. FrameWorks moves off that id onto fab-policy-v1.0.
Row-level security is already on, so each write sets the tenant first.
"""

from alembic import op

revision = "20261107_tenant_policies"
down_revision = "20261106_tank_sizes"
branch_labels = None
depends_on = None

_AQUASURE = "11111111-1111-4111-8111-111111111111"
_FRAMEWORKS = "22222222-2222-4222-8222-222222222222"


def upgrade() -> None:
    op.execute(f"SELECT set_config('app.current_tenant_id', '{_FRAMEWORKS}', true)")
    op.execute(
        f"""
        DELETE FROM policy_row
        WHERE tenant_id = '{_FRAMEWORKS}' AND policy_id = 'water-policy-v1.0'
        """
    )
    op.execute(
        f"""
        INSERT INTO policy_row (tenant_id, policy_id)
        VALUES ('{_FRAMEWORKS}', 'fab-policy-v1.0')
        ON CONFLICT (tenant_id, policy_id) DO NOTHING
        """
    )
    op.execute(f"SELECT set_config('app.current_tenant_id', '{_AQUASURE}', true)")
    op.execute(
        f"""
        INSERT INTO policy_row (tenant_id, policy_id)
        VALUES ('{_AQUASURE}', 'water-policy-v1.0')
        ON CONFLICT (tenant_id, policy_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(f"SELECT set_config('app.current_tenant_id', '{_FRAMEWORKS}', true)")
    op.execute(
        f"""
        DELETE FROM policy_row
        WHERE tenant_id = '{_FRAMEWORKS}' AND policy_id = 'fab-policy-v1.0'
        """
    )
