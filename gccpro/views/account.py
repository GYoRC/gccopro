"""Login by email link, logout, and the resident's own weeks page."""

from datetime import date

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template,
                   request, session, url_for)

from .. import auth, clock, frdates, push, rules
from ..auth import login_required
from ..db import get_db, get_setting
from . import parse_date, safe_back
from .calendar import build_month

bp = Blueprint("account", __name__)


@bp.route("/connexion", methods=["GET", "POST"])
def login():
    """Ask for an email address and send a login link if it belongs to a resident.

    The response is identical whether or not the address is known, so the form
    cannot be used to discover who lives in the building.
    """
    if request.method == "GET":
        if g.user is not None:
            return redirect(url_for("calendar.index"))
        return render_template("login.html")

    email = request.form.get("email", "").strip()
    ip = request.remote_addr or "?"
    if email and auth.allow_login_request(email, ip):
        resident = get_db().execute(
            "SELECT * FROM residents WHERE email = ? AND active = 1", (email,)
        ).fetchone()
        if resident is not None:
            auth.send_login_link(resident)
    return render_template("login_sent.html", email=email)


@bp.get("/connexion/<token>")
def login_confirm(token: str):
    """Show a confirmation button instead of logging in on GET.

    Email security scanners open links automatically; requiring a POST keeps
    them from using up the single-use token.
    """
    return render_template("login_confirm.html", token=token)


@bp.post("/connexion/<token>")
def login_finish(token: str):
    """Consume the token and open a session."""
    resident_id = auth.consume_login_token(token)
    if resident_id is None:
        flash("Ce lien n’est plus valable. Demandez-en un nouveau.", "erreur")
        return redirect(url_for(".login"))
    auth.log_in(resident_id)
    return redirect(url_for("calendar.index"))


@bp.post("/deconnexion")
def logout():
    """End the session."""
    session.clear()
    flash("Vous êtes déconnecté.", "ok")
    return redirect(url_for(".login"))


@bp.get("/mes-semaines")
@login_required
def my_weeks():
    """List the resident's upcoming weeks and the notification settings."""
    today = clock.today()
    deadline_days = get_setting("cancel_deadline_days")
    rows = get_db().execute(
        "SELECT week_start FROM bookings WHERE resident_id = ? AND week_start >= ?"
        " ORDER BY week_start",
        (g.user["id"], rules.monday_of(today).isoformat()),
    ).fetchall()
    weeks = []
    for row in rows:
        monday = date.fromisoformat(row["week_start"])
        weeks.append({
            "monday": monday,
            "can_cancel": rules.can_cancel(monday, today, deadline_days),
            "deadline": rules.cancel_deadline(monday, deadline_days),
        })
    vapid_key = current_app.config["VAPID_PRIVATE_KEY"]
    return render_template(
        "my_weeks.html",
        weeks=weeks,
        today=today,
        cal=build_month(today, g.user["id"]),
        vapid_public_key=push.vapid_public_key(vapid_key) if vapid_key else "",
    )


@bp.post("/annuler")
@login_required
def cancel():
    """Cancel one of the resident's weeks (admins may cancel any week, any time)."""
    monday = parse_date(request.form.get("week_start"))
    db = get_db()
    row = db.execute("SELECT resident_id FROM bookings WHERE week_start = ?",
                     (monday.isoformat(),)).fetchone()
    if row is None:
        abort(404)
    is_admin = g.user["role"] == "admin"
    if row["resident_id"] != g.user["id"] and not is_admin:
        abort(403)
    if not is_admin and not rules.can_cancel(monday, clock.today(), get_setting("cancel_deadline_days")):
        flash("Il est trop tard pour annuler cette semaine. Contactez l’administrateur.", "erreur")
        return redirect(safe_back(url_for(".my_weeks")))
    with db:
        db.execute("DELETE FROM bookings WHERE week_start = ?", (monday.isoformat(),))
    flash(f"Semaine {frdates.semaine(monday)} annulée.", "ok")
    return redirect(safe_back(url_for(".my_weeks")))
