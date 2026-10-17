"""Shared fixtures: an app on a temporary database with a fixed "today"."""

import re
from datetime import date

import pytest

from gccpro import create_app, push
from gccpro.db import get_db

#: Wednesday 21 October 2026, ISO week 43.
TODAY = date(2026, 10, 21)


@pytest.fixture
def app(tmp_path):
    """Application with an empty database, in-memory mail and a VAPID key."""
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "DATABASE": str(tmp_path / "test.db"),
        "MAIL_BACKEND": "memory",
        "BASE_URL": "https://copro.test",
        "VAPID_PRIVATE_KEY": push.generate_vapid_private_key(),
        "TODAY": TODAY,
    })
    with app.app_context():
        db = get_db()
        with db:
            db.execute("INSERT INTO residents (id, name, email, apartment, role)"
                       " VALUES (1, 'Admin', 'admin@test.fr', 'Apt 1', 'admin')")
            db.execute("INSERT INTO residents (id, name, email, apartment)"
                       " VALUES (2, 'Alice', 'alice@test.fr', 'Apt 2')")
            db.execute("INSERT INTO residents (id, name, email, apartment)"
                       " VALUES (3, 'Bruno', 'bruno@test.fr', 'Apt 3')")
    yield app


@pytest.fixture
def client(app):
    """Test client for ``app``."""
    return app.test_client()


@pytest.fixture
def outbox(app):
    """List of emails sent through the memory backend."""
    return app.extensions.setdefault("outbox", [])


def csrf(client) -> str:
    """Return the client session's CSRF token (rendering a page with a form creates it).

    ``/connexion`` redirects once logged in, so ``/`` is tried as well.
    """
    for url in ("/connexion", "/"):
        client.get(url)
        with client.session_transaction() as session:
            if "csrf" in session:
                return session["csrf"]
    raise AssertionError("no CSRF token in session")


def login(client, outbox, email: str) -> None:
    """Log ``client`` in as ``email`` through the real email-link flow."""
    token = csrf(client)
    client.post("/connexion", data={"email": email, "csrf_token": token})
    link = re.search(r"https://copro\.test(/connexion/\S+)", outbox[-1].get_content()).group(1)
    client.post(link, data={"csrf_token": csrf(client)})
