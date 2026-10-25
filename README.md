# GCCopro

A small web app for running the chores rota of a residential building in France.

Each week, from Monday to Sunday, one resident is on duty: they clean the common areas, take out the
trash and clean the parking lot. Residents book their weeks in the app, and the person on duty
gets a phone notification the evening before each trash pickup.

The app is self-hosted on a Synology NAS and served at `https://le53.yoanngualtieri.xyz`.
The interface is entirely in French.

## Features

- **Calendar**: a month view where each row is one Monday–Sunday week, plus a list view. Residents
  book 1 or 2 weeks at a time, never more than 2 in a row, up to a configurable horizon (26 weeks by default).
- **Calendar**: year, month and list views; under them, the resident's own upcoming weeks with
  cancellation up to a deadline (7 days before the week by default).
- **Profile** (*Profil*): the resident's details, the switch for push notifications on each device,
  and logout.
- **Trash reminders**: a push notification at 18:00 the day before each pickup, sent to whoever is on
  duty that evening. It falls back to email for residents without notifications.
- **Unbooked weeks**: highlighted in the calendar. Residents are notified and the admins are emailed
  two weeks ahead (configurable).
- **Building info** (*Infos*): announcements, with the next dated event (e.g. the Assemblée
  Générale) shown first.
- **Administration**:
  - residents (add, deactivate, promote to admin, send a login link);
  - assigning or freeing any week;
  - trash pickup days (weekly, even or odd weeks) and holiday exceptions;
  - announcements;
  - settings;
  - a test notification.
- **No passwords**: residents log in with a one-time link, sent by email automatically, or, for residents who log in with their phone number, forwarded on WhatsApp by an admin in one tap. They then stay logged in for 6 months.
- **Installable**: residents can add the site to their phone's home screen. On iPhone this is
  required for notifications (iOS 16.4 or later).

## Tech overview

Python 3.12, Flask with server-rendered Jinja2 templates, SQLite and Waitress. There is no JavaScript
framework and no build step. The only scripts are a service worker and the notification button.

The NAS (DS216j) has a 32-bit ARM CPU and about 500 MB of RAM, so every runtime dependency is pure
Python. Web Push encryption is therefore implemented in-house (`gccpro/push.py`, `gccpro/aesgcm.py`)
and checked against the RFC 8291 and NIST test vectors.

- [ARCHITECTURE.md](ARCHITECTURE.md): code layout, module dependencies and request flows.
- [CLAUDE.md](CLAUDE.md): conventions and NAS constraints, in condensed form.

## Local development

Requires Python 3.12. From the repository root, in Git Bash:

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt

# Create your admin account in the local database (instance/gccpro.db)
.venv/Scripts/flask --app gccpro create-admin --name "Your Name" --email you@example.org

