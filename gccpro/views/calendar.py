"""Calendar page: the upcoming weeks, who is on duty, and booking.

Three views (year by default) share the same per-week data (:func:`week_infos`): a year of twelve
mini-months, a month grid where each row is one Monday-to-Sunday week,
and the list of upcoming weeks. The resident's own upcoming weeks (with the
cancel buttons) are shown under every view.
"""

import sqlite3
from collections import defaultdict
from datetime import date, timedelta

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .. import clock, frdates, rules, trash
from ..auth import login_required
from ..db import bookings_between, get_db, fixed_pickups, get_setting, trash_config
from . import parse_date, safe_back

bp = Blueprint("calendar", __name__)


def week_infos(mondays: list[date], today: date, resident_id: int) -> list[dict]:
    """Return display data for each week starting on one of ``mondays``.

    Each dict has: ``monday``, ``days`` (the 7 dates), ``booking`` (row or None),
    ``mine``, ``past``, ``current``, ``pickups`` (list of :class:`trash.Pickup`),
    ``events`` (``{date: [titles]}``), ``can_book_1``, ``can_book_2`` and
    ``can_cancel`` (resident rule; admins may also cancel from the admin page).
    """
    if not mondays:
        return []
    horizon = get_setting("horizon_weeks")
    deadline_days = get_setting("cancel_deadline_days")
    first, last = mondays[0], mondays[-1]
    this_monday = rules.monday_of(today)

    # Neighbouring weeks are loaded too, so the consecutive-weeks rule sees them.
    booked = bookings_between(first - 2 * rules.WEEK, last + 2 * rules.WEEK)
    owners = {week: row["resident_id"] for week, row in booked.items()}

    rule_list, exceptions = trash_config()
    pickups_by_week = defaultdict(list)
    for pickup in trash.pickups(rule_list, exceptions, first, last + timedelta(days=6),
                                 fixed_pickups()):
        pickups_by_week[rules.monday_of(pickup.date)].append(pickup)

    events = defaultdict(list)
    for row in get_db().execute(
        "SELECT title, event_date FROM announcements WHERE event_date BETWEEN ? AND ?",
        (first.isoformat(), (last + timedelta(days=6)).isoformat()),
    ):
        events[date.fromisoformat(row["event_date"])].append(row["title"])

    def allowed(week: date, count: int) -> bool:
        """Return True if ``resident_id`` may book ``count`` weeks from ``week``."""
        try:
            rules.validate_booking(week, count, resident_id, owners, today, horizon)
            return True
        except rules.BookingError:
            return False

    infos = []
    for week in mondays:
        booking = booked.get(week)
        mine = booking is not None and booking["resident_id"] == resident_id
        days = [week + timedelta(days=i) for i in range(7)]
        infos.append({
            "monday": week,
            "days": days,
            "booking": booking,
            "mine": mine,
            "past": week < this_monday,
            "current": week == this_monday,
            "pickups": pickups_by_week[week],
            "events": {day: events[day] for day in days if day in events},
            "can_book_1": booking is None and allowed(week, 1),
            "can_book_2": booking is None and allowed(week, 2),
            "can_cancel": mine and week >= this_monday and rules.can_cancel(week, today, deadline_days),
            "cancel_deadline": rules.cancel_deadline(week, deadline_days),
        })
    return infos


