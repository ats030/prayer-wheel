"""Snapshot restore privacy, quota and publication tests; no live DB touched."""
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_trial import Clock, rid
from trial import TrialLedger, TrialLimit, ReceiptGone
from trial_restore import restore


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.clock = Clock(datetime(2026, 10, 11, 12, tzinfo=timezone.utc))
        self.ledger = TrialLedger(self.folder / "original.sqlite3", self.clock)
        self.target = self.folder / "restored.sqlite3"

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def snapshot(self):
        return self.ledger.backup(self.folder / "backups")

    def test_results_deleted_pending_not_restarted_and_restore_day_reserved(self):
        self.ledger.accept("one", rid(1), "new", {"query": "history"})
        self.ledger.claim()
        self.ledger.finish("one", rid(1), {"secret": "RESTORED_RESULT_MUST_NOT_SURVIVE"})
        self.ledger.accept("one", rid(2), "new", {"query": "running"})
        self.ledger.claim()
        self.ledger.accept("one", rid(3), "new", {"query": "queued"})
        source = self.snapshot()
        before = hashlib.sha256(source.read_bytes()).digest()
        summary = restore(source, self.target, clock=self.clock)
        self.assertEqual(summary["results"], 0)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(b"RESTORED_RESULT_MUST_NOT_SURVIVE", self.target.read_bytes())
        recovered = TrialLedger(self.target, self.clock)
        try:
            self.assertIsNone(recovered.claim())
            with self.assertRaises(ReceiptGone):
                recovered.get("one", rid(1))
            for number in (2, 3):
                self.assertEqual(recovered.get("one", rid(number))["state"], "failed")
                with self.assertRaises(ValueError):
                    recovered.cancel("one", rid(number))
            with self.assertRaises(TrialLimit) as caught:
                recovered.accept("one", rid(4), "new", {})
            self.assertEqual(caught.exception.reason, "trial_daily")
            replay, created = recovered.accept("one", rid(2), "new", {"query": "running"})
            self.assertEqual((created, replay["state"]), (False, "failed"))
            self.clock.advance(days=1)
            self.assertTrue(recovered.accept("one", rid(4), "new", {})[1])
        finally:
            recovered.close()
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), before)
        self.assertEqual(self.ledger.get("one", rid(2))["state"], "running")

    def test_legacy_snapshot_without_guard_and_reopen_keep_restore_block(self):
        self.ledger.accept("one", rid(1), "new", {})
        self.ledger.cancel("one", rid(1))
        source = self.snapshot()
        with sqlite3.connect(source) as db:
            db.execute("DROP TABLE restore_guard")
        restore(source, self.target, clock=self.clock)
        for _ in range(2):
            recovered = TrialLedger(self.target, self.clock)
            try:
                self.assertEqual(recovered.usage()["used"], 10)
                recovered.cancel("one", rid(1))
                with self.assertRaises(TrialLimit):
                    recovered.accept("one", rid(2), "new", {})
            finally:
                recovered.close()

    def test_rejects_expired_future_invalid_symlink_and_existing_destination(self):
        source = self.snapshot()
        for delta in (timedelta(days=8), timedelta(seconds=-1)):
            with self.assertRaises(ValueError):
                restore(source, self.target, clock=lambda: self.clock() + delta)
            self.assertFalse(self.target.exists())
        self.target.write_text("must not replace")
        with self.assertRaises(ValueError):
            restore(source, self.target, clock=self.clock)
        self.assertEqual(self.target.read_text(), "must not replace")
        self.target.unlink()
        link = self.folder / source.name
        link.symlink_to(source)
        with self.assertRaises(OSError):
            restore(link, self.target, clock=self.clock)
        invalid = self.folder / "invalid" / source.name
        invalid.parent.mkdir()
        invalid.write_bytes(b"not sqlite")
        with self.assertRaises(sqlite3.DatabaseError):
            restore(invalid, self.target, clock=self.clock)
        self.assertFalse(self.target.exists())

    def test_unexpected_schema_and_publish_race_leave_destination_untouched(self):
        source = self.snapshot()
        with sqlite3.connect(source) as db:
            db.execute("CREATE TABLE unexpected (body TEXT)")
        with self.assertRaises(ValueError):
            restore(source, self.target, clock=self.clock)
        with sqlite3.connect(source) as db:
            db.execute("DROP TABLE unexpected")
        def competing_publish(original, destination):
            Path(destination).write_text("concurrent output")
            raise FileExistsError
        with patch("trial_restore.os.link", side_effect=competing_publish):
            with self.assertRaises(FileExistsError):
                restore(source, self.target, clock=self.clock)
        self.assertEqual(self.target.read_text(), "concurrent output")
        self.assertEqual(list(self.folder.glob(".trial-restore-*")), [])

    def test_fifo_source_is_rejected_without_waiting_for_writer(self):
        source = self.folder / "trial-20261011T120000000000Z.sqlite3"
        os.mkfifo(source)
        code = ("from datetime import datetime,timezone; import sys; from trial_restore import restore; "
                "restore(sys.argv[1],sys.argv[2],clock=lambda:datetime(2026,10,11,12,tzinfo=timezone.utc))")
        completed = subprocess.run([sys.executable, "-c", code, str(source), str(self.target)],
                                   capture_output=True, timeout=2)
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
