"""The two businesses this process can start as.

The database `tenant` table is the copy the agent reads when Postgres is up.
These rows are what startup uses when that table is missing, and what the
migration inserts the first time.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


class TenantProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: UUID
    slug: str
    display_name: str
    trade: str
    area: str
    about: str


_AQUASURE = TenantProfile(
    tenant_id=UUID("11111111-1111-4111-8111-111111111111"),
    slug="aquasure",
    display_name="AquaSure",
    trade="water tanks and pumps",
    area="Johannesburg",
    about="AquaSure installs and replaces household water tanks and pumps.",
)
_FRAMEWORKS = TenantProfile(
    tenant_id=UUID("22222222-2222-4222-8222-222222222222"),
    slug="frameworks",
    display_name="FrameWorks",
    trade="carports and sheeting",
    area="Pretoria",
    about="FrameWorks builds carports and replaces sheeting and windows.",
)
CATALOGUE = (_AQUASURE, _FRAMEWORKS)
_BY_SLUG = {profile.slug: profile for profile in CATALOGUE}
_UNKNOWN = "TENANT is aquasure or frameworks."


def known_tenant(slug: str) -> TenantProfile:
    profile = _BY_SLUG.get(slug)
    if profile is None:
        raise ValueError(_UNKNOWN)
    return profile


def unknown_tenant_sentence() -> str:
    return _UNKNOWN


def open_tenant(database_url: str, slug: str) -> tuple[TenantProfile, str, bool]:
    """The business, where it was read from, and whether the database answered.

    A missing row still returns the built-in profile. A closed database does not:
    the third value is false, and the caller must not treat the built-in row as live.
    """
    builtin = known_tenant(slug)
    try:
        loaded = _from_table(database_url, slug)
    except SQLAlchemyError:
        return builtin, "unavailable", False
    if loaded is None:
        return builtin, "built-in", True
    return loaded, "tenant table", True


def resolve_tenant(database_url: str, slug: str) -> tuple[TenantProfile, str]:
    """The active business, and whether it came from the table or the built-in row.

    A missing table or a closed database keeps the built-in row for that slug.
    A row that is present wins, so an edit in the table is what the agent sees.
    """
    profile, source, _reachable = open_tenant(database_url, slug)
    if source == "unavailable":
        return profile, "built-in"
    return profile, source


def _from_table(database_url: str, slug: str) -> TenantProfile | None:
    database = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 1},
    )
    try:
        with database.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT tenant_id, slug, display_name, trade, area, about
                        FROM tenant
                        WHERE slug = :slug
                        """
                    ),
                    {"slug": slug},
                )
                .mappings()
                .first()
            )
    finally:
        database.dispose()
    if row is None:
        return None
    return TenantProfile(
        tenant_id=row["tenant_id"],
        slug=row["slug"],
        display_name=row["display_name"],
        trade=row["trade"],
        area=row["area"],
        about=row["about"],
    )
