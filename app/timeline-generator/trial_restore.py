"""Offline, non-overwriting restoration of trusted trial snapshots; never an HTTP API."""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import stat
import tempfile

from trial import BACKUP_DAYS, BACKUP_NAME, JST, stamp, utcnow

MAX_BACKUP_BYTES = 64 * 1024 * 1024
COLUMNS = {
    "receipts": {"owner", "receipt_id", "fingerprint", "operation", "target", "payload", "day", "state", "seq",
                 "accepted_at", "updated_at", "first_started_at", "refunded"},
    "results": {"owner", "receipt_id", "body", "completed_at", "expires_at", "received_at"},
    "restore_guard": {"day"},
}


def validate(db):
    if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
        raise ValueError("Invalid trial snapshot")
    tables = set()
    for kind, name, sql in db.execute("SELECT type,name,sql FROM sqlite_master"):
        if kind == "table" and name in COLUMNS and "VIRTUAL" not in (sql or "").upper():
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({name})")}
            if columns != COLUMNS[name]:
                raise ValueError("Invalid trial snapshot schema")
            tables.add(name)
        elif kind == "index" and (name in {"receipt_day", "receipt_queue"} or name.startswith("sqlite_autoindex_")):
            continue
        else:
            raise ValueError("Unexpected trial snapshot schema")
    if not {"receipts", "results"}.issubset(tables):
        raise ValueError("Not a trial snapshot")


def restore(source, destination, *, clock=utcnow):
    source, destination = Path(source), Path(destination)
    moment = clock()
    match = BACKUP_NAME.fullmatch(source.name)
    if not match:
        raise ValueError("A dated trial snapshot is required")
    try:
        saved = datetime.strptime(match[1], "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValueError("Invalid snapshot date") from None
    if not timedelta(0) <= moment - saved <= timedelta(days=BACKUP_DAYS):
        raise ValueError("Snapshot must be within its seven-day retention")
    if os.path.lexists(destination) or os.path.lexists(str(destination) + ".lock"):
        raise ValueError("Restore destination must be new")
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    temporary = None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BACKUP_BYTES:
            raise ValueError("Invalid snapshot size or file type")
        # The operator selects a closed, trusted snapshot. immutable prevents WAL
        # sidecars/locking/writes; NOFOLLOW above pins the selected regular file.
        with closing(sqlite3.connect(f"file:/proc/self/fd/{descriptor}?mode=ro&immutable=1", uri=True)) as source_db:
            validate(source_db)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            handle, temporary = tempfile.mkstemp(prefix=".trial-restore-", dir=destination.parent)
            os.close(handle)
            with closing(sqlite3.connect(temporary)) as copy:
                source_db.backup(copy)
                copy.execute("PRAGMA secure_delete=ON")
                copy.execute("DELETE FROM results")
                copy.execute("UPDATE receipts SET state='failed', updated_at=? WHERE state IN ('queued','running')", (stamp(moment),))
                copy.execute("CREATE TABLE IF NOT EXISTS restore_guard (day TEXT PRIMARY KEY)")
                copy.execute("DELETE FROM restore_guard")
                copy.execute("INSERT INTO restore_guard VALUES (?)", (moment.astimezone(JST).date().isoformat(),))
                copy.commit()
                # Do not retain removed results in free pages of the published DB.
                copy.execute("VACUUM")
                count = copy.execute("SELECT count(*) FROM receipts").fetchone()[0]
        with open(temporary, "rb") as output:
            os.fsync(output.fileno())
        # Atomic publication without replacing a destination created concurrently.
        os.link(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return {"receipts": count, "results": 0, "blocked_day": moment.astimezone(JST).date().isoformat()}
    finally:
        os.close(descriptor)
        if temporary is not None:
            for suffix in ("", "-journal", "-wal", "-shm"):
                Path(temporary + suffix).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Restore a trusted trial snapshot to a NEW database; results are discarded.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    try:
        restore(args.source, args.destination)
    except (OSError, ValueError, sqlite3.Error):
        raise SystemExit("Trial restore refused; verify snapshot and new destination") from None
    print("Trial ledger restored without results. New trial requests resume after JST midnight.")


if __name__ == "__main__":
    main()
