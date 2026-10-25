"""Phone numbers (gccpro.phones), the 003 migration, and login via WhatsApp."""

import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote

import pytest

from conftest import csrf, login
from gccpro import db as gdb
from gccpro import phones, push, reminders
from gccpro.db import get_db

BRUNO_PHONE = "+33612345678"


# --- Pure functions -----------------------------------------------------------------

@pytest.mark.parametrize("raw", ["06 12 34 56 78", "06.12.34.56.78", "0612345678",
                                 "+33 6 12 34 56 78", "+33 06 12 34 56 78", "0033612345678",
                                 "(06) 12-34-56-78"])
def test_normalize_french_formats(raw):
    assert phones.normalize(raw) == BRUNO_PHONE


def test_normalize_foreign_and_invalid():
    assert phones.normalize("+41 79 123 45 67") == "+41791234567"
    for bad in ["", "abc", "12345", "06 12 34", "+0612345678"]:
        with pytest.raises(phones.PhoneError):
            phones.normalize(bad)


def test_display_and_whatsapp_url():
    assert phones.display(BRUNO_PHONE) == "06 12 34 56 78"
    assert phones.display("+41791234567") == "+41791234567"
    assert phones.display(None) == ""
    url = phones.whatsapp_url(BRUNO_PHONE, "Bonjour, voici : https://x.fr/a?b=1")
    assert url.startswith("https://wa.me/33612345678?text=")
    assert unquote(url.split("text=")[1]) == "Bonjour, voici : https://x.fr/a?b=1"


# --- Migration ----------------------------------------------------------------------

def test_migration_003_keeps_data_and_foreign_keys(tmp_path):
    conn = gdb.connect(str(tmp_path / "old.db"))
    # Bring the database to the state before 003, with data referencing residents.
    conn.execute("CREATE TABLE schema_migrations (name TEXT PRIMARY KEY)")
    for name in ("001_init.sql", "002_trash_dates.sql"):
        conn.executescript((gdb.SCHEMA_DIR / name).read_text(encoding="utf-8"))
        with conn:
            conn.execute("INSERT INTO schema_migrations VALUES (?)", (name,))
    with conn:
        conn.execute("INSERT INTO residents (id, name, email) VALUES (7, 'Alice', 'a@x.fr')")
        conn.execute("INSERT INTO bookings (week_start, resident_id) VALUES ('2026-10-26', 7)")
        conn.execute("INSERT INTO push_subscriptions (resident_id, endpoint, p256dh, auth)"
                     " VALUES (7, 'https://p/1', 'k', 'a')")

    assert gdb.migrate(conn) == ["003_phone_login.sql"]

    assert tuple(conn.execute("SELECT name, email, phone FROM residents").fetchone()) == ("Alice", "a@x.fr", None)
    assert conn.execute("SELECT resident_id FROM bookings").fetchone()[0] == 7
    assert conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(sqlite3.IntegrityError):  # FKs still enforced on the rebuilt table
        with conn:
            conn.execute("INSERT INTO bookings (week_start, resident_id) VALUES ('2026-11-02', 99)")
    with pytest.raises(sqlite3.IntegrityError):  # email or phone required
        with conn:
            conn.execute("INSERT INTO residents (name) VALUES ('Nobody')")
    conn.close()


# --- Login with a phone number -------------------------------------------------------

@pytest.fixture
def bruno_has_phone(app):
    """Give Bruno (resident 3) a phone number and no email."""
    with app.app_context():
        db = get_db()
        with db:
            db.execute("UPDATE residents SET phone = ?, email = NULL WHERE id = 3", (BRUNO_PHONE,))


def post_login(client, identifier):
    """Submit the login form."""
    return client.post("/connexion", data={"identifiant": identifier, "csrf_token": csrf(client)})


def test_phone_login_alerts_admin_once(app, client, outbox, bruno_has_phone):
    page = post_login(client, "06 12 34 56 78").get_data(as_text=True)
    assert "WhatsApp" in page and "06 12 34 56 78" in page
    assert [m["To"] for m in outbox] == ["admin@test.fr"]
    assert "Bruno (Apt 3) demande un lien" in outbox[0].get_content()
    post_login(client, "0612345678")   # a second tap within the hour
    assert len(outbox) == 1
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM login_requests").fetchone()[0] == 1


def test_unknown_phone_same_answer_no_alert(app, client, outbox):
    page = post_login(client, "07 00 00 00 00").get_data(as_text=True)
    assert "Demande transmise" in page and outbox == []
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM login_requests").fetchone()[0] == 0


