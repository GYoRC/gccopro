-- Residents can have an email, a phone number, or both (at least one).
-- SQLite cannot drop NOT NULL in place, so the table is rebuilt following the
-- documented procedure: foreign keys off, copy, drop, rename, check, foreign keys on.
-- Other tables keep referencing "residents" by name, so their rows stay attached.

PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE residents_new (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT UNIQUE COLLATE NOCASE,
    phone       TEXT UNIQUE,  -- E.164, e.g. +33612345678
    apartment   TEXT NOT NULL DEFAULT '',
    role        TEXT NOT NULL DEFAULT 'resident' CHECK (role IN ('resident', 'admin')),
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

INSERT INTO residents_new (id, name, email, apartment, role, active, created_at)
    SELECT id, name, NULLIF(trim(email), ''), apartment, role, active, created_at FROM residents;

DROP TABLE residents;
ALTER TABLE residents_new RENAME TO residents;

-- Login link requests made with a phone number, for an admin to answer on WhatsApp.
CREATE TABLE login_requests (
    id           INTEGER PRIMARY KEY,
    resident_id  INTEGER NOT NULL REFERENCES residents(id) ON DELETE CASCADE,
    requested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    handled_at   TEXT
);

COMMIT;
PRAGMA foreign_keys = ON;
