"""Administration: residents, week assignment, trash calendar, announcements, settings."""

import sqlite3
from datetime import date

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import auth, clock, frdates, push, rules, trash
from ..auth import admin_required
from ..db import SETTINGS_DEFAULTS, bookings_between, get_db, get_resident, get_setting, set_setting
from . import parse_date

bp = Blueprint("admin", __name__, url_prefix="/admin")

#: Bounds for each editable setting, and its French label on the page.
SETTING_FIELDS = {
    "horizon_weeks": (4, 104, "Réservations ouvertes sur (semaines)"),
    "cancel_deadline_days": (0, 60, "Annulation possible jusqu’à (jours avant la semaine)"),
    "free_week_notice_days": (7, 60, "Rappel des semaines libres (jours à l’avance)"),
}


def _back():
    """Redirect to the admin page, keeping the section anchor if one was sent."""
    return redirect(url_for(".index") + request.form.get("anchor", ""))


@bp.get("")
@admin_required
def index():
    """Show every administration section on one page."""
    db = get_db()
    today = clock.today()
    first = rules.monday_of(today)
    last = rules.last_bookable_week(today, get_setting("horizon_weeks"))
    booked = bookings_between(first, last)
    weeks = []
    week = first
    while week <= last:
        weeks.append({"monday": week, "booking": booked.get(week)})
        week += rules.WEEK
    return render_template(
        "admin/index.html",
        residents=db.execute("SELECT * FROM residents ORDER BY active DESC, name").fetchall(),
        weeks=weeks,
        trash_rules=db.execute("SELECT * FROM trash_rules ORDER BY weekday, label").fetchall(),
        exceptions=db.execute(
            "SELECT e.*, t.label FROM trash_exceptions e JOIN trash_rules t ON t.id = e.rule_id"
            " WHERE e.date >= ? ORDER BY e.date",
            (today.isoformat(),),
        ).fetchall(),
        announcements=db.execute(
            "SELECT * FROM announcements ORDER BY COALESCE(event_date, published_at) DESC"
        ).fetchall(),
        settings={name: get_setting(name) for name in SETTINGS_DEFAULTS},
        setting_fields=SETTING_FIELDS,
        frequencies=trash.FREQUENCIES,
        jours=frdates.JOURS,
    )


# --- Residents --------------------------------------------------------------------

@bp.post("/residents/ajouter")
@admin_required
def add_resident():
    """Register a resident; optionally email them a login link right away."""
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    if not name or "@" not in email:
        flash("Nom et adresse e-mail valides obligatoires.", "erreur")
        return _back()
    db = get_db()
    try:
        with db:
            cur = db.execute(
                "INSERT INTO residents (name, email, apartment, role) VALUES (?, ?, ?, ?)",
                (name, email, request.form.get("apartment", "").strip(),
                 "admin" if request.form.get("is_admin") else "resident"),
            )
    except sqlite3.IntegrityError:
        flash("Cette adresse e-mail est déjà enregistrée.", "erreur")
        return _back()
    if request.form.get("send_link"):
        auth.send_login_link(get_resident(cur.lastrowid))
        flash(f"{name} ajouté(e) ; un lien de connexion a été envoyé.", "ok")
    else:
        flash(f"{name} ajouté(e).", "ok")
    return _back()


def _other_resident(resident_id: int):
    """Return the resident row, refusing unknown ids and the admin's own account."""
    resident = get_resident(resident_id)
    if resident is None:
        abort(404)
    if resident["id"] == g.user["id"]:
        flash("Vous ne pouvez pas modifier votre propre compte ici.", "erreur")
        return None
    return resident


@bp.post("/residents/<int:resident_id>/activer")
@admin_required
def toggle_active(resident_id: int):
    """Deactivate (logs them out, blocks login) or reactivate a resident."""
    resident = _other_resident(resident_id)
    if resident is not None:
        db = get_db()
        with db:
            db.execute("UPDATE residents SET active = 1 - active WHERE id = ?", (resident_id,))
        flash(f"{resident['name']} : compte {'désactivé' if resident['active'] else 'réactivé'}.", "ok")
    return _back()


