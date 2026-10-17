"""Flask blueprints, one module per area of the site."""

from datetime import date
from urllib.parse import urlsplit

from flask import abort, request


def parse_date(value: str | None) -> date:
    """Parse an ISO date sent by a form, or abort with 400 if it is invalid."""
    try:
        return date.fromisoformat(value or "")
    except ValueError:
        abort(400, "Date invalide.")


def safe_back(default: str) -> str:
    """Return the referring page's path (same host only) so forms can return to it.

    Only the path and query are kept, so a forged Referer cannot redirect to
    another site. Falls back to ``default``.
    """
    referrer = urlsplit(request.referrer or "")
    if referrer.netloc and referrer.netloc == request.host and referrer.path.startswith("/"):
        return referrer.path + (f"?{referrer.query}" if referrer.query else "")
    return default
