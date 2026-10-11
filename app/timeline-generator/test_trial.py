"""Public trial ledger: quota, ownership, start/cancel races and temporary storage (no model calls)."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import tempfile
import threading
import unittest
from unittest.mock import patch

import trial
from trial import JST, ReceiptConflict, ReceiptGone, TrialLedger, TrialLimit


class Clock:
    def __init__(self, moment):
        self.moment, self.lock = moment, threading.Lock()

    def __call__(self):
        with self.lock:
            return self.moment

    def advance(self, **delta):
        with self.lock:
            self.moment += timedelta(**delta)


def rid(n):
    return f"receipt-{n:08d}-abcdef"


class TrialLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = self.temp.name + "/trial.sqlite3"
        self.clock = Clock(datetime(2026, 10, 11, 12, 0, tzinfo=JST))
        self.ledger = TrialLedger(self.path, self.clock)

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def accept(self, n, owner="alice", operation="new", payload=None):
        return self.ledger.accept(owner, rid(n), operation, payload or {"query": f"テーマ{n}"})

    def run_to_completion(self, n, owner="alice", result=None):
        self.accept(n, owner)
        started = self.ledger.claim()
        self.assertEqual(started["receipt_id"], rid(n))
        self.ledger.finish(owner, rid(n), result)

    def test_twenty_concurrent_accepts_never_exceed_daily_limit(self):
        with patch.object(trial, "PENDING_LIMIT", 100):
            with ThreadPoolExecutor(20) as pool:
                outcomes = list(pool.map(self.try_accept, range(20)))
        self.assertEqual(outcomes.count("created"), trial.DAILY_LIMIT)
        self.assertEqual(outcomes.count("trial_daily"), 20 - trial.DAILY_LIMIT)
        self.assertEqual(self.ledger.usage()["used"], trial.DAILY_LIMIT)

    def test_twenty_concurrent_accepts_respect_pending_limit(self):
        with ThreadPoolExecutor(20) as pool:
            outcomes = list(pool.map(self.try_accept, range(20)))
        self.assertEqual(outcomes.count("created"), trial.PENDING_LIMIT)
        self.assertEqual(outcomes.count("trial_pending"), 20 - trial.PENDING_LIMIT)

    def try_accept(self, n):
        try:
            self.accept(n, owner=f"user{n}")
            return "created"
        except TrialLimit as exc:
            return exc.reason

    def test_daily_limit_resets_at_jst_midnight_and_counts_all_operations(self):
        self.clock.moment = datetime(2026, 10, 11, 23, 59, 30, tzinfo=JST)
        for n in range(trial.DAILY_LIMIT):
            self.ledger.accept("alice", rid(n), ["new", "regenerate", "retry"][n % 3], {"q": n})
            self.ledger.claim()
            self.ledger.finish("alice", rid(n), None)
        with self.assertRaises(TrialLimit) as caught:
            self.accept(99)
        self.assertEqual((caught.exception.reason, caught.exception.retry_after), ("trial_daily", 30))
        self.clock.advance(seconds=30)
        receipt, created = self.accept(99)
        self.assertTrue(created)
        self.assertEqual(receipt["day"], "2026-10-12")

    def test_unstarted_cancel_refunds_once_and_started_cancel_does_not(self):
        self.accept(1)
        self.accept(2)
        first = self.ledger.cancel("alice", rid(1))
        self.assertEqual((first["state"], first["refunded"]), ("cancelled", True))
        again = self.ledger.cancel("alice", rid(1))
        self.assertTrue(again["refunded"])
        self.assertEqual(self.ledger.usage()["used"], 1)
        self.assertEqual(self.ledger.claim()["receipt_id"], rid(2))
        stopped = self.ledger.cancel("alice", rid(2))
        self.assertEqual((stopped["state"], stopped["refunded"]), ("cancelled", False))
        self.assertEqual(self.ledger.usage()["used"], 1)

    def test_start_then_restart_then_cancel_keeps_quota_used(self):
        self.accept(1)
        self.ledger.claim()
        self.ledger.close()
        self.ledger = TrialLedger(self.path, self.clock)
        receipt = self.ledger.get("alice", rid(1))
        self.assertEqual(receipt["state"], "queued")
        self.assertIsNotNone(receipt["first_started_at"])
        self.assertFalse(self.ledger.cancel("alice", rid(1))["refunded"])
        self.assertEqual(self.ledger.usage()["used"], 1)

    def test_next_day_cancel_refunds_the_acceptance_day_only(self):
        self.accept(1)
        self.clock.advance(days=1)
        self.assertTrue(self.ledger.cancel("alice", rid(1))["refunded"])
        self.assertEqual(self.ledger.usage()["used"], 0)
        with patch.object(trial, "PENDING_LIMIT", 100):
            for n in range(2, 2 + trial.DAILY_LIMIT):
                self.accept(n)
            with self.assertRaises(TrialLimit):
                self.accept(50)

    def test_start_cancel_race_refunds_only_when_cancel_wins(self):
        for n in range(30):
            self.accept(n)
            barrier = threading.Barrier(2)

            def start():
                barrier.wait()
                return self.ledger.claim()

            def cancel():
                barrier.wait()
                return self.ledger.cancel("alice", rid(n))

            with ThreadPoolExecutor(2) as pool:
                started, cancelled = pool.submit(start), pool.submit(cancel)
                started, cancelled = started.result(), cancelled.result()
            final = self.ledger.get("alice", rid(n))
            self.assertEqual(final["state"], "cancelled")
            if started is None:
                self.assertTrue(final["refunded"])
                self.assertIsNone(final["first_started_at"])
            else:
                self.assertFalse(final["refunded"])
                self.assertIsNotNone(final["first_started_at"])
            self.assertEqual(self.ledger.usage()["pending"], 0)

    def test_replay_conflict_and_deleted_receipts(self):
        receipt, created = self.accept(1)
        self.assertTrue(created)
        with patch.object(trial, "DAILY_LIMIT", 1):
            replay, created = self.accept(1)
        self.assertFalse(created)
        self.assertEqual(replay["seq"], receipt["seq"])
        with self.assertRaises(ReceiptConflict):
            self.accept(1, payload={"query": "別のテーマ"})
        with self.assertRaises(ReceiptConflict):
            self.accept(1, operation="retry")
        self.ledger.cancel("alice", rid(1))
        cancelled, created = self.accept(1)
        self.assertEqual((cancelled["state"], created), ("cancelled", False))
        self.assertEqual(self.ledger.usage()["pending"], 0)
        self.ledger.delete("alice", rid(1))
        with self.assertRaises(ReceiptGone):
            self.accept(1)
        with self.assertRaises(ReceiptGone):
            self.accept(1, payload={"query": "別のテーマ"})
        with self.assertRaises(ReceiptGone):
            self.ledger.get("alice", rid(1))

    def test_owners_only_see_and_cancel_their_receipts(self):
        self.accept(1, owner="alice")
        self.accept(1, owner="bob", payload={"query": "別人"})
        self.assertIsNone(self.ledger.cancel("carol", rid(1)))
        self.assertIsNone(self.ledger.get("carol", rid(1)))
        self.assertEqual([r["owner"] for r in self.ledger.listing("bob")], ["bob"])
        self.assertEqual(self.ledger.cancel("alice", rid(1))["owner"], "alice")
        self.assertEqual(self.ledger.get("bob", rid(1))["state"], "queued")
        with self.assertRaises(ValueError):
            self.ledger.accept("", rid(2), "new", {})
        with self.assertRaises(ValueError):
            self.ledger.accept("alice", "short", "new", {})
        with self.assertRaises(ValueError):
            self.ledger.accept("alice", rid(2), "byok", {})

    def test_delete_and_retention_keep_quota_until_ledger_expiry(self):
        self.run_to_completion(1, result={"events": []})
        self.ledger.delete("alice", rid(1))
        self.assertEqual(self.ledger.usage()["used"], 1)
        self.clock.advance(days=trial.LEDGER_DAYS)
        self.assertEqual(self.ledger.purge()["receipts"], 0)
        with self.assertRaises(ReceiptGone):
            self.accept(1)
        self.clock.advance(days=1)
        self.assertEqual(self.ledger.purge()["receipts"], 1)

    def test_temporary_result_expiry_receipt_grace_and_refetch(self):
        self.run_to_completion(1, result={"events": [{"year": 1984}]})
        self.run_to_completion(2, result={"events": []})
        self.assertEqual(self.ledger.get("alice", rid(1))["result"], {"events": [{"year": 1984}]})
        received = self.ledger.receive("alice", rid(1))
        self.assertIsNotNone(received["received_at"])
        self.clock.advance(minutes=trial.RECEIVED_GRACE_MINUTES - 1)
        self.assertIn("result", self.ledger.get("alice", rid(1)))
        self.assertEqual(self.ledger.receive("alice", rid(1)), received)
        self.clock.advance(minutes=1)
        with self.assertRaises(ReceiptGone):
            self.ledger.get("alice", rid(1))
        with self.assertRaises(ReceiptGone):
            self.ledger.receive("alice", rid(1))
        self.assertIsNone(self.ledger.receive("bob", rid(2)))
        self.clock.advance(hours=trial.RESULT_HOURS)
        with self.assertRaises(ReceiptGone):
            self.ledger.get("alice", rid(2))
        self.assertEqual(self.ledger.purge()["results"], 2)
        self.clock.moment = datetime(2026, 10, 11, 23, 0, tzinfo=JST)
        self.assertEqual(self.ledger.usage()["used"], 2)

    def test_failed_and_unstarted_items_cannot_be_finished_or_deleted_early(self):
        self.accept(1)
        self.assertFalse(self.ledger.finish("alice", rid(1), {"events": []}))
        with self.assertRaises(ValueError):
            self.ledger.delete("alice", rid(1))
        self.ledger.claim()
        self.assertTrue(self.ledger.finish("alice", rid(1), None))
        self.assertEqual(self.ledger.get("alice", rid(1))["state"], "failed")
        with self.assertRaises(ValueError):
            self.ledger.cancel("alice", rid(1))

    def test_backups_expire_after_backup_days(self):
        folder = self.temp.name + "/backups"
        first = self.ledger.backup(folder)
        self.clock.advance(days=trial.BACKUP_DAYS, seconds=1)
        second = self.ledger.backup(folder)
        self.assertFalse(first.exists())
        self.assertTrue(second.exists())

    def test_only_one_receipt_runs_at_a_time(self):
        self.accept(1)
        self.accept(2)
        self.assertEqual(self.ledger.claim()["receipt_id"], rid(1))
        self.assertIsNone(self.ledger.claim())
        self.ledger.finish("alice", rid(1), None)
        self.assertEqual(self.ledger.claim()["receipt_id"], rid(2))

    def test_deleted_input_and_result_leave_no_recoverable_text(self):
        marker = "削除される秘密のテーマ"
        self.accept(1, payload={"query": marker})
        self.ledger.claim()
        self.ledger.finish("alice", rid(1), {"events": [{"title": marker}]})
        self.ledger.delete("alice", rid(1))
        with open(self.path, "rb") as handle:
            self.assertNotIn(marker.encode(), handle.read())

    def test_files_are_owner_only_and_backups_ignore_foreign_files(self):
        import os
        folder = self.temp.name + "/backups"
        os.makedirs(folder)
        open(folder + "/trial-latest.sqlite3", "w").close()
        first = self.ledger.backup(folder)
        with self.assertRaises(FileExistsError):
            self.ledger.backup(folder)
        self.clock.advance(microseconds=1)
        self.assertNotEqual(self.ledger.backup(folder), first)
        for path in [self.path, self.path + ".lock", first]:
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertTrue(os.path.exists(folder + "/trial-latest.sqlite3"))

    def test_single_process_owns_the_ledger(self):
        with self.assertRaises(BlockingIOError):
            TrialLedger(self.path, self.clock)


if __name__ == "__main__":
    unittest.main()
