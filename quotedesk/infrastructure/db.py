"""PostgreSQL access.

This module does not open a connection. `engine` builds a SQLAlchemy engine
and leaves the first connection to the caller.
"""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)
