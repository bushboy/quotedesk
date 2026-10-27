"""Uvicorn entry: quotedesk.infrastructure.main:create_app.

Importing this module does not build the app or read settings.
"""

from quotedesk.infrastructure.container import create_app as build_app
from quotedesk.infrastructure.config import Settings


def create_app(settings: Settings | None = None):
    return build_app(settings)
