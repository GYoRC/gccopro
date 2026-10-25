"""SQLite access: per-request connections, schema migrations and shared queries."""

import sqlite3
from datetime import date
from pathlib import Path

from flask import Flask, current_app, g

from .trash import Exception_, FixedPickup, Rule

SCHEMA_DIR = Path(__file__).parent / "schema"

#: Default values for the admin-editable settings (stored as text in `settings`).
SETTINGS_DEFAULTS = {
    "horizon_weeks": 26,          # how many weeks ahead residents can book
    "cancel_deadline_days": 7,    # residents cannot cancel later than this before the week
    "free_week_notice_days": 14,  # announce unbooked weeks starting within this many days
}


def connect(path: str) -> sqlite3.Connection:
    """Open a connection with the pragmas the app relies on.

    Args:
        path: Filesystem path of the database file.
    """
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_db() -> sqlite3.Connection:
    """Return the connection bound to the current request or CLI context."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc: BaseException | None = None) -> None:
    """Close the context's connection, if one was opened."""
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply every ``schema/NNN_*.sql`` file not yet recorded, in name order.

    Returns:
        The names of the files applied during this call.
    """
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
    done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for path in sorted(SCHEMA_DIR.glob("*.sql")):
        if path.name in done:
            continue
        # executescript commits on its own; the bookkeeping row follows immediately.
        conn.executescript(path.read_text(encoding="utf-8"))
        with conn:
            conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (path.name,))
        applied.append(path.name)
    return applied


def init_app(app: Flask) -> None:
    """Create the database if needed, bring its schema up to date, register teardown."""
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(app.config["DATABASE"])
    try:
        migrate(conn)
    finally:
        conn.close()
    app.teardown_appcontext(close_db)


# --- Settings -------------------------------------------------------------------

def get_setting(name: str) -> int:
    """Return an integer setting, falling back to :data:`SETTINGS_DEFAULTS`."""
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (name,)).fetchone()
    return int(row["value"]) if row else SETTINGS_DEFAULTS[name]


def set_setting(name: str, value: int) -> None:
    """Store an integer setting; ``name`` must be a key of :data:`SETTINGS_DEFAULTS`."""
    if name not in SETTINGS_DEFAULTS:
        raise KeyError(name)
    db = get_db()
    with db:
        db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (name, str(int(value))),
        )


# --- Shared queries -------------------------------------------------------------

def bookings_between(start: date, end: date) -> dict[date, sqlite3.Row]:
    """Return bookings whose week starts in ``[start, end]``, keyed by Monday.

    Each row carries ``resident_id``, ``name``, ``apartment`` and ``assigned_by_admin``.
    """
    rows = get_db().execute(
        "SELECT b.week_start, b.resident_id, b.assigned_by_admin, r.name, r.apartment"
        " FROM bookings b JOIN residents r ON r.id = b.resident_id"
        " WHERE b.week_start BETWEEN ? AND ?",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    return {date.fromisoformat(row["week_start"]): row for row in rows}


def booking_owners(start: date, end: date) -> dict[date, int]:
    """Return ``{monday: resident_id}`` for weeks starting in ``[start, end]``."""
    return {week: row["resident_id"] for week, row in bookings_between(start, end).items()}


def trash_config() -> tuple[list[Rule], list[Exception_]]:
    """Load all trash rules and exceptions as :mod:`gccpro.trash` value objects."""
    db = get_db()
    rules = [
        Rule(row["id"], row["label"], row["weekday"], row["frequency"])
        for row in db.execute("SELECT * FROM trash_rules ORDER BY weekday, label")
    ]
    exceptions = [
        Exception_(
            row["rule_id"],
            date.fromisoformat(row["date"]),
            date.fromisoformat(row["moved_to"]) if row["moved_to"] else None,
        )
        for row in db.execute("SELECT * FROM trash_exceptions")
    ]
    return rules, exceptions


def fixed_pickups() -> list[FixedPickup]:
    """Load the fixed-date pickups as :class:`gccpro.trash.FixedPickup` objects."""
    return [
        FixedPickup(date.fromisoformat(row["date"]), row["label"])
        for row in get_db().execute("SELECT * FROM trash_dates ORDER BY date")
    ]


def get_resident(resident_id: int) -> sqlite3.Row | None:
    """Return the resident row with ``resident_id``, or None."""
    return get_db().execute("SELECT * FROM residents WHERE id = ?", (resident_id,)).fetchone()
