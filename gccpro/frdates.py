"""French date formatting without relying on system locales (unreliable on DSM)."""

from datetime import date, timedelta

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _jour(day: date) -> str:
    """Return the day number as written in French ("1er" for the first of the month)."""
    return "1er" if day.day == 1 else str(day.day)


def date_longue(day: date) -> str:
    """Format as "mardi 20 octobre 2026"."""
    return f"{JOURS[day.weekday()]} {_jour(day)} {MOIS[day.month - 1]} {day.year}"


def date_courte(day: date) -> str:
    """Format as "mardi 20 octobre" (no year)."""
    return f"{JOURS[day.weekday()]} {_jour(day)} {MOIS[day.month - 1]}"


def iso_longue(value: str) -> str:
    """Format an ISO date string (as stored in SQLite) like :func:`date_longue`."""
    return date_longue(date.fromisoformat(value))


def semaine(monday: date) -> str:
    """Format the week starting ``monday`` as "du 19 au 25 octobre 2026".

    The month and year are repeated only when the week spans two of them.
    """
    sunday = monday + timedelta(days=6)
    end = f"{_jour(sunday)} {MOIS[sunday.month - 1]} {sunday.year}"
    if monday.year != sunday.year:
        start = f"{_jour(monday)} {MOIS[monday.month - 1]} {monday.year}"
    elif monday.month != sunday.month:
        start = f"{_jour(monday)} {MOIS[monday.month - 1]}"
    else:
        start = _jour(monday)
    return f"du {start} au {end}"
