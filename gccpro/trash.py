"""Trash pickup calendar: expands recurring rules and exceptions into actual dates.

Pure functions only (no database access), so the logic is easy to test.
"""

from dataclasses import dataclass
from datetime import date, timedelta

#: Allowed values of :attr:`Rule.frequency`, with their French labels.
FREQUENCIES = {
    "weekly": "Toutes les semaines",
    "even_weeks": "Semaines paires",
    "odd_weeks": "Semaines impaires",
}

#: A pickup can be moved at most this far from its normal date.
MAX_MOVE = timedelta(days=31)


@dataclass(frozen=True)
class Rule:
    """A recurring pickup, e.g. "Ordures ménagères" every Tuesday."""

    id: int
    label: str
    weekday: int    # 0 = Monday ... 6 = Sunday
    frequency: str  # a key of FREQUENCIES


@dataclass(frozen=True)
class Exception_:
    """A change to one occurrence of a rule: cancelled, or moved to another date."""

    rule_id: int
    date: date
    moved_to: date | None  # None means the pickup is cancelled


@dataclass(frozen=True, order=True)
class Pickup:
    """One actual pickup on a given date."""

    date: date
    label: str
    rule_id: int


def occurs(rule: Rule, day: date) -> bool:
    """Return True if ``rule`` normally has a pickup on ``day`` (ignoring exceptions)."""
    if day.weekday() != rule.weekday:
        return False
    week = day.isocalendar().week
    if rule.frequency == "even_weeks":
        return week % 2 == 0
    if rule.frequency == "odd_weeks":
        return week % 2 == 1
    return True


def pickups(rules: list[Rule], exceptions: list[Exception_], start: date, end: date) -> list[Pickup]:
    """Return the pickups falling in ``[start, end]``, sorted by date then label.

    Normal occurrences are generated with a margin of :data:`MAX_MOVE` on both
    sides, so that an occurrence moved into the range from outside it is included.
    Exceptions on dates where the rule has no occurrence are ignored.
    """
    changes = {(exc.rule_id, exc.date): exc for exc in exceptions}
    result = []
    day = start - MAX_MOVE
    while day <= end + MAX_MOVE:
        for rule in rules:
            if not occurs(rule, day):
                continue
            change = changes.get((rule.id, day))
            if change is None:
                target = day
            elif change.moved_to is None:
                continue  # cancelled
            else:
                target = change.moved_to
            if start <= target <= end:
                result.append(Pickup(target, rule.label, rule.id))
        day += timedelta(days=1)
    return sorted(result)