@bp.post("/residents/<int:resident_id>/role")
@admin_required
def toggle_role(resident_id: int):
    """Grant or remove administrator rights."""
    resident = _other_resident(resident_id)
    if resident is not None:
        new_role = "resident" if resident["role"] == "admin" else "admin"
        db = get_db()
        with db:
            db.execute("UPDATE residents SET role = ? WHERE id = ?", (new_role, resident_id))
        flash(f"{resident['name']} est maintenant {'administrateur' if new_role == 'admin' else 'résident'}.", "ok")
    return _back()


@bp.post("/residents/<int:resident_id>/lien")
@admin_required
def send_link(resident_id: int):
    """Email a login link to a resident (e.g. a new phone)."""
    resident = get_resident(resident_id)
    if resident is None or not resident["active"]:
        abort(404)
    auth.send_login_link(resident)
    flash(f"Lien de connexion envoyé à {resident['email']}.", "ok")
    return _back()


# --- Weeks ------------------------------------------------------------------------

@bp.post("/semaines/attribuer")
@admin_required
def assign_week():
    """Assign a week to a resident, replacing any existing booking.

    The admin is not bound by the horizon or the consecutive-weeks limit.
    """
    monday = parse_date(request.form.get("week_start"))
    if monday.weekday() != 0:
        abort(400, "La semaine doit commencer un lundi.")
    resident = get_resident(request.form.get("resident_id", type=int) or 0)
    if resident is None or not resident["active"]:
        flash("Choisissez un résident.", "erreur")
        return _back()
    db = get_db()
    with db:
        db.execute(
            "INSERT INTO bookings (week_start, resident_id, assigned_by_admin) VALUES (?, ?, 1)"
            " ON CONFLICT (week_start) DO UPDATE SET resident_id = excluded.resident_id,"
            " assigned_by_admin = 1",
            (monday.isoformat(), resident["id"]),
        )
    flash(f"Semaine {frdates.semaine(monday)} attribuée à {resident['name']}.", "ok")
    return _back()


@bp.post("/semaines/liberer")
@admin_required
def free_week():
    """Remove the booking of a week."""
    monday = parse_date(request.form.get("week_start"))
    db = get_db()
    with db:
        db.execute("DELETE FROM bookings WHERE week_start = ?", (monday.isoformat(),))
    flash(f"Semaine {frdates.semaine(monday)} libérée.", "ok")
    return _back()


# --- Trash calendar ---------------------------------------------------------------

@bp.post("/poubelles/ajouter")
@admin_required
def add_trash_rule():
    """Add a recurring pickup (label, weekday, frequency)."""
    label = request.form.get("label", "").strip()
    weekday = request.form.get("weekday", type=int)
    frequency = request.form.get("frequency", "weekly")
    if not label or weekday not in range(7) or frequency not in trash.FREQUENCIES:
        flash("Collecte invalide.", "erreur")
        return _back()
    db = get_db()
    with db:
        db.execute("INSERT INTO trash_rules (label, weekday, frequency) VALUES (?, ?, ?)",
                   (label, weekday, frequency))
    flash(f"Collecte « {label} » ajoutée.", "ok")
    return _back()


@bp.post("/poubelles/<int:rule_id>/supprimer")
@admin_required
def delete_trash_rule(rule_id: int):
    """Delete a recurring pickup and its exceptions."""
    db = get_db()
    with db:
        db.execute("DELETE FROM trash_rules WHERE id = ?", (rule_id,))
    flash("Collecte supprimée.", "ok")
    return _back()


