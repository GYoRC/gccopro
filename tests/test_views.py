"""End-to-end page behaviour through the Flask test client."""

import re
from datetime import timedelta

from conftest import TODAY, csrf, login
from gccpro import auth
from gccpro.db import get_db

NEXT_MONDAY = "2026-10-26"


def book(client, week: str, count: int = 1):
    """Submit the booking form."""
    return client.post("/reserver", data={"week_start": week, "count": count,
                                          "csrf_token": csrf(client)}, follow_redirects=True)


def test_pages_require_login(client):
    for url in ("/", "/profil", "/infos", "/admin"):
        response = client.get(url)
        assert response.status_code == 302 and "/connexion" in response.headers["Location"]


def test_login_flow_and_single_use_link(client, outbox):
    token = csrf(client)
    client.post("/connexion", data={"identifiant": "ALICE@test.fr", "csrf_token": token})
    assert len(outbox) == 1 and outbox[0]["To"] == "alice@test.fr"
    link = re.search(r"https://copro\.test(/connexion/\S+)", outbox[0].get_content()).group(1)

    # GET only shows a confirmation button (link scanners must not log in).
    assert "Se connecter" in client.get(link).get_data(as_text=True)
    client.post(link, data={"csrf_token": csrf(client)})
    assert "Calendrier d’entretien" in client.get("/").get_data(as_text=True)

    # Reusing the link fails.
    other = client.application.test_client()
    response = other.post(link, data={"csrf_token": csrf(other)}, follow_redirects=True)
    assert "plus valable" in response.get_data(as_text=True)


def test_unknown_email_gets_same_answer_and_no_mail(client, outbox):
    response = client.post("/connexion", data={"identifiant": "x@nowhere.fr", "csrf_token": csrf(client)})
    assert "Vérifiez votre messagerie" in response.get_data(as_text=True)
    assert outbox == []


def test_expired_link(app, client):
    with app.app_context():
        token = auth.create_login_token(2)
        db = get_db()
        with db:
            db.execute("UPDATE login_tokens SET expires_at = '2000-01-01T00:00:00Z'")
    response = client.post(f"/connexion/{token}", data={"csrf_token": csrf(client)},
                           follow_redirects=True)
    assert "plus valable" in response.get_data(as_text=True)


def test_csrf_required(client, outbox):
    login(client, outbox, "alice@test.fr")
    response = client.post("/reserver", data={"week_start": NEXT_MONDAY, "count": 1})
    assert response.status_code == 400


def test_booking_and_consecutive_limit(client, outbox):
    login(client, outbox, "alice@test.fr")
    page = book(client, NEXT_MONDAY, 2).get_data(as_text=True)
    assert "réservées. Merci" in page
    page = book(client, "2026-11-09").get_data(as_text=True)
    assert "consécutives" in page
    page = client.get("/").get_data(as_text=True)
    assert "Mes prochaines semaines" in page and "du 26 octobre au 1er novembre 2026" in page and "du 2 au 8 novembre 2026" in page


def test_cannot_book_someone_elses_week(client, app, outbox):
    with app.app_context():
        db = get_db()
        with db:
            db.execute("INSERT INTO bookings (week_start, resident_id) VALUES (?, 3)", (NEXT_MONDAY,))
    login(client, outbox, "alice@test.fr")
    assert "déjà réservée" in book(client, NEXT_MONDAY).get_data(as_text=True)
    assert "Bruno" in client.get("/").get_data(as_text=True)


def test_cancel_rules(client, app, outbox):
    login(client, outbox, "alice@test.fr")
    book(client, NEXT_MONDAY)          # 5 days away: past the 7-day deadline
    book(client, "2026-11-16")         # far enough to cancel
    page = client.post("/annuler", data={"week_start": NEXT_MONDAY, "csrf_token": csrf(client)},
                       follow_redirects=True).get_data(as_text=True)
    assert "trop tard" in page
    page = client.post("/annuler", data={"week_start": "2026-11-16", "csrf_token": csrf(client)},
                       follow_redirects=True).get_data(as_text=True)
    assert "annulée" in page


