#!/usr/bin/env python3
"""Month listing items link to their own festival page and keep a map link."""
from datetime import date
import unittest

from festival_calendar import render

FESTIVALS = [{'qid': 'Q1', 'label_ja': '十月祭', 'prefecture': '群馬県',
              'occurrences': [{'start': '2026-10-20', 'source': 'https://example.jp/oct'}]}]


class PageLinkChecks(unittest.TestCase):
    def test_item_title_links_to_festival_page_and_map_link_remains(self):
        html = render(FESTIVALS, date(2026, 10, 11))
        self.assertIn('<h3><a href="/festivals/Q1">十月祭</a></h3>', html)
        self.assertIn('<a href="/?kind=omatsuri&amp;qid=Q1">地図で見る</a>', html)


if __name__ == '__main__':
    unittest.main()
