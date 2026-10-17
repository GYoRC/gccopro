"""Single source of "now" and "today" for the application, in the building's time zone."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app

#: The building is in France; every calendar date is interpreted in this zone.
PARIS = ZoneInfo("Europe/Paris")


def today() -> date:
    """Return today's date in Paris, or the ``TODAY`` override when configured."""
    fixed = current_app.config.get("TODAY")
    if fixed is not None:
        return fixed
    return datetime.now(PARIS).date()


def utcnow() -> datetime:
    """Return the current time as an aware UTC datetime (used for token expiry)."""
    return datetime.now(timezone.utc)


def iso_utc(moment: datetime) -> str:
    """Format an aware datetime as a sortable UTC string for storage in SQLite."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