def test_invalid_identifier_is_rejected(client, outbox):
    response = post_login(client, "pas un numéro")
    assert response.status_code == 400
    assert "valide" in response.get_data(as_text=True) and outbox == []


def test_admin_whatsapp_link_logs_resident_in(app, client, outbox, bruno_has_phone):
    post_login(client, "06 12 34 56 78")
    login(client, outbox, "admin@test.fr")
    admin_page = client.get("/admin").get_data(as_text=True)
    assert "Demandes de connexion" in admin_page and "06 12 34 56 78" in admin_page

    page = client.post("/admin/residents/3/whatsapp",
                       data={"csrf_token": csrf(client)}).get_data(as_text=True)
    assert 'href="https://wa.me/33612345678?text=' in page
    path = re.search(r"https://copro\.test(/connexion/[A-Za-z0-9_-]+)", page).group(1)

    # The request is handled; the link lasts about 24 hours.
    assert "Demandes de connexion" not in client.get("/admin").get_data(as_text=True)
    with app.app_context():
        expires = get_db().execute(
            "SELECT expires_at FROM login_tokens ORDER BY id DESC LIMIT 1").fetchone()[0]
    remaining = datetime.strptime(expires, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) \
        - datetime.now(timezone.utc)
    assert timedelta(hours=23) < remaining <= timedelta(hours=24)

    # Bruno opens the link on his phone and is logged in.
    phone = app.test_client()
    phone.post(path, data={"csrf_token": csrf(phone)})
    assert "Calendrier d’entretien" in phone.get("/").get_data(as_text=True)
    with phone.session_transaction() as session:
        assert session["rid"] == 3


def test_admin_adds_and_edits_contacts(app, client, outbox):
    login(client, outbox, "admin@test.fr")
    token = csrf(client)
    sent_before = len(outbox)
    client.post("/admin/residents/ajouter", data={"name": "Chloé", "apartment": "Apt 4",
                                                 "phone": "06 98 76 54 32", "send_link": "1",
                                                 "csrf_token": token})
    page = client.post("/admin/residents/ajouter", data={"name": "Rien", "apartment": "Apt 5",
                                                        "csrf_token": token},
                       follow_redirects=True).get_data(as_text=True)
    assert "au moins une adresse e-mail ou un numéro" in page
    with app.app_context():
        chloe = get_db().execute("SELECT * FROM residents WHERE name = 'Chloé'").fetchone()
        assert chloe["phone"] == "+33698765432" and chloe["email"] is None
    assert len(outbox) == sent_before  # no email to send to

    # Edit: add an email, and refuse a phone already used by someone else.
    client.post(f"/admin/residents/{chloe['id']}/modifier",
                data={"name": "Chloé", "email": "chloe@test.fr", "phone": "0698765432",
                      "csrf_token": token})
    page = client.post("/admin/residents/2/modifier",
                       data={"name": "Alice", "email": "alice@test.fr", "phone": "06 98 76 54 32",
                             "csrf_token": token}, follow_redirects=True).get_data(as_text=True)
    assert "appartient déjà" in page
    with app.app_context():
        row = get_db().execute("SELECT email, phone FROM residents WHERE id = ?", (chloe["id"],)).fetchone()
        assert tuple(row) == ("chloe@test.fr", "+33698765432")
        assert get_db().execute("SELECT phone FROM residents WHERE id = 2").fetchone()[0] is None


def test_login_link_cli_accepts_phone(app, bruno_has_phone):
    result = app.test_cli_runner().invoke(args=["login-link", "06 12 34 56 78"])
    assert result.exit_code == 0 and "/connexion/" in result.output


def test_reminder_for_phone_only_resident_without_push(app, outbox, monkeypatch, bruno_has_phone):
    monkeypatch.setattr(push, "deliver", lambda sub, msg: 201)
    with app.app_context():
        db = get_db()
        with db:
            db.execute("INSERT INTO trash_rules (label, weekday, frequency) VALUES ('Ordures', 1, 'weekly')")
            db.execute("INSERT INTO bookings (week_start, resident_id) VALUES ('2026-10-26', 3)")
        lines = reminders.run(date(2026, 10, 26))
    assert any("Bruno (not reached" in line for line in lines)
    # Only the admin gets emails (unbooked weeks); nothing is attempted for Bruno.
    assert {m["To"] for m in outbox} <= {"admin@test.fr"}
