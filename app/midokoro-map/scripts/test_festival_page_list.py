#!/usr/bin/env python3
"""Only festivals with a dated, http-sourced occurrence get a page and a sitemap entry."""
import unittest

from festival_page import page_qids, sitemap_entries

FESTIVALS = [
    {'qid': 'Q20', 'occurrences': [{'start': '2025-05-01', 'source': 'https://example.jp/a'}]},
    {'qid': 'Q3', 'occurrences': [{'start': '2026-10-01', 'end': '2026-10-02', 'source': 'http://example.jp/b'}]},
    {'qid': 'Q4', 'occurrences': [{'start': '2026-10-01'}]},
    {'qid': 'Q5', 'occurrences': [{'start': '2026-10-01', 'source': 'javascript:alert(1)'}]},
    {'qid': 'Q6', 'occurrences': [{'start': '未定', 'source': 'https://example.jp/c'}]},
    {'qid': 'Q7'},
    {'qid': '', 'occurrences': [{'start': '2026-10-01', 'source': 'https://example.jp/d'}]},
]


class ListChecks(unittest.TestCase):
    def test_page_qids_keeps_dated_sourced_festivals_sorted_without_duplicates(self):
        self.assertEqual(page_qids(FESTIVALS + FESTIVALS[:1]), ['Q20', 'Q3'])

    def test_sitemap_entries_use_public_origin(self):
        self.assertEqual(sitemap_entries(['Q20', 'Q3']),
                         '<url><loc>https://midokoro-map.ats030.workers.dev/festivals/Q20</loc></url>\n'
                         '<url><loc>https://midokoro-map.ats030.workers.dev/festivals/Q3</loc></url>\n')


if __name__ == '__main__':
    unittest.main()
