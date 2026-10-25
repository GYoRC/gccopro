"""Daily reminder job (gccpro.reminders) with push delivery stubbed out."""

from datetime import date

import pytest

from gccpro import push, reminders
from gccpro.db import get_db


@pytest.fixture
def sent(monkeypatch):
    """Record pushes instead of contacting push services; every push succeeds."""
    calls = []

    def fake_deliver(subscription, message):
        calls.append((subscription["endpoint"], message))
        return 201

    monkeypatch.setattr(push, "deliver", fake_deliver)
    return calls


def setup_db(app, *, subscribe=(2, 3)):
    """Tuesday trash rule, Alice (2) on week 43, Bruno (3) on week 44, subscriptions."""
    with app.app_context():
        db = get_db()
        with db:
            db.execute("INSERT INTO trash_rules (label, weekday, frequency) VALUES ('Ordures', 1, 'weekly')")
            db.execute("INSERT INTO trash_rules (label, weekday, frequency) VALUES ('Verre', 0, 'weekly')")
            db.execute("INSERT INTO bookings (week_start, resident_id) VALUES ('2026-10-19', 2)")
            db.execute("INSERT INTO bookings (week_start, resident_id) VALUES ('2026-10-26', 3)")
            # Keep the free-week part quiet unless a test wants it.
            for week in ("2026-11-02", "2026-11-09", "2026-11-16"):
                db.execute("INSERT INTO bookings (week_start, resident_id) VALUES (?, 1)", (week,))
            for rid in subscribe:
                db.execute("INSERT INTO push_subscriptions (resident_id, endpoint, p256dh, auth)"
                           " VALUES (?, ?, 'k', 'a')", (rid, f"https://push.example/{rid}"))


def test_trash_reminder_goes_to_person_on_duty(app, sent):
    setup_db(app)
    with app.app_context():
        lines = reminders.run(date(2026, 10, 26))  # Monday evening, Tuesday pickup
    assert sent == [("https://push.example/3", {
        "title": "Poubelles à sortir ce soir",
        "body": "Collecte demain, mardi 27 octobre : Ordures.",
        "url": "/",
    })]
    assert "Bruno" in lines[0]


def test_trash_reminder_goes_to_whole_apartment(app, sent):
    with app.app_context():
        db = get_db()
        with db:
            db.execute("INSERT INTO residents (id, name, email, apartment)"
                       " VALUES (4, 'Chloé', 'chloe@test.fr', ' apt 3 ')")
    setup_db(app, subscribe=(3, 4))
    with app.app_context():
        lines = reminders.run(date(2026, 10, 26))
        reminders.run(date(2026, 10, 26))  # idempotent per resident
    assert sorted(endpoint for endpoint, _ in sent) == [
        "https://push.example/3", "https://push.example/4"]
    assert len(lines) == 2


def test_fixed_date_pickup_also_notifies_admin_apartment(app, sent):
    setup_db(app, subscribe=(1, 3))
    with app.app_context():
        db = get_db()
        with db:
            db.execute("INSERT INTO trash_dates (label, date) VALUES ('Déchets verts', '2026-10-28')")
        # Tuesday evening: Wednesday has only the fixed-date pickup, owned by Bruno's week.
        reminders.run(date(2026, 10, 27))
    assert sorted(endpoint for endpoint, _ in sent) == [
        "https://push.example/1", "https://push.example/3"]
    assert all("Déchets verts" in m["body"] for _, m in sent)


def test_regular_pickup_does_not_notify_admin_apartment(app, sent):
    setup_db(app, subscribe=(1, 3))
    with app.app_context():
        reminders.run(date(2026, 10, 26))
    assert [endpoint for endpoint, _ in sent] == ["https://push.example/3"]


def test_monday_pickup_is_reminded_to_previous_weeks_resident(app, sent):
    setup_db(app)
    with app.app_context():
        reminders.run(date(2026, 10, 25))  # Sunday evening, Monday "Verre" pickup
    assert [endpoint for endpoint, _ in sent] == ["https://push.example/2"]


def test_reminder_sent_only_once(app, sent):
    setup_db(app)
    with app.app_context():
        reminders.run(date(2026, 10, 26))
        reminders.run(date(2026, 10, 26))
    assert len(sent) == 1


def test_email_fallback_without_subscription(app, sent, outbox):
    setup_db(app, subscribe=())
    with app.app_context():
        reminders.run(date(2026, 10, 26))
    assert sent == []
    assert outbox[-1]["To"] == "bruno@test.fr"
    assert "mardi 27 octobre" in outbox[-1].get_content()


def test_free_week_reminders(app, sent, outbox):
    setup_db(app)
    with app.app_context():
        db = get_db()
        with db:
            db.execute("DELETE FROM bookings WHERE week_start = '2026-11-02'")
        reminders.run(date(2026, 10, 21))  # Wednesday: no pickup tomorrow
        reminders.run(date(2026, 10, 22))
    # Pushed once to each subscribed resident, emailed once to the admin.
    assert sorted(endpoint for endpoint, _ in sent) == ["https://push.example/2", "https://push.example/3"]
    assert "du 2 au 8 novembre 2026" in sent[0][1]["body"]
    assert [m["To"] for m in outbox] == ["admin@test.fr"]


def test_dry_run_sends_nothing(app, sent, outbox):
    setup_db(app)
    with app.app_context():
        lines = reminders.run(date(2026, 10, 26), dry_run=True)
        assert get_db().execute("SELECT COUNT(*) FROM notification_log").fetchone()[0] == 0
    assert sent == [] and outbox == [] and lines[0].startswith("[dry-run]")


def test_expired_subscription_is_removed(app, monkeypatch):
    setup_db(app)
    monkeypatch.setattr(push, "deliver", lambda sub, msg: 410)
    with app.app_context():
        assert push.send_to_resident(2, "t", "b") == 0
        assert get_db().execute(
            "SELECT COUNT(*) FROM push_subscriptions WHERE resident_id = 2").fetchone()[0] == 0
