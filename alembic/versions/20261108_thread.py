"""Persist the live thread: message kind, assistant replies, and quote ids.

Revision ID: 20261108_thread
Revises: 20261107_tenant_policies

The chat writes these rows as the quotedesk role, so each new table uses the
same tenant policy as the conversation. Audit rows stay insert-only.
"""

from alembic import op

revision = "20261108_thread"
down_revision = "20261107_tenant_policies"
branch_labels = None
depends_on = None

_TABLES = ("assistant_reply", "inbound_message", "sender_bind")
_POLICY = """
CREATE POLICY tenant_isolation ON {table}
FOR ALL
USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
"""


def upgrade() -> None:
    op.execute("ALTER TABLE conversation_event ADD COLUMN kind text NOT NULL DEFAULT 'text'")
    op.execute(
        """
        CREATE TABLE assistant_reply (
            reply_id bigserial PRIMARY KEY,
            tenant_id uuid NOT NULL,
            conversation_id uuid NOT NULL REFERENCES conversation (conversation_id) ON DELETE CASCADE,
            at timestamptz NOT NULL,
            body text NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE inbound_message (
            tenant_id uuid NOT NULL,
            provider_message_id text NOT NULL,
            conversation_id uuid NOT NULL REFERENCES conversation (conversation_id) ON DELETE CASCADE,
            wa_id text NOT NULL,
            at timestamptz NOT NULL,
            kind text NOT NULL,
            body text,
            media_id text,
            mime text,
            size_bytes integer,
            duration_seconds numeric,
            transcript text,
            image_text text,
            PRIMARY KEY (tenant_id, provider_message_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sender_bind (
            tenant_id uuid NOT NULL,
            wa_id text NOT NULL,
            conversation_id uuid NOT NULL,
            PRIMARY KEY (tenant_id, wa_id)
        )
        """
    )
    op.execute("CREATE SEQUENCE quote_seq START WITH 1042")
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(_POLICY.format(table=table))


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP SEQUENCE IF EXISTS quote_seq")
    op.execute("DROP TABLE IF EXISTS sender_bind")
    op.execute("DROP TABLE IF EXISTS inbound_message")
    op.execute("DROP TABLE IF EXISTS assistant_reply")
    op.execute("ALTER TABLE conversation_event DROP COLUMN IF EXISTS kind")
