-- Initial schema. Dates are ISO 'YYYY-MM-DD' strings, timestamps ISO UTC strings.
-- STRICT tables are deliberately not used: the NAS's sqlite3 CLI (3.34) cannot read them.

CREATE TABLE residents (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    apartment   TEXT NOT NULL DEFAULT '',
    role        TEXT NOT NULL DEFAULT 'resident' CHECK (role IN ('resident', 'admin')),
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- One-time login links; only a SHA-256 hash of the token is stored.
CREATE TABLE login_tokens (
    id          INTEGER PRIMARY KEY,
    token_hash  TEXT NOT NULL UNIQUE,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL,
    used_at     TEXT
);

-- A booking is a whole week, identified by its Monday; one resident per week.
CREATE TABLE bookings (
    week_start        TEXT PRIMARY KEY,
    resident_id       INTEGER NOT NULL REFERENCES residents(id),
    assigned_by_admin INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Recurring trash pickups. weekday: 0 = Monday ... 6 = Sunday.
-- frequency uses ISO week numbers for even/odd weeks.
CREATE TABLE trash_rules (
    id         INTEGER PRIMARY KEY,
    label      TEXT NOT NULL,
    weekday    INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    frequency  TEXT NOT NULL DEFAULT 'weekly'
               CHECK (frequency IN ('weekly', 'even_weeks', 'odd_weeks'))
);

-- Exceptions to a rule on a given date: cancelled (moved_to NULL) or moved.
CREATE TABLE trash_exceptions (
    id        INTEGER PRIMARY KEY,
    rule_id   INTEGER NOT NULL REFERENCES trash_rules(id) ON DELETE CASCADE,
    date      TEXT NOT NULL,
    moved_to  TEXT,
    UNIQUE (rule_id, date)
);

CREATE TABLE push_subscriptions (
    id          INTEGER PRIMARY KEY,
    resident_id INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    endpoint    TEXT NOT NULL UNIQUE,
    p256dh      TEXT NOT NULL,
    auth        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Building information; event_date is set for dated events such as the AG.
CREATE TABLE announcements (
    id           INTEGER PRIMARY KEY,
    title        TEXT NOT NULL,
    body         TEXT NOT NULL DEFAULT '',
    event_date   TEXT,
    published_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Makes the daily reminder job idempotent: one row per notification sent.
CREATE TABLE notification_log (
    kind        TEXT NOT NULL,
    resident_id INTEGER NOT NULL,
    ref_date    TEXT NOT NULL,
    sent_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (kind, resident_id, ref_date)
);

CREATE TABLE settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
