"""Inspection rows, one owner notice per escalation, and the unknown fact state.

An inspection is offered, then booked. The owner is told once.
"""

from alembic import op

revision = "20261112_inspection"
down_revision = "20261111_turn_ledger"
branch_labels = None
depends_on = None

_POLICY = """
CREATE POLICY tenant_isolation ON {table}
FOR ALL
USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
"""


def upgrade() -> None:
    op.execute("ALTER TABLE case_fact ADD COLUMN state text NOT NULL DEFAULT 'known'")
    op.execute(
        """
        CREATE TABLE inspection (
            tenant_id uuid NOT NULL,
            inspection_id uuid NOT NULL,
            conversation_id uuid NOT NULL,
            job_id text NOT NULL,
            address text NOT NULL,
            rule_id text NOT NULL,
            fee text NOT NULL,
            window_start date,
            window_end date,
            status text NOT NULL,
            summary text NOT NULL,
            at timestamptz NOT NULL,
            PRIMARY KEY (tenant_id, inspection_id),
            UNIQUE (tenant_id, conversation_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE owner_notice (
            tenant_id uuid NOT NULL,
            conversation_id uuid NOT NULL,
            channel text NOT NULL,
            at timestamptz NOT NULL,
            PRIMARY KEY (tenant_id, conversation_id)
        )
        """
    )
    for table in ("inspection", "owner_notice"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(_POLICY.format(table=table))


def downgrade() -> None:
    for table in ("owner_notice", "inspection"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("ALTER TABLE case_fact DROP COLUMN IF EXISTS state")
