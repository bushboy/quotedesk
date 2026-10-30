"""The published rate card rows for one business."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from quotedesk.adapters.outbound.persistence.records import bind_tenant
from quotedesk.domain.services.price import RateCard, RateCardItem
from quotedesk.domain.shared.money import Money


class RateCardTables:
    def get(self, connection: Connection, tenant_id: UUID) -> RateCard | None:
        bind_tenant(connection, tenant_id)
        card = (
            connection.execute(
                text("SELECT vat_inclusive, site_visit_fee FROM rate_card WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            .mappings()
            .first()
        )
        if card is None:
            return None
        items = connection.execute(
            text(
                """
                SELECT item_code, description, unit_price, unit, role FROM rate_card_item
                WHERE tenant_id = :tenant_id
                ORDER BY position, item_code
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings()
        return RateCard(
            vat_inclusive=card["vat_inclusive"],
            site_visit_fee=Money(card["site_visit_fee"]),
            items=tuple(
                RateCardItem(
                    item_code=item["item_code"],
                    description=item["description"],
                    unit_price=Money(item["unit_price"]),
                    unit=item["unit"] or "each",
                    role=item["role"] or "product",
                )
                for item in items
            ),
        )

    def save(self, connection: Connection, tenant_id: UUID, card: RateCard) -> None:
        bind_tenant(connection, tenant_id)
        connection.execute(text("DELETE FROM rate_card WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
        connection.execute(
            text(
                """
                INSERT INTO rate_card (tenant_id, vat_inclusive, site_visit_fee)
                VALUES (:tenant_id, :vat_inclusive, :site_visit_fee)
                """
            ),
            {
                "tenant_id": tenant_id,
                "vat_inclusive": card.vat_inclusive,
                "site_visit_fee": card.site_visit_fee.amount,
            },
        )
        for position, item in enumerate(card.items):
            connection.execute(
                text(
                    """
                    INSERT INTO rate_card_item (tenant_id, item_code, description, unit_price, position, unit, role)
                    VALUES (:tenant_id, :item_code, :description, :unit_price, :position, :unit, :role)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "item_code": item.item_code,
                    "description": item.description,
                    "unit_price": item.unit_price.amount,
                    "position": position,
                    "unit": item.unit,
                    "role": item.role,
                },
            )
