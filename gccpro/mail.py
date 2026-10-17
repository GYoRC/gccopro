"""Outgoing email for login links and admin alerts, using the standard library only."""

import smtplib
import ssl
from email.message import EmailMessage

import certifi
from flask import current_app


def send_mail(to: str, subject: str, body: str) -> None:
    """Send a plain-text email through the configured backend.

    Backends (``MAIL_BACKEND``): ``smtp`` sends for real, ``console`` prints the
    message (development), ``memory`` appends it to ``app.extensions["outbox"]``
    (tests).
    """
    cfg = current_app.config
    msg = EmailMessage()
    msg["From"] = cfg["MAIL_FROM"] or cfg["SMTP_USER"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    backend = cfg["MAIL_BACKEND"]
    if backend == "memory":
        current_app.extensions.setdefault("outbox", []).append(msg)
    elif backend == "console":
        print(f"--- email to {to} ---\nSubject: {subject}\n\n{body}\n--- end ---", flush=True)
    elif backend == "smtp":
        context = ssl.create_default_context(cafile=certifi.where())
        if cfg["SMTP_STARTTLS"]:
            with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=20) as smtp:
                smtp.starttls(context=context)
                smtp.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
                smtp.send_message(msg)
        else:
            with smtplib.SMTP_SSL(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=20, context=context) as smtp:
                smtp.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
                smtp.send_message(msg)
    else:
        raise ValueError(f"unknown MAIL_BACKEND {backend!r}")
