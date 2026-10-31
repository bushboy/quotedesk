"""Clear transactional history so a test can start from scratch.

Deletes every tenant's chats, the messages in them, case files, escalations,
inspections, quotes, bookings, and handovers. Message rows live in
conversation_event, inbound_message, and assistant_reply, so those are removed
before the conversation header. Quote lines have no tenant column; they go
with the tenant's quotes. Keeps the tenant directory, rate cards, and
published policy ids. Audit rows are insert-only and stay when the database
refuses the delete.

The running app keeps an outbox and a quote cache in memory. Restart it after
this script.

    python scripts/clear_conversations.py

DATABASE_URL comes from the environment, or from the .env file beside this
repo. The next quote id is QD-1042.
"""

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

_ROOT = Path(__file__).resolve().parents[1]
# Children first. A conversation header cannot go while its messages remain,
# and row security can stop a cascading delete from seeing those messages.
_QUOTE_PARTS = (
    "quote_line",
    "quote_condition",
    "quote_evidence",
    "quote_approval",
    "quote_version",
)
_TABLES = (
    "capacity_hold",
    "capacity_slot",
    "deposit_link",
    "acceptance",
    "verification_code",
    "handover",
    "owner_notice",
    "inspection",
    "schedule_commitment",
    "quote",
    "sender_bind",
    "case_fact",
    "case_file",
    "enrichment",
    "conversation_event",
    "inbound_message",
    "assistant_reply",
    "conversation",
)


def main() -> None:
    engine = create_engine(_database_url())
    with engine.begin() as connection:
        tenants = connection.execute(text("SELECT slug, tenant_id::text FROM tenant ORDER BY slug")).all()
        if not tenants:
            sys.exit("No tenants are stored.")
        for slug, tenant_id in tenants:
            connection.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            print(slug)
            _clear_quote_parts(connection, tenant_id)
            for table in _TABLES:
                deleted = connection.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                ).rowcount
                print(f"  {table} {deleted}")
            _clear_audit(connection, tenant_id)
        connection.execute(text("ALTER SEQUENCE quote_seq RESTART WITH 1042"))
    print("Next quote id is QD-1042.")
    print("Kept tenants, rate cards, and published policies. Restart the app.")


def _clear_quote_parts(connection, tenant_id: str) -> None:
    for table in _QUOTE_PARTS:
        deleted = connection.execute(
            text(
                f"DELETE FROM {table} WHERE quote_id IN "
                "(SELECT quote_id FROM quote WHERE tenant_id = :tenant_id)"
            ),
            {"tenant_id": tenant_id},
        ).rowcount
        print(f"  {table} {deleted}")


def _clear_audit(connection, tenant_id: str) -> None:
    nested = connection.begin_nested()
    try:
        deleted = connection.execute(
            text("DELETE FROM audit_event WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        ).rowcount
    except SQLAlchemyError:
        nested.rollback()
        print("  audit_event kept (insert-only)")
        return
    nested.commit()
    print(f"  audit_event {deleted}")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL") or _from_dotenv()
    if not url:
        sys.exit("Set DATABASE_URL, or add it to .env.")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def _from_dotenv() -> str | None:
    path = _ROOT / ".env"
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("DATABASE_URL="):
            return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return None


if __name__ == "__main__":
    main()
