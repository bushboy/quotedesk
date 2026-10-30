"""Codes, handovers, acceptances, deposit links, and capacity.

The live app uses the Postgres classes when the thread store is up. The memory
classes are the same ports for a process with no database.
"""

import secrets
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from quotedesk.adapters.outbound.persistence.records import bind_tenant
from quotedesk.application.dto.agent import HandoverNote
from quotedesk.application.dto.changes import DepositLinkRecord
from quotedesk.domain.quotes.schedule import Capacity, CapacitySlot, SlotHold
from quotedesk.domain.shared.ids import QuoteId


class IssuedCodes:
    def __init__(self) -> None:
        self._codes: dict[tuple[UUID, str], str] = {}

    def issue(self, tenant_id: UUID, quote_id: QuoteId) -> str:
        key = (tenant_id, quote_id.value)
        found = self._codes.get(key)
        if found is not None:
            return found
        code = f"{secrets.randbelow(9000) + 1000:04d}"
        self._codes[key] = code
        return code

    def matches(self, tenant_id: UUID, quote_id: QuoteId, code: str) -> bool:
        return self._codes.get((tenant_id, quote_id.value)) == code


class SequencingIds:
    """One id per quote in this process. The first is still QD-1042."""

    def __init__(self) -> None:
        self._next = 1042

    def next_quote_id(self) -> QuoteId:
        quote_id = QuoteId(f"QD-{self._next}")
        self._next += 1
        return quote_id

    def next_fact_id(self) -> UUID:
        from uuid import uuid4

        return uuid4()

    def next_idempotency_key(self) -> str:
        from uuid import uuid4

        return str(uuid4())


class MemoryAcceptances:
    def __init__(self) -> None:
        self._rows: set[tuple[UUID, str, int]] = set()

    def record(self, tenant_id: UUID, quote_id: QuoteId, version: int, at: datetime | None = None) -> None:
        self._rows.add((tenant_id, quote_id.value, version))

    def has(self, tenant_id: UUID, quote_id: QuoteId, version: int) -> bool:
        return (tenant_id, quote_id.value, version) in self._rows


class MemoryLinks:
    def __init__(self) -> None:
        self._rows: dict[tuple[UUID, str], DepositLinkRecord] = {}

    def find(self, tenant_id: UUID, idempotency_key: str) -> DepositLinkRecord | None:
        return self._rows.get((tenant_id, idempotency_key))

    def save(self, record: DepositLinkRecord) -> None:
        self._rows[(record.tenant_id, record.idempotency_key)] = record


class MemoryDeposits:
    def paid(self, tenant_id: UUID, quote_id: QuoteId) -> bool:
        return False


class MemoryCapacity:
    def __init__(self) -> None:
        self._rows: dict[UUID, Capacity] = {}

    def get(self, tenant_id: UUID) -> Capacity:
        return self._rows.get(tenant_id, Capacity())

    def save(self, tenant_id: UUID, capacity: Capacity) -> None:
        self._rows[tenant_id] = capacity


class MemoryHolds:
    def __init__(self) -> None:
        self._rows: dict[tuple[UUID, str], object] = {}

    def find(self, tenant_id: UUID, idempotency_key: str):
        return self._rows.get((tenant_id, idempotency_key))

    def save(self, tenant_id: UUID, idempotency_key: str, result) -> None:
        self._rows[(tenant_id, idempotency_key)] = result


class MemoryHandovers:
    def __init__(self) -> None:
        self._rows: dict[tuple[UUID, UUID], HandoverNote] = {}

    def append(self, tenant_id: UUID, note: HandoverNote) -> None:
        self._rows[(tenant_id, note.conversation_id)] = note

    def list(self, tenant_id: UUID) -> tuple[HandoverNote, ...]:
        return tuple(note for (stored, _), note in self._rows.items() if stored == tenant_id)


class StoredCodes:
    def __init__(self, engine) -> None:
        self._engine = engine

    def issue(self, tenant_id: UUID, quote_id: QuoteId) -> str:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            row = connection.execute(
                text(
                    """
                    SELECT code FROM verification_code
                    WHERE tenant_id = :tenant_id AND quote_id = :quote_id
                    """
                ),
                {"tenant_id": tenant_id, "quote_id": quote_id.value},
            ).one_or_none()
            if row is not None:
                return row.code
            code = f"{secrets.randbelow(9000) + 1000:04d}"
            connection.execute(
                text(
                    """
                    INSERT INTO verification_code (tenant_id, quote_id, code)
                    VALUES (:tenant_id, :quote_id, :code)
                    """
                ),
                {"tenant_id": tenant_id, "quote_id": quote_id.value, "code": code},
            )
        return code

    def matches(self, tenant_id: UUID, quote_id: QuoteId, code: str) -> bool:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            row = connection.execute(
                text(
                    """
                    SELECT code FROM verification_code
                    WHERE tenant_id = :tenant_id AND quote_id = :quote_id
                    """
                ),
                {"tenant_id": tenant_id, "quote_id": quote_id.value},
            ).one_or_none()
        return row is not None and row.code == code


