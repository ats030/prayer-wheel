"""Public trial ledger: per-owner receipts, the shared daily quota and temporary result storage.

Separate from the private JobStore database, which this module never opens. `owner` must come from a verified
server-side identity; the HTTP wiring and public authentication are not part of this module.
"""
from contextlib import contextmanager
from datetime import datetime, time as clock_time, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

JST = timezone(timedelta(hours=9))
DAILY_LIMIT = 10
PENDING_LIMIT = 3
PENDING_RETRY_AFTER = 60
LEDGER_DAYS = 90
# Temporary storage contract (PUBLIC_GENERATION_DESIGN.md): unreceived results expire 72 h after completion; a
# receipt confirmation shortens that to a 10 minute re-fetch grace; backups of this database are kept 7 days.
RESULT_HOURS = 72
RECEIVED_GRACE_MINUTES = 10
BACKUP_DAYS = 7
OPERATIONS = {"new", "regenerate", "retry"}
RECEIPT_ID = re.compile(r"[A-Za-z0-9_-]{16,64}")
BACKUP_NAME = re.compile(r"trial-(\d{8}T\d{6}\d{6}Z)\.sqlite3")
RUNNING_LIMIT = 1
MAX_RECEIPTS = 10000


class TrialLimit(Exception):
    def __init__(self, reason, retry_after):
        super().__init__(reason)
        self.reason, self.retry_after = reason, retry_after


class ReceiptConflict(ValueError):
    """The receipt ID was already used for another operation, target or input (409)."""


class ReceiptGone(Exception):
    """The receipt or its temporary result was deleted or expired (410)."""


def utcnow():
    return datetime.now(timezone.utc)


