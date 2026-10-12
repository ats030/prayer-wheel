import re
from types import SimpleNamespace
import unittest

from byok_metrics import MaterialMetrics


class MaterialMetricTests(unittest.TestCase):
    def test_counts_preserve_material_and_do_not_retain_text(self):
        sources = [{"passages": [{"text": "1926年 SECRET", "date_heading": ""},
                                  {"text": "本文", "date_heading": "1945年"},
                                  {"text": "本文", "date_heading": ""}]}]
        timeline = SimpleNamespace(DATE_PATTERN=re.compile(r"\d{4}年"),
            fetch_sources=lambda: sources,
            material_batches=lambda material, query: iter([material, material]))
        metrics = MaterialMetrics(timeline)
        self.assertIs(timeline.fetch_sources(), sources)
        batches = list(timeline.material_batches(sources, "昭和"))
        self.assertIs(batches[0], sources)
        self.assertEqual(metrics.summary(), {"sources_fetched": 1, "passages_fetched": 3,
            "dated_passages_fetched": 2, "batches_total": 2, "passage_appearances_in_batches": 6})
        snapshot = metrics.summary()
        snapshot["sources_fetched"] = 0
        self.assertEqual(metrics.summary()["sources_fetched"], 1)
        self.assertNotIn("SECRET", repr(vars(metrics)))


if __name__ == "__main__":
    unittest.main()