def test_resident_cannot_cancel_others_or_open_admin(client, app, outbox):
    with app.app_context():
        db = get_db()
        with db:
            db.execute("INSERT INTO bookings (week_start, resident_id) VALUES ('2026-11-16', 3)")
    login(client, outbox, "alice@test.fr")
    response = client.post("/annuler", data={"week_start": "2026-11-16", "csrf_token": csrf(client)})
    assert response.status_code == 403
    assert client.get("/admin").status_code == 403


def test_admin_assigns_and_manages(client, app, outbox):
    login(client, outbox, "admin@test.fr")
    token = csrf(client)
    assert client.get("/admin").status_code == 200
    client.post("/admin/semaines/attribuer", data={"week_start": NEXT_MONDAY, "resident_id": 3,
                                                  "csrf_token": token})
    client.post("/admin/poubelles/ajouter", data={"label": "Ordures ménagères", "weekday": 1,
                                                 "frequency": "weekly", "csrf_token": token})
    client.post("/admin/annonces/ajouter", data={"title": "Assemblée Générale", "body": "Salle commune, 19 h",
                                                "event_date": "2026-11-20", "csrf_token": token})
    page = client.get("/").get_data(as_text=True)
    assert "Bruno" in page and "Ordures ménagères" in page
    page = client.get("/infos").get_data(as_text=True)
    assert "Prochain rendez-vous" in page and "vendredi 20 novembre 2026" in page


def test_admin_adds_resident_and_sends_link(client, outbox):
    login(client, outbox, "admin@test.fr")
    client.post("/admin/residents/ajouter", data={"name": "Chloé", "email": "chloe@test.fr",
                                                 "apartment": "Apt 4", "send_link": "1",
                                                 "csrf_token": csrf(client)})
    assert outbox[-1]["To"] == "chloe@test.fr"


def test_apartment_must_come_from_fixed_list(client, app, outbox):
    login(client, outbox, "admin@test.fr")
    client.post("/admin/residents/ajouter", data={"name": "Dan", "email": "dan@test.fr",
                                                 "apartment": "Apt 99", "csrf_token": csrf(client)})
    client.post("/admin/residents/2/logement", data={"apartment": "Apt 7", "csrf_token": csrf(client)})
    client.post("/admin/residents/3/logement", data={"apartment": "Villa", "csrf_token": csrf(client)})
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT 1 FROM residents WHERE email = 'dan@test.fr'").fetchone() is None
        assert db.execute("SELECT apartment FROM residents WHERE id = 2").fetchone()[0] == "Apt 7"
        assert db.execute("SELECT apartment FROM residents WHERE id = 3").fetchone()[0] == "Apt 3"


def test_deactivated_resident_is_logged_out(client, app, outbox):
    login(client, outbox, "alice@test.fr")
    with app.app_context():
        db = get_db()
        with db:
            db.execute("UPDATE residents SET active = 0 WHERE id = 2")
    assert client.get("/").status_code == 302


def test_push_subscription_roundtrip(client, app, outbox):
    login(client, outbox, "alice@test.fr")
    sub = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "x", "auth": "y"}}
    response = client.post("/push/abonnement", json=sub, headers={"X-CSRF-Token": csrf(client)})
    assert response.status_code == 200
    with app.app_context():
        assert get_db().execute("SELECT resident_id FROM push_subscriptions").fetchone()[0] == 2
    client.post("/push/desabonnement", json={"endpoint": sub["endpoint"]},
                headers={"X-CSRF-Token": csrf(client)})
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0] == 0


def test_month_mondays():
    from gccpro.views.calendar import month_mondays
    # October 2026 runs Thursday 1 to Saturday 31: weeks of 28 Sep ... 26 Oct.
    weeks = month_mondays(2026, 10)
    assert weeks[0].isoformat() == "2026-09-28" and weeks[-1].isoformat() == "2026-10-26"
    assert len(weeks) == 5
    # Month starting on a Monday (June 2026) does not include the previous week.
    assert month_mondays(2026, 6)[0].isoformat() == "2026-06-01"
    assert month_mondays(2026, 12)[-1].isoformat() == "2026-12-28"


