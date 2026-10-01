"""通知条件と、失敗時に状態を進めない契約の回帰テスト。外部送信はしない。"""

import copy
import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import weather_notify as wn

NOW = datetime(2026, 10, 2, 3, tzinfo=wn.JST)


def forecast(pop=49, high=25, advisory=False):
    return {"area": {"code": "230010"}, "report_datetime": (NOW - timedelta(hours=10)).isoformat(),
            "days": [{"date": NOW.date().isoformat(), "weather": "晴れ", "temp_max": high,
                      "temp_min": 18, "pops": [{"value": pop}]}],
            "alerts": [{"name": "雷注意報", "level": "advisory"}] if advisory else []}


def warning(codes=()):
    return {"reportDatetime": NOW.isoformat(), "areaTypes": [{"areas": [
        {"code": "230010", "warnings": [{"code": c, "status": "継続"} for c in codes]}]}]}


class NotifyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        p = patch.object(wn, "STATE_DIR", Path(self.temp.name))
        p.start()
        self.addCleanup(p.stop)
        wn.save_state("morning.json", {"date": "2026-10-01", "temp_max": 25})

    def morning(self, data):
        with patch.object(wn, "fetch_json", return_value=data):
            return wn.morning(NOW)

    def test_rain_boundary(self):
        self.assertEqual(self.morning(forecast())[0], "")
        self.assertIn("最大 50%", self.morning(forecast(pop=50))[0])

    def test_temperature_boundaries(self):
        for high in (20, 30):
            self.assertIn("前日分の予報との差", self.morning(forecast(high=high))[0])
        for high in (21, 29, None):
            self.assertEqual(self.morning(forecast(high=high))[0], "")

    def test_first_day_and_missing_baseline(self):
        (wn.STATE_DIR / "morning.json").unlink()
        text, _ = self.morning(forecast())
        self.assertIn("最高 25", text)
        self.assertNotIn("予報との差", text)
        wn.save_state("morning.json", {"date": "2026-09-30", "temp_max": 10})
        self.assertEqual(self.morning(forecast())[0], "")

    def test_advisory_and_missing_rain(self):
        text, _ = self.morning(forecast(pop=None, advisory=True))
        self.assertIn("雷注意報", text)
        self.assertNotIn("傘の目安", text)

    def test_stale_or_wrong_area(self):
        data = forecast()
        data["report_datetime"] = (NOW - timedelta(days=2)).isoformat()
        with self.assertRaises(ValueError):
            self.morning(data)
        data = forecast()
        data["area"]["code"] = "130010"
        with self.assertRaises(ValueError):
            self.morning(data)

    def check(self, data, send, dry=False):
        with patch.object(wn, "fetch_json", return_value=data):
            return wn.check_warnings(send, dry)

    def test_initial_duplicate_upgrade_and_reissue(self):
        sent = []
        self.assertTrue(self.check(warning(["03", "14"]), sent.append))
        self.assertEqual(len(sent), 1)
        self.assertFalse(self.check(warning(["03"]), sent.append))
        self.assertTrue(self.check(warning(["33"]), sent.append))
        self.assertIn("大雨特別警報", sent[-1])
        self.assertFalse(self.check(warning(), sent.append))
        self.assertTrue(self.check(warning(["03"]), sent.append))
        self.assertEqual(len(sent), 3)

    def test_send_failure_retries(self):
        wn.save_state("warnings.json", {"codes": ["03"]})
        def fail(text):
            raise OSError("送信失敗")
        with self.assertRaises(OSError):
            self.check(warning(["03", "05"]), fail)
        self.assertEqual(wn.load_state("warnings.json")["codes"], ["03"])
        sent = []
        self.assertTrue(self.check(warning(["03", "05"]), sent.append))
        self.assertIn("暴風警報", sent[0])
        self.assertNotIn("大雨警報", sent[0])

    def test_fetch_failure_preserves_state(self):
        wn.save_state("warnings.json", {"codes": ["03"]})
        with patch.object(wn, "fetch_json", side_effect=OSError("取得失敗")):
            with self.assertRaises(OSError):
                wn.check_warnings(lambda _: self.fail("送信不要"))
        self.assertEqual(wn.load_state("warnings.json")["codes"], ["03"])

    def test_malformed_data_preserves_state(self):
        wn.save_state("warnings.json", {"codes": ["03"]})
        for data in ({}, {"reportDatetime": NOW.isoformat(), "areaTypes": []}):
            with self.assertRaises((KeyError, ValueError)):
                self.check(data, lambda _: self.fail("送信不要"))
        self.assertEqual(wn.load_state("warnings.json")["codes"], ["03"])

    def test_released_warning_is_absent(self):
        data = warning(["03"])
        data["areaTypes"][0]["areas"][0]["warnings"][0]["status"] = "解除"
        self.assertEqual(wn.warning_codes(data), [])

    def test_dry_run_never_sends_or_saves(self):
        self.check(warning(["03"]), lambda _: self.fail("送信不要"), True)
        self.assertEqual(wn.load_state("warnings.json"), {})

    def test_digest_weather_only_and_send_failure(self):
        spec = importlib.util.spec_from_file_location("digest_test", Path(__file__).with_name("morning-digest.py"))
        md = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(md)
        state = {"date": "2026-10-02", "temp_max": 25}
        with patch.object(sys, "argv", ["morning-digest.py"]), \
                patch.object(md, "reflection_section", return_value=(Path("none"), None)), \
                patch.object(md, "load_items", return_value=[]), \
                patch.object(wn, "morning", return_value=("天気通知", state)), \
                patch.object(md, "webhook_url", return_value="https://example.com"), \
                patch.object(md, "post_to_discord", side_effect=OSError("送信失敗")):
            self.assertEqual(md.main(), 1)
        self.assertEqual(wn.load_state("morning.json")["date"], "2026-10-01")


if __name__ == "__main__":
    unittest.main()
