"""送信に失敗しても後から分かること (ats030-we1i)。

2026-08-22 23:00 の通知が Discord の 403 で失敗し、翌日 systemctl --user
list-units --state=failed を手で見るまで誰も知らなかった。OnFailure の通知先も
同じ Webhook なので、Discord 側の問題では失敗の知らせも届かない。

凍結21件の見直しがこの通知に乗っているため、届かないと二度と目に入らない。
欠測を次の成功時に必ず伝える。
"""

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import notify


class TestMissedRuns:
    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = notify.STATE_PATH
        notify.STATE_PATH = Path(self._tmp.name) / "last-send.json"

    def teardown_method(self):
        notify.STATE_PATH = self._orig
        self._tmp.cleanup()

    def test_no_state_reports_nothing(self):
        """初回は欠測を主張しない"""
        assert notify.missed_note(date(2026, 8, 30)) == ""

    def test_success_leaves_no_note(self):
        notify.record_send(True, date(2026, 8, 23))
        assert notify.missed_note(date(2026, 8, 30)) == ""

    def test_failure_is_reported_next_time(self):
        """前回落ちていたら、次に届いた本文で知らせる"""
        notify.record_send(False, date(2026, 8, 23))
        note = notify.missed_note(date(2026, 8, 30))
        assert "2026-08-23" in note
        assert "届かなかった" in note

    def test_consecutive_failures_are_counted(self):
        for d in (date(2026, 8, 23), date(2026, 8, 30), date(2026, 9, 6)):
            notify.record_send(False, d)
        note = notify.missed_note(date(2026, 9, 13))
        assert "3回" in note

    def test_success_clears_the_streak(self):
        notify.record_send(False, date(2026, 8, 23))
        notify.record_send(True, date(2026, 8, 30))
        assert notify.missed_note(date(2026, 9, 6)) == ""

    def test_broken_state_file_is_ignored(self):
        """状態が壊れていても通知そのものは止めない"""
        notify.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        notify.STATE_PATH.write_text("{ではない", encoding="utf-8")
        assert notify.missed_note(date(2026, 8, 30)) == ""

    def test_state_is_written_where_it_can_be_regenerated(self):
        """~/cache 相当。失われても次回の通知が作り直すだけ"""
        notify.record_send(True, date(2026, 8, 23))
        assert json.loads(notify.STATE_PATH.read_text(encoding="utf-8"))["ok"] is True


class TestMessage:
    def test_note_is_placed_at_the_top(self):
        """欠測は本文の先頭に置く。埋もれると気づけない"""
        summary = {"remaining": 1, "deferred": 0, "over_30_days": 0, "median_age": 1,
                   "delta_7d": 0, "freeze_expired": 0, "freeze_undated": 0, "oldest": []}
        msg = notify.build_message(summary, date(2026, 8, 30), missed="⚠ 前回は届かなかった")
        assert msg.splitlines()[0] == "⚠ 前回は届かなかった"