def test_month_view_select_and_book(client, outbox):
    login(client, outbox, "alice@test.fr")
    page = client.get("/").get_data(as_text=True)
    assert "Octobre 2026" in page and "?mois=2026-11" in page
    assert 'id="semaine-choisie"' not in page

    url = "/?mois=2026-11&semaine=2026-11-02"
    page = client.get(url).get_data(as_text=True)
    assert "Semaine du 2 au 8 novembre 2026" in page and "Réserver cette semaine" in page

    # Booking from the panel returns to the same month view, now showing "Vous".
    response = client.post("/reserver", data={"week_start": "2026-11-02", "count": 1,
                                              "csrf_token": csrf(client)},
                           headers={"Referer": "http://localhost" + url})
    assert response.headers["Location"] == url
    page = client.get(url).get_data(as_text=True)
    assert "Vous êtes inscrit(e)" in page and "Annuler ma semaine" in page


def test_month_view_tolerates_bad_parameters(client, outbox):
    login(client, outbox, "alice@test.fr")
    assert client.get("/?mois=2026-13&semaine=nope").status_code == 200
    assert client.get("/?vue=liste").status_code == 200


def test_year_view(client, outbox):
    login(client, outbox, "alice@test.fr")
    book(client, NEXT_MONDAY)
    page = client.get("/?vue=annee").get_data(as_text=True)
    assert "Novembre" in page and "mini-week mine" in page and "Mes prochaines semaines" in page
    assert client.get("/?vue=annee&annee=nope").status_code == 200
    assert "2027" in client.get("/?vue=annee&annee=2027").get_data(as_text=True)


def test_profile_page_and_legacy_url(client, outbox):
    login(client, outbox, "alice@test.fr")
    page = client.get("/profil").get_data(as_text=True)
    assert "alice@test.fr" in page and 'id="push-panel"' in page and "Se déconnecter" in page
    assert client.get("/mes-semaines").headers["Location"] == "/"


def test_back_redirect_ignores_other_sites(client, outbox):
    login(client, outbox, "alice@test.fr")
    response = client.post("/reserver", data={"week_start": NEXT_MONDAY, "count": 1,
                                              "csrf_token": csrf(client)},
                           headers={"Referer": "https://evil.example/phish"})
    assert response.headers["Location"] == "/"


def test_login_link_command(app, client):
    result = app.test_cli_runner().invoke(args=["login-link", "alice@test.fr"])
    assert result.exit_code == 0
    link = re.search(r"https://copro\.test(/connexion/\S+)", result.output).group(1)
    client.post(link, data={"csrf_token": csrf(client)})
    assert client.get("/").status_code == 200
    result = app.test_cli_runner().invoke(args=["login-link", "nobody@test.fr"])
    assert result.exit_code != 0


def test_site_name_shown_to_residents(client, outbox):
    page = client.get("/connexion").get_data(as_text=True)
    assert "<title>Connexion – Le 53 Bourrassol</title>" in page
    assert "Le 53" in page and "rue de Bourrassol" in page and "GCCopro" not in page
    client.post("/connexion", data={"identifiant": "alice@test.fr", "csrf_token": csrf(client)})
    assert outbox[-1]["Subject"] == "Votre lien de connexion – Le 53 Bourrassol"


def test_emails_have_date_and_message_id(app, outbox):
    from gccpro import mail
    with app.app_context():
        app.config["MAIL_FROM"] = "Le 53 Bourrassol <le53@example.org>"
        mail.send_mail("alice@test.fr", "Sujet", "Corps")
    msg = outbox[-1]
    assert msg["Date"] and msg["Message-ID"].endswith("@example.org>")
    assert msg["Reply-To"] == "le53@example.org"


def test_manifest_and_service_worker(client):
    manifest = client.get("/manifest.webmanifest").json
    assert manifest["lang"] == "fr" and manifest["short_name"] == "Le 53"
    assert "showNotification" in client.get("/sw.js").get_data(as_text=True)
