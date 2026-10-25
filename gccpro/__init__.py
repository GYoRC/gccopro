"""GCCopro: chores rota web app for a shared building.

:func:`create_app` is the application factory used by ``flask --app gccpro``,
the test-suite, and Waitress in production (``waitress-serve --call gccpro:create_app``).
"""

from flask import Flask, render_template

from . import auth, cli, config, db, frdates, phones
from .views import account, admin, calendar, info, pwa

#: Content-Security-Policy: everything from this origin only, no inline scripts.
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


def create_app(test_config: dict | None = None) -> Flask:
    """Create and configure the application.

    Args:
        test_config: Config values applied after defaults and the TOML file.
    """
    app = Flask(__name__)
    config.load(app, test_config)
    db.init_app(app)
    auth.init_app(app)
    cli.init_app(app)

    for blueprint in (calendar.bp, account.bp, info.bp, admin.bp, pwa.bp):
        app.register_blueprint(blueprint)

    # French date filters for templates.
    app.add_template_filter(frdates.date_longue)
    app.add_template_filter(frdates.date_courte)
    app.add_template_filter(frdates.semaine)
    app.add_template_filter(frdates.iso_longue)
    app.add_template_filter(phones.display, "telephone")

    @app.after_request
    def security_headers(response):
        """Add conservative security headers to every response."""
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    def error_page(error):
        """Render HTTP errors as a French page."""
        return render_template("error.html", error=error), error.code

    return app
