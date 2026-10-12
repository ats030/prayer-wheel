#!/usr/bin/env python3
"""Per-festival pages carry only sourced facts and point back to the map."""
from datetime import date
import json
import unittest

from festival_page import render_page

TODAY = date(2026, 10, 11)
FESTIVAL = {
    'qid': 'Q1', 'label_ja': '秋<祭>', 'prefecture': '群馬県',
    'description': '山車が出る。', 'description_source': 'https://ja.wikipedia.org/wiki/x',
    'occurrences': [
        {'start': '2026-10-20', 'end': '2026-10-21', 'source': 'https://example.jp/oct'},
        {'start': '2026-11-03', 'status': 'scheduled', 'source': 'https://example.jp/nov'},
        {'start': '2025-10-20', 'end': '2025-10-21', 'source': 'https://example.jp/old'},
        {'start': '2026-12-01', 'source': 'javascript:alert(1)'},
        {'start': '2026-12-05'},
    ],
}


class PageChecks(unittest.TestCase):
    def setUp(self):
        self.html = render_page(FESTIVAL, TODAY)

    def test_head_has_escaped_title_canonical_and_visit_log(self):
        self.assertTrue(self.html.startswith('<!doctype html>'))
        self.assertIn('<title>秋&lt;祭&gt;｜みどころマップ</title>', self.html)
        self.assertIn('<link rel="canonical" href="https://midokoro-map.ats030.workers.dev/festivals/Q1">', self.html)
        self.assertIn('<script src="http://ubuntu-server-app:8526/v.js" data-site="midokoro-map" defer></script>', self.html)
        self.assertIn('<h1>秋&lt;祭&gt;</h1>', self.html)
        self.assertIn('群馬県', self.html)

    def test_lists_upcoming_sourced_dates_only(self):
        self.assertIn('10月20日〜21日', self.html)
        self.assertIn('11月3日（予定）', self.html)
        self.assertIn('<a href="https://example.jp/oct" rel="noopener">example.jp</a>', self.html)
        for absent in ('example.jp/old', 'javascript:', '12月5日', '12月1日'):
            self.assertNotIn(absent, self.html)

    def test_description_shown_only_with_http_source(self):
        self.assertIn('山車が出る。', self.html)
        self.assertIn('<a href="https://ja.wikipedia.org/wiki/x" rel="noopener">ja.wikipedia.org</a>', self.html)
        html = render_page(dict(FESTIVAL, description_source=''), TODAY)
        self.assertNotIn('山車が出る。', html)

    def test_links_back_to_map(self):
        self.assertIn('href="/?kind=omatsuri&amp;qid=Q1"', self.html)
        self.assertNotIn('href="/festivals"', self.html)

    def test_no_upcoming_dates_says_so(self):
        html = render_page(dict(FESTIVAL, occurrences=[]), TODAY)
        self.assertIn('次回の日程は確認できていません。', html)
        self.assertNotIn('application/ld+json', html)

    def test_page_shares_the_site_frame(self):
        for part in ('name="viewport"', 'name="description"', 'property="og:url" content="https://midokoro-map.ats030.workers.dev/festivals/Q1"',
                     'href="/app.css"', 'href="/stories/story.css"', 'class="story-page"', 'class="skip-link"', 'class="site-header"'):
            self.assertIn(part, self.html)

    def test_event_data_lists_only_shown_dates(self):
        raw = self.html.split('<script type="application/ld+json">', 1)[1].split('</script>', 1)[0]
        self.assertNotIn('<', raw)
        events = json.loads(raw)
        self.assertEqual([(e['startDate'], e['endDate']) for e in events],
                         [('2026-10-20', '2026-10-21'), ('2026-11-03', '2026-11-03')])
        self.assertEqual(events[0]['name'], '秋<祭>')
        self.assertEqual(events[0]['location']['address']['addressRegion'], '群馬県')


if __name__ == '__main__':
    unittest.main()
