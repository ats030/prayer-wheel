import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).with_name("enrich_wikidata_dates.py")
SPEC = importlib.util.spec_from_file_location("date_enricher", MODULE_PATH)
date_enricher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(date_enricher)


class DateEnricherTest(unittest.TestCase):
    def test_parses_fixed_and_weekday_rules(self):
        self.assertEqual(date_enricher.parse_calendar_item("10月22日")["day"], 22)
        self.assertEqual(date_enricher.parse_calendar_item("10月の第2月曜日")["weekday"], 1)
        self.assertEqual(date_enricher.parse_calendar_item("2月の最終日曜日")["kind"], "last_weekday")
        self.assertEqual(date_enricher.parse_calendar_item("大晦日")["month"], 12)

    def test_rejects_month_only_and_lunar_dates(self):
        self.assertIsNone(date_enricher.parse_calendar_item("10月"))
        self.assertIsNone(date_enricher.parse_calendar_item("旧暦8月15日"))

    def test_groups_consecutive_fixed_dates(self):
        items = [date_enricher.parse_calendar_item(label) for label in ("10月9日", "10月7日", "10月8日")]
        self.assertEqual(
            date_enricher.group_fixed_dates(items),
            [{"kind": "fixed", "start": "10-07", "end": "10-09"}],
        )

    def test_requires_every_linked_value_to_be_resolvable(self):
        festival_entities = {
            "Q1": {"claims": {"P837": [claim("QDAY")]}},
            "Q2": {"claims": {"P837": [claim("QDAY"), claim("QMONTH")]}},
        }
        calendar_entities = {
            "QDAY": {"labels": {"ja": {"value": "8月2日"}}},
            "QMONTH": {"labels": {"ja": {"value": "8月"}}},
        }
        schedules = date_enricher.schedules_by_festival(festival_entities, calendar_entities)
        self.assertIn("Q1", schedules)
        self.assertNotIn("Q2", schedules)


def claim(qid):
    return {"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": qid}}}}


if __name__ == "__main__":
    unittest.main()