# Start the dev server
.venv/Scripts/flask --app gccpro run --debug
```

Open http://localhost:5000 (use `localhost`, not `127.0.0.1`) and enter your email. In development,
emails are printed in the terminal, so copy the login link from there.

To test push notifications locally, create a git-ignored `instance/config.toml` with a VAPID key.
Browsers allow push on `localhost` without HTTPS.

```toml
VAPID_PRIVATE_KEY = "..."   # output of: .venv/Scripts/flask --app gccpro gen-vapid
VAPID_SUBJECT = "mailto:you@example.org"
BASE_URL = "http://localhost:5000"
```

### Tests

```bash
.venv/Scripts/python -m pytest                                   # whole suite
.venv/Scripts/python -m pytest tests/test_rules.py::test_horizon  # a single test
```

### CLI commands

Run them as `.venv/Scripts/flask --app gccpro <command>` locally, or on the NAS through the scripts below.

| Command | Purpose |
|---------|---------|
| `create-admin --name N --email E` | Create an administrator (or promote an existing resident) |
| `login-link EMAIL` | Print a one-time login link, without sending email |
| `send-reminders [--date YYYY-MM-DD] [--dry-run]` | Run the daily reminder job (optionally as if on another day) |
| `gen-vapid` | Generate a VAPID key for push notifications |
| `backup DEST` | Write a consistent copy of the database |

## Production (Synology NAS)

### How it runs

```
Internet ─▶ Freebox (ports 80, 443) ─▶ DSM reverse proxy (HTTPS, Let's Encrypt)
         ─▶ Waitress on 127.0.0.1:8090 ─▶ SQLite
```

Everything lives under `/volume1/homes/claude/gccpro/` on the NAS:

| Folder | Contents |
|--------|----------|
| `app/` | The code, replaced on each deploy |
| `venv/` | Python 3.12 virtualenv (SynoCommunity `python312` package) |
| `data/` | `config.toml` (secrets, chmod 600), `gccpro.db`, `backups/`, `logs/`. Never touched by deploys |

### Deploying an update

```bash
.venv/Scripts/python -m pytest && bash deploy/deploy.sh
```

`deploy.sh` copies the code over `ssh nas`, then `deploy/install.sh` updates the virtualenv, restarts
the server and checks that it answers. Database migrations run automatically on startup.

### First-time setup (already done, for reference)

1. **SSH:** key-based access for user `claude`, with the alias `nas` in `~/.ssh/config`.
2. **Python:** install the **Python 3.12** package from SynoCommunity in Package Center.
3. **First deploy:** `bash deploy/deploy.sh` stops and asks for `data/config.toml`.
   - Create it from [deploy/config.example.toml](deploy/config.example.toml), generating `SECRET_KEY` and `VAPID_PRIVATE_KEY` on the NAS.
   - Then run `bash gccpro/app/deploy/install.sh` on the NAS.
4. **Admin account:** `ssh nas`, then `cd gccpro/app && ../venv/bin/flask create-admin ...`. Set
   `GCCPRO_CONFIG=../data/config.toml` first; all `deploy/*.sh` scripts set it through `env.sh`.
5. **DSM Task Scheduler** (user-defined scripts, user `claude`):

   | Trigger | Script |
   |---------|--------|
   | Boot-up, and every 5 minutes (watchdog) | `bash /volume1/homes/claude/gccpro/app/deploy/start.sh` |
   | Daily at 18:00 | `bash /volume1/homes/claude/gccpro/app/deploy/reminders.sh` |
   | Daily at 03:00 | `bash /volume1/homes/claude/gccpro/app/deploy/backup.sh` |

6. **Network:**
   - DNS (OVH): `nas` is a DynHost A record holding the Freebox's full-stack IPv4 address; `le53` is a CNAME to `nas.yoanngualtieri.xyz.`
   - Freebox: forward TCP 80 and 443 to 192.168.1.49. Never forward 5001.
   - DSM: a Let's Encrypt certificate, and a reverse proxy rule from HTTPS `le53.yoanngualtieri.xyz:443` to HTTP `localhost:8090`, with the certificate assigned to it.
7. **Backups:** include `data/backups/` in a Hyper Backup task.

### Day-to-day operations

| Task | Command (from the PC) |
|------|-----------------------|
| Give someone a login link without email | `ssh nas bash gccpro/app/deploy/login-link.sh someone@example.org` |
| Set or change the SMTP password (typed without echo) | `ssh -t nas bash gccpro/app/deploy/set-smtp-password.sh` |
| Check what tonight's reminders would send | `ssh nas 'cd gccpro/app && . deploy/env.sh && ../venv/bin/flask send-reminders --dry-run'` |
| Read the logs | `ssh nas tail -50 gccpro/data/logs/server.log` (also `reminders.log`, `backup.log`) |
| Restart the server | `ssh nas 'bash gccpro/app/deploy/stop.sh; bash gccpro/app/deploy/start.sh'` |

### Email

Login links and admin alerts are sent over SMTP, configured in `data/config.toml` (`MAIL_BACKEND`, `SMTP_*`,
`MAIL_FROM`). Any provider with SMTP works: a Gmail app password, a free.fr address, or a relay such
as Brevo for sending from the domain. While `MAIL_BACKEND = "console"`, emails are written to
`server.log` instead of being sent. Use `login-link.sh` to log people in meanwhile.

Never put the SMTP password on a command line or in the repository. Use `set-smtp-password.sh`.

## Security notes

- Secrets (`SECRET_KEY`, SMTP password, VAPID key) exist only in `data/config.toml` on the NAS.
- Login links are single use, valid 15 minutes, and stored only as hashes.
- Login-link requests are rate-limited, and the login form gives the same answer for known and
  unknown addresses.
- Every form is CSRF-protected. Pages send a strict Content-Security-Policy, and the session cookie is
  `Secure`, `HttpOnly` and `SameSite=Lax`.
- Only ports 80 and 443 are exposed. The app itself listens on localhost only.
