"""Trash pickup expansion (gccpro.trash) and French dates (gccpro.frdates)."""

from datetime import date

from gccpro import frdates
from gccpro.trash import Exception_, Pickup, Rule, pickups

TUESDAY_WEEKLY = Rule(1, "Ordures ménagères", 1, "weekly")
FRIDAY_EVEN = Rule(2, "Tri sélectif", 4, "even_weeks")
FRIDAY_ODD = Rule(3, "Verre", 4, "odd_weeks")


def test_weekly_and_parity():
    # 19–25 Oct 2026 is ISO week 43 (odd); 26 Oct–1 Nov is week 44 (even).
    result = pickups([TUESDAY_WEEKLY, FRIDAY_EVEN, FRIDAY_ODD], [], date(2026, 10, 19), date(2026, 11, 1))
    assert result == [
        Pickup(date(2026, 10, 20), "Ordures ménagères", 1),
        Pickup(date(2026, 10, 23), "Verre", 3),
        Pickup(date(2026, 10, 27), "Ordures ménagères", 1),
        Pickup(date(2026, 10, 30), "Tri sélectif", 2),
    ]


def test_cancelled_and_moved():
    exceptions = [
        Exception_(1, date(2026, 10, 20), None),               # cancelled
        Exception_(1, date(2026, 10, 27), date(2026, 10, 28)),  # moved one day
    ]
    result = pickups([TUESDAY_WEEKLY], exceptions, date(2026, 10, 19), date(2026, 11, 1))
    assert [p.date for p in result] == [date(2026, 10, 28)]


def test_moved_into_range_from_outside():
    exceptions = [Exception_(1, date(2026, 11, 3), date(2026, 10, 31))]
    result = pickups([TUESDAY_WEEKLY], exceptions, date(2026, 10, 29), date(2026, 11, 1))
    assert [p.date for p in result] == [date(2026, 10, 31)]


def test_exception_on_non_pickup_day_is_ignored():
    exceptions = [Exception_(1, date(2026, 10, 21), None)]
    result = pickups([TUESDAY_WEEKLY], exceptions, date(2026, 10, 19), date(2026, 10, 25))
    assert [p.date for p in result] == [date(2026, 10, 20)]


def test_french_dates():
    assert frdates.date_longue(date(2026, 10, 20)) == "mardi 20 octobre 2026"
    assert frdates.date_courte(date(2026, 11, 1)) == "dimanche 1er novembre"
    assert frdates.semaine(date(2026, 10, 19)) == "du 19 au 25 octobre 2026"
    assert frdates.semaine(date(2026, 10, 26)) == "du 26 octobre au 1er novembre 2026"
    assert frdates.semaine(date(2026, 12, 28)) == "du 28 décembre 2026 au 3 janvier 2027"
