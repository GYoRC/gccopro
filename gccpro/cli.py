"""Flask CLI commands: ``flask --app gccpro <command>``."""

import sqlite3
from datetime import date

import click
from flask import Flask, current_app
from flask.cli import with_appcontext

from . import auth, clock, phones, push, reminders
from .db import get_db


@click.command("create-admin")
@with_appcontext
@click.option("--name", required=True, help="Display name, e.g. 'Yoann G.'")
@click.option("--email", required=True)
@click.option("--apartment", default="", help="Apartment label, e.g. 'Apt 3'")
def create_admin(name: str, email: str, apartment: str) -> None:
    """Create an administrator, or promote the resident with this email."""
    db = get_db()
    with db:
        db.execute(
            "INSERT INTO residents (name, email, apartment, role) VALUES (?, ?, ?, 'admin')"
            " ON CONFLICT (email) DO UPDATE SET role = 'admin', active = 1",
            (name, email.strip(), apartment),
        )
    click.echo(f"Administrator {email} ready. Log in with this address at /connexion.")


@click.command("login-link")
@with_appcontext
@click.argument("identifier")
def login_link(identifier: str) -> None:
    """Print a one-time login link for IDENTIFIER, an email or a phone number."""
    if "@" in identifier:
        column, value = "email", identifier.strip()
    else:
        try:
            column, value = "phone", phones.normalize(identifier)
        except phones.PhoneError:
            raise click.ClickException(f"{identifier!r} is neither an email nor a phone number.")
    resident = get_db().execute(
        f"SELECT * FROM residents WHERE {column} = ? AND active = 1", (value,)
    ).fetchone()
    if resident is None:
        raise click.ClickException(f"No active resident with {column} {value}.")
    token = auth.create_login_token(resident["id"])
    base = current_app.config["BASE_URL"].rstrip("/")
    click.echo(f"{base}/connexion/{token}")
    click.echo(f"Valid {int(auth.TOKEN_LIFETIME.total_seconds() // 60)} minutes, single use.")


@click.command("gen-vapid")
@with_appcontext
def gen_vapid() -> None:
    """Print a new VAPID private key line for the config file."""
    key = push.generate_vapid_private_key()
    click.echo(f'VAPID_PRIVATE_KEY = "{key}"')
    click.echo(f"# public key (sent to browsers automatically): {push.vapid_public_key(key)}")


@click.command("send-reminders")
@with_appcontext
@click.option("--date", "on_date", default=None, help="Run as if today were YYYY-MM-DD.")
@click.option("--dry-run", is_flag=True, help="Show what would be sent, send nothing.")
def send_reminders(on_date: str | None, dry_run: bool) -> None:
    """Send trash and unbooked-week reminders (run once a day, in the evening)."""
    today = date.fromisoformat(on_date) if on_date else clock.today()
    lines = reminders.run(today, dry_run=dry_run)
    click.echo(f"{today.isoformat()}: {len(lines)} notification(s)")
    for line in lines:
        click.echo("  " + line)


@click.command("backup")
@with_appcontext
@click.argument("destination")
def backup(destination: str) -> None:
    """Write a consistent copy of the database to DESTINATION (safe while running)."""
    target = sqlite3.connect(destination)
    try:
        get_db().backup(target)
    finally:
        target.close()
    click.echo(f"Backup written to {destination}")


def init_app(app: Flask) -> None:
    """Register the commands on ``app``."""
    for command in (create_admin, login_link, gen_vapid, send_reminders, backup):
        app.cli.add_command(command)
