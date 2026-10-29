"""Run slow work (SMTP, push) after the HTTP response is decided.

The public login form must answer in the same time and with the same page whether or
not the address or number is known; otherwise response time reveals who lives in the
building. Sending mail takes seconds, so it moves to a daemon thread.
"""

import logging
import threading
from typing import Callable

from flask import current_app

log = logging.getLogger(__name__)

#: Name given to the worker threads (tests wait for them).
THREAD_NAME = "gccpro-background"


def run(job: Callable[[], None]) -> None:
    """Run ``job`` inside an application context, never raising into the caller.

    Errors are logged. In production the job runs in a daemon thread, so the
    request returns immediately; when ``TESTING`` is set it runs inline, which
    keeps tests deterministic.

    The job must not touch request objects or database rows fetched by the
    request (SQLite connections are per context): pass plain strings and numbers.
    """
    app = current_app._get_current_object()

    def wrapper() -> None:
        with app.app_context():
            try:
                job()
            except Exception:
                log.exception("background job failed")

    if app.testing:
        wrapper()
    else:
        threading.Thread(target=wrapper, name=THREAD_NAME, daemon=True).start()
