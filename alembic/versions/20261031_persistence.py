"""Case, conversation, schedule, policy, and audit tables, with row-level security.

Revision ID: 20261031_persistence
Revises: 20261030_quote
"""

from alembic import op

revision = "20261031_persistence"
down_revision = "20261030_quote"
branch_labels = None
depends_on = None

_TABLES = (
    "quote",
    "case_file",
    "case_fact",
    "conversation",
    "conversation_event",
    "schedule_commitment",
    "policy_row",
    "audit_event",
)

_POLICY = """
CREATE POLICY tenant_isolation ON {table}
FOR ALL
USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE case_file (
            conversation_id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE case_fact (
            fact_id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL,
            conversation_id uuid NOT NULL REFERENCES case_file (conversation_id) ON DELETE CASCADE,
            job_id text NOT NULL,
            job_type text,
            job_status text NOT NULL,
            key text NOT NULL,
            value text NOT NULL,
            source text NOT NULL,
            event_id uuid NOT NULL,
            superseded_by uuid,
            contested boolean NOT NULL DEFAULT false
        )
        """
    )
    op.execute(
        """
        CREATE TABLE conversation (
            conversation_id uuid PRIMARY KEY,
            tenant_id uuid NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE conversation_event (
            conversation_id uuid NOT NULL REFERENCES conversation (conversation_id) ON DELETE CASCADE,
            tenant_id uuid NOT NULL,
            provider_message_id text NOT NULL,
            at timestamptz NOT NULL,
            body text NOT NULL,
            transcript_id text,
            extraction_id text,
            arrival integer NOT NULL,
            PRIMARY KEY (conversation_id, provider_message_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE schedule_commitment (
            quote_id text PRIMARY KEY,
            tenant_id uuid NOT NULL,
            status text NOT NULL,
            sentence text NOT NULL,
            earliest_window date
        )
        """
    )
    op.execute(
        """
        CREATE TABLE policy_row (
            tenant_id uuid NOT NULL,
            policy_id text NOT NULL,
            PRIMARY KEY (tenant_id, policy_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE audit_event (
            audit_id bigserial PRIMARY KEY,
            tenant_id uuid NOT NULL,
            action text NOT NULL,
            quote_id text,
            version integer
        )
        """
    )
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(_POLICY.format(table=table))
    op.execute("REVOKE UPDATE, DELETE ON audit_event FROM quotedesk")
    op.execute("REVOKE UPDATE, DELETE ON audit_event FROM PUBLIC")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS audit_event")
    op.execute("DROP TABLE IF EXISTS policy_row")
    op.execute("DROP TABLE IF EXISTS schedule_commitment")
    op.execute("DROP TABLE IF EXISTS conversation_event")
    op.execute("DROP TABLE IF EXISTS conversation")
    op.execute("DROP TABLE IF EXISTS case_fact")
    op.execute("DROP TABLE IF EXISTS case_file")