def stamp(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def private_file(path):
    """Create the file owner-only before SQLite or flock touches it; SQLite journals copy its mode."""
    os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
    os.chmod(path, 0o600)


def fingerprint(operation, target, payload):
    text = json.dumps([operation, target, payload], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


class TrialLedger:
    def __init__(self, path, clock=utcnow):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        private_file(self.path)
        private_file(str(self.path) + ".lock")
        self.lock = open(str(self.path) + ".lock", "a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.transaction() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS receipts (
                    owner TEXT NOT NULL, receipt_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    operation TEXT NOT NULL, target TEXT, payload TEXT, day TEXT NOT NULL, state TEXT NOT NULL,
                    seq INTEGER NOT NULL, accepted_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    first_started_at TEXT, refunded INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (owner, receipt_id))""")
                db.execute("""CREATE TABLE IF NOT EXISTS results (
                    owner TEXT NOT NULL, receipt_id TEXT NOT NULL, body TEXT NOT NULL,
                    completed_at TEXT NOT NULL, expires_at TEXT NOT NULL, received_at TEXT,
                    PRIMARY KEY (owner, receipt_id))""")
                db.execute("CREATE INDEX IF NOT EXISTS receipt_day ON receipts(day, refunded)")
                db.execute("CREATE INDEX IF NOT EXISTS receipt_queue ON receipts(state, seq)")
                # The first start stays recorded, so a restarted item is never refunded on a later cancel.
                db.execute("UPDATE receipts SET state='queued', updated_at=? WHERE state='running'", (stamp(self.clock()),))
        except BaseException:
            self.lock.close()
            raise

    def close(self):
        self.lock.close()

    @contextmanager
    def transaction(self, write=True):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            # Deleted inputs and results must not survive in free pages or the backups copied from them.
            db.execute("PRAGMA secure_delete=ON")
            # Acceptance, start and cancel serialize on the same write lock; reads do not take it.
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")
        finally:
            db.close()

    @staticmethod
    def decode(row):
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item["payload"]) if item["payload"] is not None else None
        item["refunded"] = bool(item["refunded"])
        return item

    @staticmethod
    def fetch_row(db, owner, receipt_id):
        return db.execute("SELECT * FROM receipts WHERE owner=? AND receipt_id=?", (owner, receipt_id)).fetchone()

    @staticmethod
    def counts(db, day):
        used = db.execute("SELECT count(*) FROM receipts WHERE day=? AND refunded=0", (day,)).fetchone()[0]
        pending = db.execute("SELECT count(*) FROM receipts WHERE state IN ('queued','running')").fetchone()[0]
        return used, pending

    @staticmethod
    def check_ids(owner, receipt_id):
        if not isinstance(owner, str) or not 1 <= len(owner) <= 128:
            raise ValueError("本人を確認できません。")
        if not isinstance(receipt_id, str) or not RECEIPT_ID.fullmatch(receipt_id):
            raise ValueError("受付IDが不正です。")

    def accept(self, owner, receipt_id, operation, payload, target=None):
        """Return (receipt, created). Replays are answered before any limit is checked."""
        self.check_ids(owner, receipt_id)
        if operation not in OPERATIONS:
            raise ValueError("操作が不正です。")
        moment = self.clock()
        digest = fingerprint(operation, target, payload)
        with self.transaction() as db:
            row = self.fetch_row(db, owner, receipt_id)
            if row is not None:
                if row["state"] == "deleted":
                    raise ReceiptGone("この受付は削除済みです。")
                if row["fingerprint"] != digest:
                    raise ReceiptConflict("この受付IDは別の条件で使われています。新しい受付IDで登録してください。")
                return self.decode(row), False
            day = moment.astimezone(JST).date().isoformat()
            used, pending = self.counts(db, day)
            if used >= DAILY_LIMIT:
                midnight = datetime.combine(moment.astimezone(JST).date() + timedelta(days=1), clock_time(), JST)
                raise TrialLimit("trial_daily", max(1, int((midnight - moment).total_seconds())))
            if pending >= PENDING_LIMIT:
                raise TrialLimit("trial_pending", PENDING_RETRY_AFTER)
            # Cancellation refunds AI quota, not unbounded disk capacity.
            if db.execute("SELECT count(*) FROM receipts").fetchone()[0] >= MAX_RECEIPTS:
                raise TrialLimit("trial_storage", 3600)
            seq = db.execute("SELECT coalesce(max(seq), 0) + 1 FROM receipts").fetchone()[0]
            db.execute("""INSERT INTO receipts (owner, receipt_id, fingerprint, operation, target, payload, day, state,
                seq, accepted_at, updated_at) VALUES (?,?,?,?,?,?,?, 'queued', ?,?,?)""",
                       (owner, receipt_id, digest, operation, target, json.dumps(payload, ensure_ascii=False), day,
                        seq, stamp(moment), stamp(moment)))
            return self.decode(self.fetch_row(db, owner, receipt_id)), True

    def claim(self):
        """Start the oldest queued receipt (worker side, any owner); None while the one generation slot is busy."""
        moment = stamp(self.clock())
        with self.transaction() as db:
            if db.execute("SELECT count(*) FROM receipts WHERE state='running'").fetchone()[0] >= RUNNING_LIMIT:
                return None
            row = db.execute("SELECT * FROM receipts WHERE state='queued' ORDER BY seq LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("""UPDATE receipts SET state='running', updated_at=?, first_started_at=coalesce(first_started_at, ?)
                WHERE owner=? AND receipt_id=?""", (moment, moment, row["owner"], row["receipt_id"]))
            return self.decode(self.fetch_row(db, row["owner"], row["receipt_id"]))

    def cancel(self, owner, receipt_id):
        """None for an unknown receipt or another owner's receipt; only an unstarted cancel refunds its day."""
        self.check_ids(owner, receipt_id)
        with self.transaction() as db:
            row = self.fetch_row(db, owner, receipt_id)
            if row is None:
                return None
            if row["state"] == "deleted":
                raise ReceiptGone("この受付は削除済みです。")
            if row["state"] == "cancelled":
                return self.decode(row)
            if row["state"] not in {"queued", "running"}:
                raise ValueError("待機中・生成中の処理だけ中止できます。")
            refund = row["first_started_at"] is None and not row["refunded"]
            db.execute("UPDATE receipts SET state='cancelled', updated_at=?, refunded=refunded OR ? WHERE owner=? AND receipt_id=?",
                       (stamp(self.clock()), refund, owner, receipt_id))
            return self.decode(self.fetch_row(db, owner, receipt_id))

    def finish(self, owner, receipt_id, result=None):
        """Record a running receipt's outcome; a result goes to temporary storage until the owner receives it."""
        moment = self.clock()
        with self.transaction() as db:
            row = self.fetch_row(db, owner, receipt_id)
            if row is None or row["state"] != "running":
                return False
            db.execute("UPDATE receipts SET state=?, updated_at=? WHERE owner=? AND receipt_id=?",
                       ("complete" if result is not None else "failed", stamp(moment), owner, receipt_id))
            if result is not None:
                db.execute("INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,NULL)",
                           (owner, receipt_id, json.dumps(result, ensure_ascii=False), stamp(moment),
                            stamp(moment + timedelta(hours=RESULT_HOURS))))
            return True

    def get(self, owner, receipt_id):
        """The owner's receipt and, while it is kept, its result."""
        self.check_ids(owner, receipt_id)
        moment = stamp(self.clock())
        with self.transaction(write=False) as db:
            row = self.fetch_row(db, owner, receipt_id)
            if row is None:
                return None
            if row["state"] == "deleted":
                raise ReceiptGone("この受付は削除済みです。")
            item = self.decode(row)
            if row["state"] == "complete":
                result = db.execute("SELECT * FROM results WHERE owner=? AND receipt_id=? AND expires_at>?",
                                    (owner, receipt_id, moment)).fetchone()
                if result is None:
                    raise ReceiptGone("一時保存の期限が過ぎました。端末に保存した年表を確認してください。")
                item.update(result=json.loads(result["body"]), expires_at=result["expires_at"], received_at=result["received_at"])
            return item

    def receive(self, owner, receipt_id):
        """The device saved the result: keep it only for the short re-fetch grace."""
        self.check_ids(owner, receipt_id)
        moment = self.clock()
        with self.transaction() as db:
            row = self.fetch_row(db, owner, receipt_id)
            if row is None:
                return None
            if row["state"] != "complete":
                raise ReceiptGone("受け取れる結果がありません。") if row["state"] == "deleted" else ValueError("結果がまだありません。")
            result = db.execute("SELECT * FROM results WHERE owner=? AND receipt_id=? AND expires_at>?",
                                (owner, receipt_id, stamp(moment))).fetchone()
            if result is None:
                raise ReceiptGone("一時保存の期限が過ぎました。端末に保存した年表を確認してください。")
            if result["received_at"] is None:
                expires = min(result["expires_at"], stamp(moment + timedelta(minutes=RECEIVED_GRACE_MINUTES)))
                db.execute("UPDATE results SET received_at=?, expires_at=? WHERE owner=? AND receipt_id=?",
                           (stamp(moment), expires, owner, receipt_id))
            return dict(db.execute("SELECT owner, receipt_id, expires_at, received_at FROM results WHERE owner=? AND receipt_id=?",
                                   (owner, receipt_id)).fetchone())

    def delete(self, owner, receipt_id):
        """Remove the input and result; the ledger row stays so the day's quota is unchanged."""
        self.check_ids(owner, receipt_id)
        with self.transaction() as db:
            row = self.fetch_row(db, owner, receipt_id)
            if row is None:
                return None
            if row["state"] in {"queued", "running"}:
                raise ValueError("待機中・生成中の処理は中止してから削除してください。")
            db.execute("DELETE FROM results WHERE owner=? AND receipt_id=?", (owner, receipt_id))
            db.execute("UPDATE receipts SET state='deleted', payload=NULL, target=NULL, fingerprint='', updated_at=? WHERE owner=? AND receipt_id=?",
                       (stamp(self.clock()), owner, receipt_id))
            return {"receipt_id": receipt_id, "deleted": True}

    def listing(self, owner):
        with self.transaction(write=False) as db:
            rows = db.execute("SELECT * FROM receipts WHERE owner=? AND state!='deleted' ORDER BY seq DESC", (owner,)).fetchall()
            return [self.decode(row) for row in rows]

    def usage(self):
        day = self.clock().astimezone(JST).date().isoformat()
        with self.transaction(write=False) as db:
            used, pending = self.counts(db, day)
        return {"day": day, "used": used, "daily_limit": DAILY_LIMIT, "pending": pending, "pending_limit": PENDING_LIMIT}

    def purge(self):
        """Drop expired results and ledger rows past retention; an expired result never restores quota."""
        moment = self.clock()
        oldest = (moment.astimezone(JST).date() - timedelta(days=LEDGER_DAYS)).isoformat()
        with self.transaction() as db:
            results = db.execute("DELETE FROM results WHERE expires_at<=?", (stamp(moment),)).rowcount
            receipts = db.execute("DELETE FROM receipts WHERE day<? AND state NOT IN ('queued','running')", (oldest,)).rowcount
            db.execute("DELETE FROM results WHERE NOT EXISTS (SELECT 1 FROM receipts r WHERE r.owner=results.owner AND r.receipt_id=results.receipt_id)")
        return {"results": results, "receipts": receipts}

    def backup(self, directory):
        """Write a dated snapshot and remove snapshots older than BACKUP_DAYS."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        moment = self.clock()
        target = directory / f"trial-{moment.astimezone(timezone.utc):%Y%m%dT%H%M%S%fZ}.sqlite3"
        # Never overwrite an earlier snapshot; the empty owner-only file becomes the copy.
        os.close(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        source, copy = sqlite3.connect(self.path), sqlite3.connect(target)
        try:
            source.backup(copy)
        finally:
            copy.close()
            source.close()
        limit = moment - timedelta(days=BACKUP_DAYS)
        for old in directory.iterdir():
            match = BACKUP_NAME.fullmatch(old.name)
            if match and datetime.strptime(match[1], "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc) < limit:
                old.unlink()
        return target
