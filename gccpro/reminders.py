"""Daily reminder job, run by DSM Task Scheduler via ``flask send-reminders``.

Sends, at most once each (tracked in ``notification_log``):
- a push to the resident on duty (plus the admins' apartment for fixed-date pickups) and the rest of their apartment when there is a trash pickup tomorrow, with an
  email fallback when they have no push subscription;
- a push to every resident for each unbooked week coming up soon;
- an email to the administrators for each such unbooked week.
"""

from datetime import date, timedelta

from flask import current_app

from . import frdates, mail, push, rules, trash
from .db import booking_owners, fixed_pickups, get_db, get_resident, get_setting, trash_config


def _already_sent(kind: str, resident_id: int, ref: date) -> bool:
    """Return True if this notification was already recorded."""
    return get_db().execute(
        "SELECT 1 FROM notification_log WHERE kind = ? AND resident_id = ? AND ref_date = ?",
        (kind, resident_id, ref.isoformat()),
    ).fetchone() is not None


def _record(kind: str, resident_id: int, ref: date) -> None:
    """Record that a notification was sent."""
    db = get_db()
    with db:
        db.execute(
            "INSERT OR IGNORE INTO notification_log (kind, resident_id, ref_date) VALUES (?, ?, ?)",
            (kind, resident_id, ref.isoformat()),
        )


def household(resident_id: int) -> list:
    """Return the active residents to notify for a booking by ``resident_id``.

    That is every active resident sharing the booker's apartment (compared
    case-insensitively); the booker alone when their apartment is blank.
    """
    booker = get_resident(resident_id)
    apartment = (booker["apartment"] or "").strip()
    if not apartment:
        return [booker]
    return get_db().execute(
        "SELECT * FROM residents WHERE active = 1 AND lower(trim(apartment)) = lower(?)"
        " ORDER BY id",
        (apartment,),
    ).fetchall()


def admin_households() -> list:
    """Return the active residents living in an apartment where an active admin lives."""
    return get_db().execute(
        "SELECT * FROM residents WHERE active = 1 AND trim(apartment) != '' AND lower(trim(apartment)) IN"
        " (SELECT lower(trim(apartment)) FROM residents WHERE active = 1 AND role = 'admin')"
        " ORDER BY id"
    ).fetchall()


def run(today: date, dry_run: bool = False) -> list[str]:
    """Send today's reminders.

    Args:
        today: The day the job runs (reminders concern ``today + 1``).
        dry_run: Report what would be sent without sending or recording anything.

    Returns:
        Human-readable lines describing each notification (for the job log).
    """
    report: list[str] = []
    base_url = current_app.config["BASE_URL"].rstrip("/")
    site = current_app.config["SITE_NAME"]
    owners = booking_owners(today - timedelta(weeks=1), today + timedelta(weeks=12))

    # 1. Trash pickups tomorrow.
    tomorrow = today + timedelta(days=1)
    rule_list, exceptions = trash_config()
    due = trash.pickups(rule_list, exceptions, tomorrow, tomorrow, fixed_pickups())
    labels = [p.label for p in due]
    owner_id = rules.reminder_recipient(tomorrow, owners)
    if labels and owner_id is not None:
        what = ", ".join(labels)
        title = "Poubelles à sortir ce soir"
        body = f"Collecte demain, {frdates.date_courte(tomorrow)} : {what}."
        recipients = household(owner_id)
        if any(p.special for p in due):
            # Special pickups (fixed dates) also concern the admins' apartment.
            known = {r["id"] for r in recipients}
            recipients += [r for r in admin_households() if r["id"] not in known]
        for resident in recipients:
            rid = resident["id"]
            if _already_sent("trash", rid, tomorrow):
                continue
            if dry_run:
                report.append(f"[dry-run] trash -> {resident['name']}: {body}")
                continue
            delivered = push.send_to_resident(rid, title, body, "/")
            channel = "push"
            if delivered == 0:
                if resident["email"]:
                    mail.send_mail(
                        resident["email"],
                        f"{title} – {site}",
                        f"Bonjour {resident['name']},\n\n{body}\n\n{base_url}/\n",
                    )
                    channel = "email"
                else:
                    # Phone-only resident without notifications enabled: nothing to send.
                    channel = "not reached: no push subscription, no email"
            _record("trash", rid, tomorrow)
            report.append(f"trash -> {resident['name']} ({channel}): {body}")
    elif labels and owner_id is None:
        report.append(f"trash pickup tomorrow ({', '.join(labels)}) but nobody booked the week")

    # 2. Unbooked weeks coming up.
    free = rules.free_weeks_to_announce(today, owners, get_setting("free_week_notice_days"))
    db = get_db()
    residents = db.execute("SELECT * FROM residents WHERE active = 1").fetchall()
    for week in free:
        text = f"La semaine {frdates.semaine(week)} n’est pas encore réservée."
        for resident in residents:
            if _already_sent("free_week", resident["id"], week):
                continue
            if dry_run:
                report.append(f"[dry-run] free week -> {resident['name']}: {text}")
                continue
            # Only residents with a working subscription are recorded, so that a
            # resident who enables notifications later still gets the reminder.
            if push.send_to_resident(resident["id"], "Semaine à réserver", text, "/"):
                _record("free_week", resident["id"], week)
                report.append(f"free week -> {resident['name']} (push): {text}")
        for admin in (r for r in residents if r["role"] == "admin" and r["email"]):
            if _already_sent("free_week_admin", admin["id"], week):
                continue
            if dry_run:
                report.append(f"[dry-run] free week -> admin {admin['name']} (email)")
                continue
            mail.send_mail(
                admin["email"],
                f"Semaine non réservée – {site}",
                f"{text}\n\nVous pouvez l’attribuer depuis l’administration : {base_url}/admin\n",
            )
            _record("free_week_admin", admin["id"], week)
            report.append(f"free week -> admin {admin['name']} (email): {text}")
    return report
