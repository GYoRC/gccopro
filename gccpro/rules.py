"""Booking rules for the chores rota. Pure functions; error messages are in French.

Bookings are passed around as ``{monday: resident_id}`` dictionaries.
"""

from datetime import date, timedelta

from . import frdates

MAX_CONSECUTIVE_WEEKS = 2
WEEK = timedelta(weeks=1)


class BookingError(ValueError):
    """A booking or cancellation request that breaks a rule; ``str()`` is user-facing."""


def monday_of(day: date) -> date:
    """Return the Monday of the week containing ``day``."""
    return day - timedelta(days=day.weekday())


def last_bookable_week(today: date, horizon_weeks: int) -> date:
    """Return the Monday of the last week residents may book.

    The current week counts as the first of the ``horizon_weeks`` weeks.
    """
    return monday_of(today) + (horizon_weeks - 1) * WEEK


def validate_booking(
    first_week: date,
    count: int,
    resident_id: int,
    bookings: dict[date, int],
    today: date,
    horizon_weeks: int,
) -> list[date]:
    """Check that a resident may book ``count`` weeks starting at ``first_week``.

    Rules: 1 or 2 weeks at a time, starting on a Monday, not before the current
    week, not after the booking horizon, only free weeks, and never more than
    :data:`MAX_CONSECUTIVE_WEEKS` consecutive weeks for the same resident
    (including weeks they already hold).

    Returns:
        The Mondays of the weeks to book.

    Raises:
        BookingError: If any rule is broken.
    """
    if count not in (1, 2):
        raise BookingError("Vous pouvez réserver 1 ou 2 semaines à la fois.")
    if first_week.weekday() != 0:
        raise BookingError("Une réservation commence toujours un lundi.")

    weeks = [first_week + i * WEEK for i in range(count)]
    last = last_bookable_week(today, horizon_weeks)
    for week in weeks:
        if week < monday_of(today):
            raise BookingError("Cette semaine est déjà passée.")
        if week > last:
            raise BookingError(
                f"Les réservations sont ouvertes jusqu’à la semaine {frdates.semaine(last)}."
            )
        if week in bookings:
            raise BookingError(f"La semaine {frdates.semaine(week)} est déjà réservée.")

    # Length of the run of consecutive weeks this resident would hold.
    own = {week for week, owner in bookings.items() if owner == resident_id} | set(weeks)
    run = len(weeks)
    week = weeks[0] - WEEK
    while week in own:
        run += 1
        week -= WEEK
    week = weeks[-1] + WEEK
    while week in own:
        run += 1
        week += WEEK
    if run > MAX_CONSECUTIVE_WEEKS:
        raise BookingError(
            f"Vous ne pouvez pas réserver plus de {MAX_CONSECUTIVE_WEEKS} semaines consécutives."
        )
    return weeks


def cancel_deadline(week_start: date, deadline_days: int) -> date:
    """Return the last day on which a resident may cancel the week ``week_start``."""
    return week_start - timedelta(days=deadline_days)


def can_cancel(week_start: date, today: date, deadline_days: int) -> bool:
    """Return True if a resident (not the admin) may still cancel ``week_start``."""
    return today <= cancel_deadline(week_start, deadline_days)


def reminder_recipient(pickup_day: date, bookings: dict[date, int]) -> int | None:
    """Return who must take the trash out for a pickup on ``pickup_day``.

    The bins go out the evening before, so the responsible resident is the one
    on duty the day before the pickup: for a Monday pickup, that is the person
    whose week ends on the Sunday.
    """
    return bookings.get(monday_of(pickup_day - timedelta(days=1)))


def free_weeks_to_announce(today: date, bookings: dict[date, int], notice_days: int) -> list[date]:
    """Return unbooked weeks starting after the current week and within ``notice_days``."""
    first = monday_of(today) + WEEK
    last = monday_of(today + timedelta(days=notice_days))
    weeks = []
    week = first
    while week <= last:
        if week not in bookings:
            weeks.append(week)
        week += WEEK
    return weeks
