"""Installable-app support: service worker, web manifest, push subscriptions."""

from flask import Blueprint, abort, current_app, g, jsonify, request, send_from_directory, url_for

from ..auth import login_required
from ..db import get_db

bp = Blueprint("pwa", __name__)


@bp.get("/sw.js")
def service_worker():
    """Serve the service worker from the site root so its scope covers every page."""
    response = send_from_directory(current_app.static_folder, "sw.js", max_age=0)
    response.headers["Content-Type"] = "text/javascript; charset=utf-8"
    return response


@bp.get("/manifest.webmanifest")
def manifest():
    """Describe the app for "Add to home screen" (required for push on iPhone)."""
    response = jsonify({
        "name": current_app.config["SITE_NAME"],
        "short_name": current_app.config["SITE_SHORT_NAME"],
        "description": "Calendrier d’entretien de l’immeuble",
        "lang": "fr",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f6f7f9",
        "theme_color": "#2f5d8a",
        "icons": [
            {"src": url_for("static", filename="icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": url_for("static", filename="icon-512.png"), "sizes": "512x512", "type": "image/png"},
        ],
    })
    response.mimetype = "application/manifest+json"
    return response


@bp.post("/push/abonnement")
@login_required
def subscribe():
    """Store (or move to this resident) a browser push subscription.

    Expects the JSON produced by ``PushSubscription.toJSON()``.
    """
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint", "")
    keys = data.get("keys") or {}
    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        abort(400)
    db = get_db()
    with db:
        db.execute(
            "INSERT INTO push_subscriptions (resident_id, endpoint, p256dh, auth) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (endpoint) DO UPDATE SET resident_id = excluded.resident_id,"
            " p256dh = excluded.p256dh, auth = excluded.auth",
            (g.user["id"], endpoint, keys["p256dh"], keys["auth"]),
        )
    return jsonify(ok=True)


@bp.post("/push/desabonnement")
@login_required
def unsubscribe():
    """Forget a push subscription of the logged-in resident."""
    endpoint = (request.get_json(silent=True) or {}).get("endpoint", "")
    db = get_db()
    with db:
        db.execute("DELETE FROM push_subscriptions WHERE endpoint = ? AND resident_id = ?",
                   (endpoint, g.user["id"]))
    return jsonify(ok=True)
