"""Login by link (email or WhatsApp via an admin), logout, and the resident's profile page."""

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template,
                   request, session, url_for)

from .. import auth, clock, frdates, phones, push, rules
from ..auth import login_required
from ..db import get_db, get_setting
from . import parse_date, safe_back

bp = Blueprint("account", __name__)


@bp.route("/connexion", methods=["GET", "POST"])
def login():
    """Ask for an email address or a phone number and start the matching login flow.

    - Email: a login link is emailed to the resident.
    - Phone: the admins are alerted and forward a link on WhatsApp.

    The response is identical whether or not the email or number is known, so
    the form cannot be used to discover who lives in the building.
    """
    if request.method == "GET":
        if g.user is not None:
            return redirect(url_for("calendar.index"))
        return render_template("login.html")

    identifier = request.form.get("identifiant", "").strip()
    if "@" in identifier:
        kind, value = "email", identifier
    else:
        try:
            kind, value = "phone", phones.normalize(identifier)
        except phones.PhoneError:
            flash("Saisissez une adresse e-mail ou un numéro de téléphone valide.", "erreur")
            return render_template("login.html", identifier=identifier), 400

    ip = request.remote_addr or "?"
    if auth.allow_login_request(value, ip):
        resident = get_db().execute(
            f"SELECT * FROM residents WHERE {kind} = ? AND active = 1", (value,)
        ).fetchone()
        if resident is not None:
            if kind == "email":
                auth.send_login_link(resident)
            else:
                auth.request_whatsapp_link(resident)
    shown = value if kind == "email" else phones.display(value)
    return render_template("login_sent.html", kind=kind, identifier=shown)


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


@bp.get("/profil")
@login_required
def profile():
    """Show the resident's details, the notification settings and the logout button."""
    vapid_key = current_app.config["VAPID_PRIVATE_KEY"]
    phone = g.user["phone"]
    return render_template(
        "profile.html",
        phone=phones.display(phone) if phone else "",
        vapid_public_key=push.vapid_public_key(vapid_key) if vapid_key else "",
    )


@bp.get("/mes-semaines")
@login_required
def my_weeks():
    """Old address of the page, now merged into the calendar; kept for old links."""
    return redirect(url_for("calendar.index"))


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
        return redirect(safe_back(url_for("calendar.index")))
    with db:
        db.execute("DELETE FROM bookings WHERE week_start = ?", (monday.isoformat(),))
    flash(f"Semaine {frdates.semaine(monday)} annulée.", "ok")
    return redirect(safe_back(url_for("calendar.index")))
