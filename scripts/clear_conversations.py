"""Clear conversations, quotes, and cases so a test can start from scratch.

Deletes every tenant's chats, messages, cases, quotes, bookings, and handovers.
Keeps the tenant directory, rate cards, and published policy ids. Audit rows are
insert-only and stay.

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
_TABLES = (
    "capacity_hold",
    "capacity_slot",
    "deposit_link",
    "acceptance",
    "verification_code",
    "handover",
    "schedule_commitment",
    "quote",
    "sender_bind",
    "case_file",
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