@bp.post("/exceptions/ajouter")
@admin_required
def add_exception():
    """Cancel or move one occurrence of a pickup (e.g. a public holiday)."""
    db = get_db()
    row = db.execute("SELECT * FROM trash_rules WHERE id = ?",
                     (request.form.get("rule_id", type=int),)).fetchone()
    if row is None:
        abort(404)
    day = parse_date(request.form.get("date"))
    moved_raw = request.form.get("moved_to", "").strip()
    moved_to = parse_date(moved_raw) if moved_raw else None
    rule = trash.Rule(row["id"], row["label"], row["weekday"], row["frequency"])
    if not trash.occurs(rule, day):
        flash(f"Il n’y a pas de collecte « {rule.label} » le {frdates.date_longue(day)}.", "erreur")
        return _back()
    if moved_to is not None and abs(moved_to - day) > trash.MAX_MOVE:
        flash("Une collecte ne peut être déplacée que de 31 jours au plus.", "erreur")
        return _back()
    with db:
        db.execute(
            "INSERT INTO trash_exceptions (rule_id, date, moved_to) VALUES (?, ?, ?)"
            " ON CONFLICT (rule_id, date) DO UPDATE SET moved_to = excluded.moved_to",
            (rule.id, day.isoformat(), moved_to.isoformat() if moved_to else None),
        )
    flash("Exception enregistrée.", "ok")
    return _back()


@bp.post("/exceptions/<int:exception_id>/supprimer")
@admin_required
def delete_exception(exception_id: int):
    """Remove an exception, restoring the normal pickup."""
    db = get_db()
    with db:
        db.execute("DELETE FROM trash_exceptions WHERE id = ?", (exception_id,))
    flash("Exception supprimée.", "ok")
    return _back()


# --- Announcements ----------------------------------------------------------------

@bp.post("/annonces/ajouter")
@admin_required
def add_announcement():
    """Publish an announcement; optionally notify every subscribed resident."""
    title = request.form.get("title", "").strip()
    if not title:
        flash("Le titre est obligatoire.", "erreur")
        return _back()
    event_raw = request.form.get("event_date", "").strip()
    event_date = parse_date(event_raw) if event_raw else None
    db = get_db()
    with db:
        db.execute(
            "INSERT INTO announcements (title, body, event_date) VALUES (?, ?, ?)",
            (title, request.form.get("body", "").strip(),
             event_date.isoformat() if event_date else None),
        )
    message = "Annonce publiée."
    if request.form.get("notify"):
        text = f"{title} – {frdates.date_longue(event_date)}" if event_date else title
        reached = sum(
            1 for r in db.execute("SELECT id FROM residents WHERE active = 1").fetchall()
            if push.send_to_resident(r["id"], "Nouvelle information", text, "/infos")
        )
        message += f" {reached} résident(s) notifié(s)."
    flash(message, "ok")
    return _back()


@bp.post("/annonces/<int:announcement_id>/supprimer")
@admin_required
def delete_announcement(announcement_id: int):
    """Delete an announcement."""
    db = get_db()
    with db:
        db.execute("DELETE FROM announcements WHERE id = ?", (announcement_id,))
    flash("Annonce supprimée.", "ok")
    return _back()


# --- Settings and tests -----------------------------------------------------------

@bp.post("/reglages")
@admin_required
def save_settings():
    """Save the booking settings, each clamped to its allowed range."""
    for name, (low, high, _label) in SETTING_FIELDS.items():
        value = request.form.get(name, type=int)
        if value is None or not low <= value <= high:
            flash(f"Valeur invalide pour « {_label} » ({low} à {high}).", "erreur")
            return _back()
        set_setting(name, value)
    flash("Réglages enregistrés.", "ok")
    return _back()


@bp.post("/test-notification")
@admin_required
def test_notification():
    """Send a test push to the admin's own devices."""
    count = push.send_to_resident(g.user["id"], "Test GCCopro",
                                  "Les notifications fonctionnent.", "/admin")
    if count:
        flash(f"Notification envoyée à {count} appareil(s).", "ok")
    else:
        flash("Aucun appareil n’a reçu la notification. Activez-les dans « Mes semaines ».", "erreur")
    return _back()