class StoredAcceptances:
    def __init__(self, engine) -> None:
        self._engine = engine

    def record(self, tenant_id: UUID, quote_id: QuoteId, version: int, at: datetime | None = None) -> None:
        when = at or datetime.now(timezone.utc)
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            connection.execute(
                text(
                    """
                    INSERT INTO acceptance (tenant_id, quote_id, version, at)
                    VALUES (:tenant_id, :quote_id, :version, :at)
                    ON CONFLICT (tenant_id, quote_id, version) DO NOTHING
                    """
                ),
                {"tenant_id": tenant_id, "quote_id": quote_id.value, "version": version, "at": when},
            )

    def has(self, tenant_id: UUID, quote_id: QuoteId, version: int) -> bool:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            row = connection.execute(
                text(
                    """
                    SELECT 1 FROM acceptance
                    WHERE tenant_id = :tenant_id AND quote_id = :quote_id AND version = :version
                    """
                ),
                {"tenant_id": tenant_id, "quote_id": quote_id.value, "version": version},
            ).one_or_none()
        return row is not None


class StoredLinks:
    def __init__(self, engine) -> None:
        self._engine = engine

    def find(self, tenant_id: UUID, idempotency_key: str) -> DepositLinkRecord | None:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            row = connection.execute(
                text(
                    """
                    SELECT quote_id, url FROM deposit_link
                    WHERE tenant_id = :tenant_id AND idempotency_key = :idempotency_key
                    """
                ),
                {"tenant_id": tenant_id, "idempotency_key": idempotency_key},
            ).one_or_none()
        if row is None:
            return None
        return DepositLinkRecord(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            quote_id=QuoteId(row.quote_id),
            url=row.url,
        )

    def save(self, record: DepositLinkRecord) -> None:
        with self._engine.begin() as connection:
            bind_tenant(connection, record.tenant_id)
            connection.execute(
                text(
                    """
                    INSERT INTO deposit_link (tenant_id, idempotency_key, quote_id, url)
                    VALUES (:tenant_id, :idempotency_key, :quote_id, :url)
                    ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                    """
                ),
                {
                    "tenant_id": record.tenant_id,
                    "idempotency_key": record.idempotency_key,
                    "quote_id": record.quote_id.value,
                    "url": record.url,
                },
            )


class StoredCapacity:
    def __init__(self, engine) -> None:
        self._engine = engine

    def get(self, tenant_id: UUID) -> Capacity:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            days = connection.execute(
                text("SELECT day, places FROM capacity_slot WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            slots = []
            for day in days:
                holds = tuple(
                    SlotHold(hold_expires_at=row.hold_expires_at)
                    for row in connection.execute(
                        text(
                            """
                            SELECT hold_expires_at FROM capacity_hold
                            WHERE tenant_id = :tenant_id AND day = :day
                            """
                        ),
                        {"tenant_id": tenant_id, "day": day.day},
                    )
                )
                slots.append(CapacitySlot(day=day.day, places=day.places, holds=holds))
        return Capacity(slots=tuple(slots))

    def save(self, tenant_id: UUID, capacity: Capacity) -> None:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            connection.execute(text("DELETE FROM capacity_hold WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
            connection.execute(text("DELETE FROM capacity_slot WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})
            for slot in capacity.slots:
                connection.execute(
                    text(
                        """
                        INSERT INTO capacity_slot (tenant_id, day, places)
                        VALUES (:tenant_id, :day, :places)
                        """
                    ),
                    {"tenant_id": tenant_id, "day": slot.day, "places": slot.places},
                )
                for hold in slot.holds:
                    connection.execute(
                        text(
                            """
                            INSERT INTO capacity_hold (tenant_id, day, hold_expires_at)
                            VALUES (:tenant_id, :day, :hold_expires_at)
                            """
                        ),
                        {"tenant_id": tenant_id, "day": slot.day, "hold_expires_at": hold.hold_expires_at},
                    )


class StoredHandovers:
    def __init__(self, engine) -> None:
        self._engine = engine

    def append(self, tenant_id: UUID, note: HandoverNote) -> None:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            connection.execute(
                text(
                    """
                    INSERT INTO handover (tenant_id, conversation_id, reason, brief, at)
                    VALUES (:tenant_id, :conversation_id, :reason, :brief, :at)
                    ON CONFLICT (tenant_id, conversation_id)
                    DO UPDATE SET reason = EXCLUDED.reason, brief = EXCLUDED.brief, at = EXCLUDED.at
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "conversation_id": note.conversation_id,
                    "reason": note.reason,
                    "brief": note.brief,
                    "at": note.at,
                },
            )

    def list(self, tenant_id: UUID) -> tuple[HandoverNote, ...]:
        with self._engine.begin() as connection:
            bind_tenant(connection, tenant_id)
            rows = connection.execute(
                text(
                    """
                    SELECT conversation_id, reason, brief, at
                    FROM handover
                    WHERE tenant_id = :tenant_id
                    ORDER BY at
                    """
                ),
                {"tenant_id": tenant_id},
            )
        return tuple(
            HandoverNote(conversation_id=row.conversation_id, reason=row.reason, brief=row.brief, at=row.at)
            for row in rows
        )
