"""Message status, enrichment, and the outbound batch.

Existing rows are answered, so a deploy does not reply to history. A new message
is pending until a turn claims it.
"""

from alembic import op

revision = "20261111_turn_ledger"
down_revision = "20261110_contact_name"
branch_labels = None
depends_on = None

_POLICY = """
CREATE POLICY tenant_isolation ON {table}
FOR ALL
USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
"""


def upgrade() -> None:
    op.execute("ALTER TABLE conversation_event ADD COLUMN status text")
    op.execute("ALTER TABLE conversation_event ADD COLUMN outcome text")
    op.execute("UPDATE conversation_event SET status = 'answered' WHERE status IS NULL")
    op.execute("ALTER TABLE conversation_event ALTER COLUMN status SET DEFAULT 'pending'")
    op.execute("ALTER TABLE conversation_event ALTER COLUMN status SET NOT NULL")
    op.execute("ALTER TABLE conversation ADD COLUMN escalated boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE conversation ADD COLUMN change_key text")
    op.execute("ALTER TABLE assistant_reply ADD COLUMN batch_id text")
    op.execute("ALTER TABLE assistant_reply ADD COLUMN send_status text NOT NULL DEFAULT 'sent'")
    op.execute(
        """
        CREATE UNIQUE INDEX assistant_reply_batch
        ON assistant_reply (tenant_id, batch_id)
        WHERE batch_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE TABLE enrichment (
            tenant_id uuid NOT NULL,
            provider_message_id text NOT NULL,
            payload text NOT NULL,
            PRIMARY KEY (tenant_id, provider_message_id)
        )
        """
    )
    op.execute("ALTER TABLE enrichment ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE enrichment FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY.format(table="enrichment"))


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON enrichment")
    op.execute("ALTER TABLE enrichment NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE enrichment DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS enrichment")
    op.execute("DROP INDEX IF EXISTS assistant_reply_batch")
    op.execute("ALTER TABLE assistant_reply DROP COLUMN IF EXISTS send_status")
    op.execute("ALTER TABLE assistant_reply DROP COLUMN IF EXISTS batch_id")
    op.execute("ALTER TABLE conversation DROP COLUMN IF EXISTS change_key")
    op.execute("ALTER TABLE conversation DROP COLUMN IF EXISTS escalated")
    op.execute("ALTER TABLE conversation_event DROP COLUMN IF EXISTS outcome")
    op.execute("ALTER TABLE conversation_event DROP COLUMN IF EXISTS status")
