from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from quotedesk.domain.policy.clauses import Condition
from quotedesk.domain.quotes.quote import Approval, Quote, QuoteLine, QuoteState, QuoteVersion
from quotedesk.domain.shared.ids import QuoteId
from quotedesk.domain.shared.money import Money


class QuoteTables:
    def save(self, connection: Connection, tenant_id: UUID, conversation_id: UUID, quote: Quote) -> None:
        _tenant(connection, tenant_id)
        quote_id = quote.quote_id.value
        connection.execute(text("DELETE FROM quote WHERE quote_id = :quote_id"), {"quote_id": quote_id})
        connection.execute(
            text(
                """
                INSERT INTO quote (quote_id, tenant_id, conversation_id)
                VALUES (:quote_id, :tenant_id, :conversation_id)
                """
            ),
            {"quote_id": quote_id, "tenant_id": tenant_id, "conversation_id": conversation_id},
        )
        for version in quote.versions:
            connection.execute(
                text(
                    """
                    INSERT INTO quote_version (quote_id, number, state, expiry, at)
                    VALUES (:quote_id, :number, :state, :expiry, :at)
                    """
                ),
                {
                    "quote_id": quote_id,
                    "number": version.number,
                    "state": version.state.value,
                    "expiry": version.expiry,
                    "at": version.at,
                },
            )
            for position, line in enumerate(version.lines):
                connection.execute(
                    text(
                        """
                        INSERT INTO quote_line (
                            quote_id, number, position, item_code, description, quantity, unit_price, total
                        )
                        VALUES (
                            :quote_id, :number, :position, :item_code, :description, :quantity, :unit_price, :total
                        )
                        """
                    ),
                    {
                        "quote_id": quote_id,
                        "number": version.number,
                        "position": position,
                        "item_code": line.item_code,
                        "description": line.description,
                        "quantity": line.quantity,
                        "unit_price": line.unit_price.amount,
                        "total": line.total.amount,
                    },
                )
            for position, clause in enumerate(version.clauses):
                connection.execute(
                    text(
                        """
                        INSERT INTO quote_condition (
                            quote_id, number, position, clause_id, clause_version, kind, text, if_not_true,
                            variation_item_code
                        )
                        VALUES (
                            :quote_id, :number, :position, :clause_id, :clause_version, :kind, :text, :if_not_true,
                            :variation_item_code
                        )
                        """
                    ),
                    {
                        "quote_id": quote_id,
                        "number": version.number,
                        "position": position,
                        "clause_id": clause.clause_id,
                        "clause_version": clause.clause_version,
                        "kind": clause.kind,
                        "text": clause.text,
                        "if_not_true": clause.if_not_true,
                        "variation_item_code": clause.variation_item_code,
                    },
                )
            for approval in version.approvals:
                connection.execute(
                    text(
                        """
                        INSERT INTO quote_approval (
                            quote_id, number, applies_to_version, expires_at
                        )
                        VALUES (:quote_id, :number, :applies_to_version, :expires_at)
                        """
                    ),
                    {
                        "quote_id": quote_id,
                        "number": version.number,
                        "applies_to_version": approval.applies_to_version,
                        "expires_at": approval.expires_at,
                    },
                )

    def save_evidence(self, connection: Connection, tenant_id: UUID, quote: Quote, evidence_ids: tuple[str, ...]) -> None:
        _tenant(connection, tenant_id)
        for evidence_id in evidence_ids:
            connection.execute(
                text(
                    """
                    INSERT INTO quote_evidence (quote_id, number, evidence_id)
                    VALUES (:quote_id, :number, :evidence_id)
                    """
                ),
                {"quote_id": quote.quote_id.value, "number": quote.current.number, "evidence_id": evidence_id},
            )

    def evidence(self, connection: Connection, tenant_id: UUID, quote_id: str, number: int) -> tuple[str, ...]:
        _tenant(connection, tenant_id)
        rows = connection.execute(
            text(
                """
                SELECT evidence_id FROM quote_evidence
                WHERE quote_id = :quote_id AND number = :number
                ORDER BY evidence_id
                """
            ),
            {"quote_id": quote_id, "number": number},
        )
        return tuple(row.evidence_id for row in rows)

    def save_with_audit(self, connection: Connection, tenant_id: UUID, conversation_id: UUID, quote: Quote, action: str) -> None:
        with connection.begin_nested():
            self.save(connection, tenant_id, conversation_id, quote)
            _tenant(connection, tenant_id)
            connection.execute(
                text(
                    """
                    INSERT INTO audit_event (tenant_id, action, quote_id, version)
                    VALUES (:tenant_id, :action, :quote_id, :version)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "action": action,
                    "quote_id": quote.quote_id.value,
                    "version": quote.current.number,
                },
            )

    def get(self, connection: Connection, tenant_id: UUID, conversation_id: UUID) -> Quote | None:
        _tenant(connection, tenant_id)
        row = connection.execute(
            text(
                """
                SELECT quote_id FROM quote
                WHERE tenant_id = :tenant_id AND conversation_id = :conversation_id
                """
            ),
            {"tenant_id": tenant_id, "conversation_id": conversation_id},
        ).one_or_none()
        if row is None:
            return None
        quote_id = row.quote_id
        versions = []
        version_rows = connection.execute(
            text(
                """
                SELECT number, state, expiry, at
                FROM quote_version
                WHERE quote_id = :quote_id
                ORDER BY number
                """
            ),
            {"quote_id": quote_id},
        )
        for version in version_rows:
            lines = tuple(
                QuoteLine(
                    item_code=line.item_code,
                    description=line.description,
                    quantity=Decimal(line.quantity),
                    unit_price=Money(Decimal(line.unit_price)),
                    total=Money(Decimal(line.total)),
                )
                for line in connection.execute(
                    text(
                        """
                        SELECT item_code, description, quantity, unit_price, total
                        FROM quote_line
                        WHERE quote_id = :quote_id AND number = :number
                        ORDER BY position
                        """
                    ),
                    {"quote_id": quote_id, "number": version.number},
                )
            )
            clauses = tuple(
                Condition(
                    clause_id=clause.clause_id,
                    clause_version=clause.clause_version,
                    kind=clause.kind,
                    text=clause.text,
                    if_not_true=clause.if_not_true,
                    variation_item_code=clause.variation_item_code,
                )
                for clause in connection.execute(
                    text(
                        """
                        SELECT clause_id, clause_version, kind, text, if_not_true, variation_item_code
                        FROM quote_condition
                        WHERE quote_id = :quote_id AND number = :number
                        ORDER BY position
                        """
                    ),
                    {"quote_id": quote_id, "number": version.number},
                )
            )
            approvals = tuple(
                Approval(applies_to_version=row.applies_to_version, expires_at=row.expires_at)
                for row in connection.execute(
                    text(
                        """
                        SELECT applies_to_version, expires_at
                        FROM quote_approval
                        WHERE quote_id = :quote_id AND number = :number
                        ORDER BY applies_to_version
                        """
                    ),
                    {"quote_id": quote_id, "number": version.number},
                )
            )
            versions.append(
                QuoteVersion(
                    number=version.number,
                    state=QuoteState(version.state),
                    expiry=version.expiry,
                    lines=lines,
                    clauses=clauses,
                    approvals=approvals,
                    at=version.at,
                )
            )
        return Quote(quote_id=QuoteId(quote_id), versions=tuple(versions))


def _tenant(connection: Connection, tenant_id: UUID) -> None:
    connection.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )
