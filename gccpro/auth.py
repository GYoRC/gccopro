"""Authentication by one-time email link, session handling and CSRF protection."""

import functools
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta

from flask import Flask, abort, current_app, g, redirect, request, session, url_for

from . import clock, mail
from .db import get_db

#: How long a login link stays valid.
TOKEN_LIFETIME = timedelta(minutes=15)


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest stored instead of the raw token."""
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_login_token(resident_id: int) -> str:
    """Create and store a single-use login token for ``resident_id``; return it."""
    token = secrets.token_urlsafe(32)
    expires = clock.iso_utc(clock.utcnow() + TOKEN_LIFETIME)
    db = get_db()
    with db:
        db.execute(
            "INSERT INTO login_tokens (token_hash, resident_id, expires_at) VALUES (?, ?, ?)",
            (hash_token(token), resident_id, expires),
        )
    return token


def consume_login_token(token: str) -> int | None:
    """Mark a valid, unused, unexpired token as used and return its resident id.

    Returns None for unknown, used or expired tokens, or inactive residents.
    """
    now = clock.iso_utc(clock.utcnow())
    db = get_db()
    with db:
        row = db.execute(
            "SELECT t.id, t.resident_id FROM login_tokens t"
            " JOIN residents r ON r.id = t.resident_id"
            " WHERE t.token_hash = ? AND t.used_at IS NULL AND t.expires_at > ? AND r.active = 1",
            (hash_token(token), now),
        ).fetchone()
        if row is None:
            return None
        db.execute("UPDATE login_tokens SET used_at = ? WHERE id = ?", (now, row["id"]))
        # Housekeeping: drop tokens that can no longer be used.
        db.execute("DELETE FROM login_tokens WHERE expires_at <= ?", (now,))
    return row["resident_id"]


def send_login_link(resident) -> None:
    """Email a fresh login link to ``resident`` (a residents row)."""
    token = create_login_token(resident["id"])
    link = current_app.config["BASE_URL"].rstrip("/") + url_for("account.login_confirm", token=token)
    mail.send_mail(
        resident["email"],
        "Votre lien de connexion – GCCopro",
        f"Bonjour {resident['name']},\n\n"
        f"Voici votre lien de connexion au calendrier d’entretien de l’immeuble "
        f"(valable 15 minutes, utilisable une seule fois) :\n\n{link}\n\n"
        "Si vous n’avez pas demandé ce lien, vous pouvez ignorer ce message.\n",
    )


def log_in(resident_id: int) -> None:
    """Start a fresh, long-lived session for ``resident_id``."""
    session.clear()  # prevents session fixation
    session.permanent = True
    session["rid"] = resident_id


class RateLimiter:
    """In-memory sliding-window limiter; enough for a single Waitress process."""

    def __init__(self, limit: int, window_seconds: float):
        """Allow ``limit`` hits per key within ``window_seconds``."""
        self.limit = limit
        self.window = window_seconds
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """Record a hit for ``key`` and return False if it exceeds the limit."""
        now = time.monotonic()
        hits = self.hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


def allow_login_request(email: str, ip: str) -> bool:
    """Apply the login-link limit: 5 requests per 15 minutes per address and per IP."""
    limiter: RateLimiter = current_app.extensions["login_limiter"]
    # Both keys are always counted, so a burst on one address still counts for the IP.
    ip_ok = limiter.allow("ip:" + ip)
    email_ok = limiter.allow("email:" + email.lower())
    return ip_ok and email_ok


# --- Request hooks and decorators ---------------------------------------------------

def csrf_token() -> str:
    """Return the session's CSRF token, creating it on first use."""
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def _load_user() -> None:
    """Expose the logged-in, active resident as ``g.user`` (or None)."""
    g.user = None
    rid = session.get("rid")
    if rid is not None:
        row = get_db().execute(
            "SELECT * FROM residents WHERE id = ? AND active = 1", (rid,)
        ).fetchone()
        if row is None:
            session.pop("rid", None)  # deactivated or deleted
        g.user = row


def _check_csrf() -> None:
    """Reject state-changing requests without the session's CSRF token.

    Forms send it as ``csrf_token``; ``static/app.js`` sends it as ``X-CSRF-Token``.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf", "")
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, "Jeton de sécurité invalide. Rechargez la page et réessayez.")


def login_required(view):
    """Redirect anonymous visitors to the login page."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("account.login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """Allow only logged-in administrators (403 for other residents)."""
    @functools.wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def init_app(app: Flask) -> None:
    """Register the user loader, CSRF check, rate limiter and template helpers."""
    app.extensions["login_limiter"] = RateLimiter(limit=5, window_seconds=15 * 60)
    app.before_request(_load_user)
    app.before_request(_check_csrf)

    @app.context_processor
    def inject():
        """Make the CSRF token and current user available to every template."""
        return {"csrf_token": csrf_token, "current_user": g.get("user")}
