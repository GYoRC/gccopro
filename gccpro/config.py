"""Application configuration: built-in defaults overridden by an optional TOML file.

In production the file path is given by the ``GCCPRO_CONFIG`` environment variable
(see ``deploy/config.example.toml``); in development ``instance/config.toml`` is used
if it exists. Keys in the TOML file are the Flask config keys
themselves, written in upper case.
"""

import logging
import os
import tomllib
from datetime import timedelta
from pathlib import Path

from flask import Flask

log = logging.getLogger(__name__)

#: Secret key used when none is configured; only acceptable for local development.
DEV_SECRET_KEY = "dev-insecure-change-me"


def defaults(app: Flask) -> dict:
    """Return the default configuration values for ``app``.

    The default database lives in Flask's instance folder so that development
    runs never touch production data.
    """
    return {
        "SECRET_KEY": DEV_SECRET_KEY,
        # Name shown to residents ("GCCopro" is only the developer-facing name).
        "SITE_NAME": "Le 53 Bourrassol",
        "SITE_SHORT_NAME": "Le 53",          # header, home-screen icon label (~12 chars max)
        "SITE_TAGLINE": "rue de Bourrassol",  # second line of the header
        # Fixed list of apartments an admin can pick for a resident.
        "APARTMENTS": [f"Apt {n}" for n in range(1, 8)],
        "DATABASE": str(Path(app.instance_path) / "gccpro.db"),
        # Public base URL used to build links in emails and notifications.
        "BASE_URL": "http://127.0.0.1:5000",
        # "console" prints emails, "memory" stores them (tests), "smtp" sends them.
        "MAIL_BACKEND": "console",
        "MAIL_FROM": "",
        "SMTP_HOST": "",
        "SMTP_PORT": 465,
        "SMTP_USER": "",
        "SMTP_PASSWORD": "",
        # False: implicit TLS (port 465). True: STARTTLS (port 587).
        "SMTP_STARTTLS": False,
        # Raw P-256 private key, base64url; generate with `flask --app gccpro gen-vapid`.
        "VAPID_PRIVATE_KEY": "",
        "VAPID_SUBJECT": "mailto:admin@example.org",
        "SESSION_COOKIE_SECURE": False,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "PERMANENT_SESSION_LIFETIME": timedelta(days=180),
        # Fixed "today" (datetime.date) for tests; None means the real date in Paris.
        "TODAY": None,
    }


def load(app: Flask, overrides: dict | None = None) -> None:
    """Populate ``app.config`` from defaults, the TOML file, then ``overrides``.

    Args:
        app: The application being configured.
        overrides: Extra values applied last (used by the test-suite).
    """
    app.config.from_mapping(defaults(app))

    # Production sets GCCPRO_CONFIG; in development an optional, git-ignored
    # instance/config.toml is picked up automatically.
    path = os.environ.get("GCCPRO_CONFIG")
    if not path and overrides is None:
        local = Path(app.instance_path) / "config.toml"
        path = str(local) if local.exists() else None
    if path:
        with open(path, "rb") as fh:
            app.config.from_mapping(tomllib.load(fh))

    if overrides:
        app.config.from_mapping(overrides)

    if app.config["SECRET_KEY"] == DEV_SECRET_KEY and not (app.debug or app.testing):
        log.warning("SECRET_KEY is the development default; set it in the config file.")
