"""Quote amounts, verification codes, handovers, acceptances, deposits, and holds.

Revision ID: 20261109_commercial
Revises: 20261108_thread

A range quote keeps its ends and its deposit. A card code, an acceptance, a
handover, and a held day survive a restart. FrameWorks sheet prices are per
square metre.
"""

from alembic import op

revision = "20261109_commercial"
down_revision = "20261108_thread"
branch_labels = None
depends_on = None

_FRAMEWORKS = "22222222-2222-4222-8222-222222222222"
_TABLES = (
    "verification_code",
    "handover",
    "acceptance",
    "deposit_link",
    "capacity_slot",
    "capacity_hold",
)
_POLICY = """
CREATE POLICY tenant_isolation ON {table}
FOR ALL
USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
"""


def upgrade() -> None:
    op.execute("ALTER TABLE quote_version ADD COLUMN price_type text")
    op.execute("ALTER TABLE quote_version ADD COLUMN range_min numeric(12, 2)")
    op.execute("ALTER TABLE quote_version ADD COLUMN range_max numeric(12, 2)")
    op.execute("ALTER TABLE quote_version ADD COLUMN deposit numeric(12, 2)")
    op.execute("ALTER TABLE quote_version ADD COLUMN site_visit_fee numeric(12, 2)")
    op.execute(
        """
        CREATE TABLE verification_code (
            tenant_id uuid NOT NULL,
            quote_id text NOT NULL,
            code text NOT NULL,
            PRIMARY KEY (tenant_id, quote_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE handover (
            tenant_id uuid NOT NULL,
            conversation_id uuid NOT NULL,
            reason text NOT NULL,
            brief text NOT NULL,
            at timestamptz NOT NULL,
            PRIMARY KEY (tenant_id, conversation_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE acceptance (
            tenant_id uuid NOT NULL,
            quote_id text NOT NULL,
            version integer NOT NULL,
            at timestamptz NOT NULL,
            PRIMARY KEY (tenant_id, quote_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE deposit_link (
            tenant_id uuid NOT NULL,
            idempotency_key text NOT NULL,
            quote_id text NOT NULL,
            url text NOT NULL,
            PRIMARY KEY (tenant_id, idempotency_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE capacity_slot (
            tenant_id uuid NOT NULL,
            day date NOT NULL,
            places integer NOT NULL,
            PRIMARY KEY (tenant_id, day)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE capacity_hold (
            tenant_id uuid NOT NULL,
            day date NOT NULL,
            hold_expires_at timestamptz NOT NULL,
            PRIMARY KEY (tenant_id, day, hold_expires_at)
        )
        """
    )
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(_POLICY.format(table=table))
    op.execute(f"SELECT set_config('app.current_tenant_id', '{_FRAMEWORKS}', true)")
    op.execute(
        f"""
        UPDATE rate_card_item
        SET unit_price = 180.00
        WHERE tenant_id = '{_FRAMEWORKS}' AND item_code = 'SHEET-ECO'
        """
    )
    op.execute(
        f"""
        UPDATE rate_card_item
        SET unit_price = 260.00
        WHERE tenant_id = '{_FRAMEWORKS}' AND item_code = 'SHEET-POLY'
        """
    )


def downgrade() -> None:
    op.execute(f"SELECT set_config('app.current_tenant_id', '{_FRAMEWORKS}', true)")
    op.execute(
        f"""
        UPDATE rate_card_item
        SET unit_price = 8500.00
        WHERE tenant_id = '{_FRAMEWORKS}' AND item_code = 'SHEET-ECO'
        """
    )
    op.execute(
        f"""
        UPDATE rate_card_item
        SET unit_price = 12400.00
        WHERE tenant_id = '{_FRAMEWORKS}' AND item_code = 'SHEET-POLY'
        """
    )
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("ALTER TABLE quote_version DROP COLUMN IF EXISTS site_visit_fee")
    op.execute("ALTER TABLE quote_version DROP COLUMN IF EXISTS deposit")
    op.execute("ALTER TABLE quote_version DROP COLUMN IF EXISTS range_max")
    op.execute("ALTER TABLE quote_version DROP COLUMN IF EXISTS range_min")
    op.execute("ALTER TABLE quote_version DROP COLUMN IF EXISTS price_type")
