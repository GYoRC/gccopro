"""Building information page (announcements, next Assemblée Générale, etc.)."""

from flask import Blueprint, render_template

from .. import clock
from ..auth import login_required
from ..db import get_db

bp = Blueprint("info", __name__)


@bp.get("/infos")
@login_required
def index():
    """Show upcoming dated events first (soonest first), then other announcements."""
    today = clock.today().isoformat()
    db = get_db()
    upcoming = db.execute(
        "SELECT * FROM announcements WHERE event_date >= ? ORDER BY event_date", (today,)
    ).fetchall()
    others = db.execute(
        "SELECT * FROM announcements WHERE event_date IS NULL OR event_date < ?"
        " ORDER BY published_at DESC",
        (today,),
    ).fetchall()
    return render_template("infos.html", upcoming=upcoming, others=others)
