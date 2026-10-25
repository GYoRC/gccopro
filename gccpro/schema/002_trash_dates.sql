-- One-off pickups on fixed dates with no recurrence (e.g. green waste, a few
-- times a year). They are "special": the apartment of the admins is notified too.
CREATE TABLE trash_dates (
    id     INTEGER PRIMARY KEY,
    label  TEXT NOT NULL,
    date   TEXT NOT NULL,
    UNIQUE (label, date)
);
