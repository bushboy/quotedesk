"""The rate card in Postgres, read at startup and written on every publish.

A closed database or a missing table never stops the app. Startup keeps the built-in card,
a publish stays in memory, and `reachable` tells the owner page which one happened.
"""

import logging
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from quotedesk.adapters.outbound.persistence.rate_cards import RateCardTables
from quotedesk.domain.services.price import RateCard

_log = logging.getLogger(__name__)


class StoredRateCards:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 1})
        self._tables = RateCardTables()
        self.reachable = False

    def load(self, tenant_id: UUID) -> RateCard | None:
        try:
            with self._engine.begin() as connection:
                card = self._tables.get(connection, tenant_id)
        except SQLAlchemyError:
            self.reachable = False
            _log.info("Rate card source=built-in (database not reachable)")
            return None
        self.reachable = True
        _log.info("Rate card source=%s", "built-in (no row)" if card is None else "rate_card table")
        return card

    def save(self, tenant_id: UUID, card: RateCard) -> bool:
        try:
            with self._engine.begin() as connection:
                self._tables.save(connection, tenant_id, card)
        except SQLAlchemyError:
            self.reachable = False
            _log.warning("Rate card was not saved to the database. It lasts until the app restarts.")
            return False
        self.reachable = True
        return True
