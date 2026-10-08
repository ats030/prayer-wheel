-- Only account metadata and explicitly published shares belong on the server.
CREATE TABLE users (
    subject TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'free'
) STRICT;
CREATE TABLE shares (
    token TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    photo BLOB NOT NULL,
    photo_type TEXT NOT NULL
) STRICT;
