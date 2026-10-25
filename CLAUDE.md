# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language
- All code, comments, docs, commit messages and this file: English only.
- The user may chat in French or English; reply in the user's language in chat.

## What this is
Chores rota for a building in France: residents book whole weeks (Monday–Sunday, 1 or 2 consecutive, max 2 in a row) to clean common areas, take out the trash and clean the parking lot; the person on duty gets a push notification the evening before each trash pickup. Also shows building info (e.g. Assemblée Générale date). **All user-facing text is French**; code, comments and logs are English.
- "GCCopro" is the developer-facing name only. Residents see "Le 53 Bourrassol" (header "Le 53" / "rue de Bourrassol"), from the `SITE_NAME`, `SITE_SHORT_NAME` and `SITE_TAGLINE` config keys; never hard-code the name in templates, emails or notifications.

## Stack
- Python 3.12, Flask + Jinja2 server-rendered pages, Waitress, SQLite (stdlib `sqlite3`). Plain JS in `gccpro/static/` only for the service worker and push button; no Node, no build step.
- Every runtime dependency must be pure Python (see NAS constraints below). `cryptography` is dev-only, used to cross-check `gccpro/aesgcm.py`.

## Commands (PC, Git Bash, from repo root)
- Setup: `py -3.12 -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt`
- Tests: `.venv/Scripts/python -m pytest` — single test: `.venv/Scripts/python -m pytest tests/test_rules.py::test_horizon`
- Dev server: `.venv/Scripts/flask --app gccpro run --debug`, open `http://localhost:5000` (DB in `instance/`, emails printed to console, so log in by copying the link from the terminal). Optional git-ignored `instance/config.toml` is loaded automatically (holds the dev VAPID key so push works on localhost). First create an admin: `.venv/Scripts/flask --app gccpro create-admin --name X --email Y`
- Other CLI: `send-reminders [--date YYYY-MM-DD] [--dry-run]`, `login-link EMAIL` (prints a login link, no email needed), `gen-vapid`, `backup DEST`. Commands need `@with_appcontext`.
- On the NAS: `ssh nas bash gccpro/app/deploy/login-link.sh EMAIL`; set the SMTP password interactively with `ssh -t nas bash gccpro/app/deploy/set-smtp-password.sh` (never put it on a command line).
- Deploy: `bash deploy/deploy.sh` (tar over `ssh nas`, then `deploy/install.sh` on the NAS updates the venv and restarts).

## Architecture
- `gccpro/__init__.py:create_app` is the factory for CLI, tests and Waitress (`--call gccpro:create_app`). Config = defaults in `config.py`, then the TOML file named by `GCCPRO_CONFIG` (keys are Flask config keys), then test overrides.
- Business logic is pure and unit-tested: `rules.py` (booking validation, cancel deadline, who gets the trash reminder = owner of the week containing the day *before* the pickup), `trash.py` (expands weekly / even / odd ISO-week rules plus cancel/move exceptions into dates), `frdates.py` (French dates, no locale). Views only load data via `db.py` helpers and call these.
- Schema: `gccpro/schema/NNN_*.sql`, applied automatically at startup by `db.migrate` (add a new numbered file; never edit an applied one). Dates are ISO strings; one booking per week (`bookings.week_start` = Monday, primary key). Avoid `STRICT` tables: the NAS `sqlite3` CLI is 3.34.
- Auth: one-time login link (`auth.py`); GET on the link only shows a button, POST consumes it (protects against mail scanners). Residents have an email and/or a phone (E.164, `phones.py`; schema requires at least one). Email login: link emailed, valid 15 min. Phone login: a `login_requests` row + push/email alert to admins, who send a 24 h link via the admin "WhatsApp" button (wa.me link on a page, not a redirect, because of CSP `form-action`). Signed cookie session, 180 days. CSRF token required on every POST (`csrf_token` form field or `X-CSRF-Token` header). Strict CSP: no inline scripts or styles in templates.
- Push: `push.py` implements RFC 8291 encryption + VAPID with pure-Python `ecdsa` and `aesgcm.py`, because `cryptography` has no wheel for the NAS. Tests check RFC/NIST vectors; keep them passing when touching crypto.
- `reminders.run` is idempotent via `notification_log`; trash reminders fall back to email when the resident has no push subscription.
- Time: always `clock.today()` (Europe/Paris, overridable via `TODAY` config in tests), never `date.today()`.

## Production on the NAS
- Layout: `/volume1/homes/claude/gccpro/{app,venv,data}`; `data/` holds `config.toml` (secrets, chmod 600), `gccpro.db`, `backups/`, `logs/`. Deploys replace only `app/`.
- Waitress listens on `127.0.0.1:8090` behind the DSM reverse proxy (HTTPS on `le53.yoanngualtieri.xyz`, a CNAME to `nas.yoanngualtieri.xyz` whose A record is kept current by OVH DynHost). DSM Task Scheduler (as user `claude`): `deploy/start.sh` at boot and every 5 min (watchdog), `deploy/reminders.sh` daily 18:00, `deploy/backup.sh` nightly.
- Logs: `data/logs/{server,reminders,backup}.log`.

## Hosting constraints (Synology DS216j)
- NAS address: 192.168.1.49 (DSM web UI on HTTPS port 5001).
- Shell access: `ssh nas` (key-based, user `claude`, alias in `~/.ssh/config`). Never store passwords in this repo. The `claude` account has no passwordless sudo; ask the user to run root commands.
- DSM 7.1.1-42962 Update 9 (upgraded from 7.0.1 on 2026-10-17).
- Python on NAS: Python 3.12.13 from the SynoCommunity `python312` package, at `/var/packages/python312/target/bin/python3.12` (not on PATH). Target Python 3.12 for the backend.
  - Its `sqlite3` module links SQLite 3.45.2 (`RETURNING`, `STRICT` tables and JSON functions are available).
  - pip works inside a venv: `/var/packages/python312/target/bin/python3.12 -m venv <dir>`. Create venvs under the home folder or `/volume1`, never `/tmp` (mounted `noexec`).
  - Do not use or modify the system Python 3.8.12 (`/usr/bin/python3`, no pip); DSM depends on it.
- The `sqlite3` CLI (`/usr/bin/sqlite3`) is the system one, SQLite 3.34.1.
- Other DSM packages (not on the `claude` user's PATH; call by full path):
  - Git 2.33.0: `/var/packages/Git/target/bin/git` (package stopped, binary works).
  - Node.js 12.22.12: `/var/packages/Node.js_v12/target/usr/local/bin/node` (end-of-life; do not build on it).
  - `py3k` package ships an obsolete Python 3.5.1; ignore it.
- Hardware: 32-bit ARMv7 (`armv7l`; Marvell Armada 385, dual-core 1.0 GHz), ~500 MB RAM; ~300 MB available right after boot, dropping to ~170 MB with swap in use under normal load.
  - Many Python wheels and npm packages with native code have no 32-bit ARM build and will try to compile or fail. Use pure-Python / pure-JS dependencies for anything that runs on the NAS.
  - Recent Node.js releases have reduced 32-bit ARM support; do not plan on running Node on the NAS.
- Root actions (Package Center installs, services, ports) are done by the user in the DSM web UI.
  - With so little free memory, keep the backend single-process and memory-light.
- Keep dependencies minimal and lightweight; avoid heavy frameworks and native builds.

## Coding standards
- Every module, function and non-trivial block must be commented (docstrings for Python, JSDoc for JS).
- Small, reviewable changes; explain the plan before large edits.
- Write tests alongside features.

