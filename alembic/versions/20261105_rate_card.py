"""Each business's published rate card: the VAT basis, the site visit fee, and the priced items.

Revision ID: 20261105_rate_card
Revises: 20261029_tenant

The seed rows are the prices the app shipped with. Publishing from the owner console replaces them.
"""

from alembic import op

revision = "20261105_rate_card"
down_revision = "20261029_tenant"
branch_labels = None
depends_on = None

_TABLES = ("rate_card", "rate_card_item")

_POLICY = """
CREATE POLICY tenant_isolation ON {table}
FOR ALL
USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE rate_card (
            tenant_id uuid PRIMARY KEY,
            vat_inclusive boolean NOT NULL,
            site_visit_fee numeric(12, 2) NOT NULL CHECK (site_visit_fee >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE rate_card_item (
            tenant_id uuid NOT NULL REFERENCES rate_card (tenant_id) ON DELETE CASCADE,
            item_code text NOT NULL,
            description text NOT NULL,
            unit_price numeric(12, 2) NOT NULL CHECK (unit_price > 0),
            position integer NOT NULL,
            PRIMARY KEY (tenant_id, item_code)
        )
        """
    )
    op.execute(
        """
        INSERT INTO rate_card (tenant_id, vat_inclusive, site_visit_fee)
        VALUES
            ('11111111-1111-4111-8111-111111111111', true, 750.00),
            ('22222222-2222-4222-8222-222222222222', true, 750.00)
        """
    )
    op.execute(
        """
        INSERT INTO rate_card_item (tenant_id, item_code, description, unit_price, position)
        VALUES
            ('11111111-1111-4111-8111-111111111111', 'TANK-5000', '5000 L tank', 4250.00, 0),
            ('22222222-2222-4222-8222-222222222222', 'SHEET-ECO', 'Economy sheeting', 8500.00, 0),
            ('22222222-2222-4222-8222-222222222222', 'SHEET-POLY', 'Polycarbonate sheeting', 12400.00, 1)
        """
    )
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(_POLICY.format(table=table))


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute("DROP TABLE IF EXISTS rate_card_item")
    op.execute("DROP TABLE IF EXISTS rate_card")