def month_mondays(year: int, month: int) -> list[date]:
    """Return the Mondays of every week that has at least one day in the month."""
    first_day = date(year, month, 1)
    next_month = date(year + month // 12, month % 12 + 1, 1)
    week = rules.monday_of(first_day)
    mondays = []
    while week < next_month:
        mondays.append(week)
        week += rules.WEEK
    return mondays


#: Years the calendar accepts from the query string; anything else falls back to today.
MIN_YEAR, MAX_YEAR = 2000, 2100


def parse_month(value: str | None, today: date) -> tuple[int, int]:
    """Parse ``YYYY-MM`` from the query string; fall back to today's month."""
    try:
        year, month = (int(part) for part in (value or "").split("-"))
        date(year, month, 1)  # validates the month
        if not MIN_YEAR <= year <= MAX_YEAR:
            raise ValueError(year)
        return year, month
    except ValueError:
        return today.year, today.month


def shift_month(year: int, month: int, delta: int) -> str:
    """Return ``YYYY-MM`` for the month ``delta`` months away."""
    index = year * 12 + (month - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def build_month(today: date, resident_id: int) -> dict:
    """Build the month-grid context from the ``mois`` and ``semaine`` query parameters.

    Returns:
        A dict with ``label`` ("novembre 2026"), ``month`` (YYYY-MM), ``prev``,
        ``next``, ``year_month`` (tuple), ``weeks`` (from :func:`week_infos`) and
        ``selected`` (the info of the chosen week, or None).
    """
    year, month = parse_month(request.args.get("mois"), today)
    weeks = week_infos(month_mondays(year, month), today, resident_id)
    selected = None
    chosen = request.args.get("semaine")
    if chosen:
        try:
            chosen_date = date.fromisoformat(chosen)
        except ValueError:
            chosen_date = None
        selected = next((w for w in weeks if w["monday"] == chosen_date), None)
    return {
        "label": f"{frdates.MOIS[month - 1]} {year}",
        "month": f"{year:04d}-{month:02d}",
        "year_month": (year, month),
        "prev": shift_month(year, month, -1),
        "next": shift_month(year, month, 1),
        "weeks": weeks,
        "selected": selected,
    }


def parse_year(value: str | None, today: date) -> int:
    """Parse the ``annee`` query parameter; fall back to today's year."""
    try:
        year = int(value or "")
        if not MIN_YEAR <= year <= MAX_YEAR:
            raise ValueError(year)
        return year
    except ValueError:
        return today.year


def build_year(today: date, resident_id: int) -> dict:
    """Build the year-view context from the ``annee`` query parameter.

    Returns:
        A dict with ``year``, ``prev``, ``next`` and ``months``: twelve dicts with
        ``number``, ``key`` (YYYY-MM), ``label`` and ``weeks`` (from :func:`week_infos`).
    """
    year = parse_year(request.args.get("annee"), today)
    by_month = {month: month_mondays(year, month) for month in range(1, 13)}
    # One query round for the whole year; weeks shared by two months are reused.
    all_mondays = sorted({monday for mondays in by_month.values() for monday in mondays})
    infos = {info["monday"]: info for info in week_infos(all_mondays, today, resident_id)}
    months = [{
        "number": month,
        "key": f"{year:04d}-{month:02d}",
        "label": frdates.MOIS[month - 1],
        "weeks": [infos[monday] for monday in mondays],
    } for month, mondays in by_month.items()]
    return {"year": year, "prev": year - 1, "next": year + 1, "months": months}


def my_upcoming(today: date, resident_id: int) -> list[dict]:
    """Return the resident's current and future weeks with their cancel status.

    Each dict has ``monday``, ``can_cancel`` and ``deadline`` (last cancel day rule).
    """
    deadline_days = get_setting("cancel_deadline_days")
    rows = get_db().execute(
        "SELECT week_start FROM bookings WHERE resident_id = ? AND week_start >= ?"
        " ORDER BY week_start",
        (resident_id, rules.monday_of(today).isoformat()),
    ).fetchall()
    weeks = []
    for row in rows:
        monday = date.fromisoformat(row["week_start"])
        weeks.append({
            "monday": monday,
            "can_cancel": rules.can_cancel(monday, today, deadline_days),
            "deadline": rules.cancel_deadline(monday, deadline_days),
        })
    return weeks


@bp.get("/")
@login_required
def index():
    """Show the calendar as a year (default), a month grid, or a list (``?vue=``).

    A link with ``mois`` but no ``vue`` (month navigation, week links) means the month grid.
    """
    today = clock.today()
    view = request.args.get("vue") or ("mois" if "mois" in request.args else "annee")
    mine = my_upcoming(today, g.user["id"])
    if view == "liste":
        first = rules.monday_of(today)
        last = rules.last_bookable_week(today, get_setting("horizon_weeks"))
        mondays = []
        week = first
        while week <= last:
            mondays.append(week)
            week += rules.WEEK
        return render_template("calendar.html", view="liste", mine=mine,
                               rows=week_infos(mondays, today, g.user["id"]))
    if view == "mois":
        return render_template("calendar.html", view="mois", today=today, mine=mine,
                               cal=build_month(today, g.user["id"]))
    return render_template("calendar.html", view="annee", today=today, mine=mine,
                           year=build_year(today, g.user["id"]))


@bp.post("/reserver")
@login_required
def book():
    """Book 1 or 2 consecutive weeks for the logged-in resident."""
    first = parse_date(request.form.get("week_start"))
    count = request.form.get("count", type=int, default=1)
    today = clock.today()
    owners = {
        week: row["resident_id"]
        for week, row in bookings_between(first - 3 * rules.WEEK, first + 4 * rules.WEEK).items()
    }
    back = safe_back(url_for(".index"))
    try:
        weeks = rules.validate_booking(
            first, count, g.user["id"], owners, today, get_setting("horizon_weeks")
        )
    except rules.BookingError as exc:
        flash(str(exc), "erreur")
        return redirect(back)

    db = get_db()
    try:
        with db:
            for week in weeks:
                db.execute(
                    "INSERT INTO bookings (week_start, resident_id) VALUES (?, ?)",
                    (week.isoformat(), g.user["id"]),
                )
    except sqlite3.IntegrityError:
        # Someone booked the same week between page load and submit.
        flash("Cette semaine vient d’être réservée par quelqu’un d’autre.", "erreur")
        return redirect(back)

    if len(weeks) == 1:
        flash(f"Semaine {frdates.semaine(weeks[0])} réservée. Merci !", "ok")
    else:
        flash(f"Semaines {frdates.semaine(weeks[0])} et {frdates.semaine(weeks[1])} réservées. Merci !", "ok")
    return redirect(back)
