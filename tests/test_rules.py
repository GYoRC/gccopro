"""Booking rules (gccpro.rules)."""

from datetime import date, timedelta

import pytest

from gccpro.rules import (BookingError, can_cancel, free_weeks_to_announce, last_bookable_week,
                          monday_of, reminder_recipient, validate_booking)

TODAY = date(2026, 10, 21)          # Wednesday
THIS_MONDAY = date(2026, 10, 19)
NEXT = date(2026, 10, 26)


def mondays(*offsets):
    """Return the Mondays ``offsets`` weeks after THIS_MONDAY."""
    return [THIS_MONDAY + timedelta(weeks=n) for n in offsets]


def test_monday_of():
    assert monday_of(TODAY) == THIS_MONDAY
    assert monday_of(THIS_MONDAY) == THIS_MONDAY
    assert monday_of(date(2026, 10, 25)) == THIS_MONDAY  # Sunday


def test_book_one_and_two_weeks():
    assert validate_booking(NEXT, 1, 2, {}, TODAY, 26) == [NEXT]
    assert validate_booking(NEXT, 2, 2, {}, TODAY, 26) == mondays(1, 2)


def test_current_week_is_bookable_but_not_past_weeks():
    assert validate_booking(THIS_MONDAY, 1, 2, {}, TODAY, 26) == [THIS_MONDAY]
    with pytest.raises(BookingError, match="passée"):
        validate_booking(date(2026, 10, 12), 1, 2, {}, TODAY, 26)


@pytest.mark.parametrize("count", [0, 3])
def test_only_one_or_two_weeks(count):
    with pytest.raises(BookingError, match="1 ou 2"):
        validate_booking(NEXT, count, 2, {}, TODAY, 26)


def test_must_start_on_monday():
    with pytest.raises(BookingError, match="lundi"):
        validate_booking(date(2026, 10, 27), 1, 2, {}, TODAY, 26)


def test_horizon():
    last = last_bookable_week(TODAY, 4)
    assert last == mondays(3)[0]
    assert validate_booking(last, 1, 2, {}, TODAY, 4)
    with pytest.raises(BookingError, match="ouvertes jusqu"):
        validate_booking(last, 2, 2, {}, TODAY, 4)


def test_week_taken():
    with pytest.raises(BookingError, match="déjà réservée"):
        validate_booking(NEXT, 1, 2, {NEXT: 3}, TODAY, 26)
    # Second week of a 2-week request taken by someone else.
    with pytest.raises(BookingError, match="déjà réservée"):
        validate_booking(NEXT, 2, 2, {mondays(2)[0]: 3}, TODAY, 26)


def test_no_more_than_two_consecutive_weeks():
    w1, w2, w3 = mondays(1, 2, 3)
    with pytest.raises(BookingError, match="consécutives"):
        validate_booking(w3, 1, 2, {w1: 2, w2: 2}, TODAY, 26)
    with pytest.raises(BookingError, match="consécutives"):
        validate_booking(w1, 1, 2, {w2: 2, w3: 2}, TODAY, 26)
    with pytest.raises(BookingError, match="consécutives"):
        validate_booking(w2, 2, 2, {w1: 2}, TODAY, 26)
    # Filling a one-week gap between two of one's own weeks makes a run of 3.
    with pytest.raises(BookingError, match="consécutives"):
        validate_booking(w2, 1, 2, {w1: 2, w3: 2}, TODAY, 26)


def test_consecutive_rule_ignores_other_residents_and_gaps():
    w1, w2, w3, w4 = mondays(1, 2, 3, 4)
    assert validate_booking(w3, 1, 2, {w1: 3, w2: 3}, TODAY, 26) == [w3]
    assert validate_booking(w3, 2, 2, {w1: 2}, TODAY, 26) == [w3, w4]


def test_cancel_deadline():
    assert can_cancel(NEXT, date(2026, 10, 19), 7)       # exactly 7 days before
    assert not can_cancel(NEXT, date(2026, 10, 20), 7)
    assert can_cancel(NEXT, date(2026, 10, 26), 0)       # deadline 0: until the Monday


def test_reminder_recipient_uses_day_before():
    w0, w1 = mondays(0, 1)
    bookings = {w0: 2, w1: 3}
    assert reminder_recipient(date(2026, 10, 20), bookings) == 2   # Tuesday pickup
    assert reminder_recipient(date(2026, 10, 25), bookings) == 2   # Sunday pickup
    # Monday pickup: bins go out on Sunday, the previous week's resident.
    assert reminder_recipient(date(2026, 10, 26), bookings) == 2
    assert reminder_recipient(date(2026, 10, 27), bookings) == 3
    assert reminder_recipient(date(2026, 11, 3), bookings) is None


def test_free_weeks_to_announce():
    w1, w2, w3 = mondays(1, 2, 3)
    # Within 14 days of Wednesday 21 Oct: weeks of 26 Oct and 2 Nov (not the current week).
    assert free_weeks_to_announce(TODAY, {}, 14) == [w1, w2]
    assert free_weeks_to_announce(TODAY, {w1: 2}, 14) == [w2]
    assert w3 not in free_weeks_to_announce(TODAY, {}, 14)
