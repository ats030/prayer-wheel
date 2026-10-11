#!/usr/bin/env python3
"""The month listing shows only dated, sourced occurrences and links back to the map."""
from datetime import date
import unittest

from festival_calendar import render


def festival(qid, label, *occurrences, date_text=''):
    return {'qid': qid, 'label_ja': label, 'prefecture': '群馬県', 'date': date_text, 'occurrences': list(occurrences)}


FESTIVALS = [
    festival('Q1', '十月祭', {'year': 2026, 'start': '2026-10-20', 'end': '2026-10-21', 'source': 'https://example.jp/oct'}),
    festival('Q2', '霜月祭', {'year': 2026, 'start': '2026-11-03', 'end': '2026-11-03', 'status': 'scheduled', 'source': 'https://example.jp/nov'}),
    festival('Q3', '未定祭'),
    festival('Q4', '終了祭', {'year': 2026, 'start': '2026-10-01', 'end': '2026-10-02', 'source': 'https://example.jp/done'}),
    festival('Q5', '出典なし祭', {'year': 2026, 'start': '2026-10-25', 'end': '2026-10-25'}),
    festival('Q8', 'スクリプト祭', {'year': 2026, 'start': '2026-10-25', 'end': '2026-10-25', 'source': 'javascript:alert(1)'}),
    festival('Q6', '師走祭', {'year': 2026, 'start': '2026-12-05', 'end': '2026-12-05', 'source': 'https://example.jp/dec'}),
    festival('Q7', '月またぎ祭', {'year': 2026, 'start': '2026-10-31', 'end': '2026-11-02', 'source': 'https://example.jp/span'}),
]


class CalendarChecks(unittest.TestCase):
    def setUp(self):
        self.html = render(FESTIVALS, date(2026, 10, 11))
        self.this_month, self.next_month = self.html.split('id="next-month"', 1)

    def test_lists_only_dated_sourced_current_occurrences(self):
        self.assertIn('十月祭', self.this_month)
        self.assertIn('霜月祭', self.next_month)
        for absent in ('未定祭', '終了祭', '出典なし祭', 'スクリプト祭', '師走祭'):
            self.assertNotIn(absent, self.html)

    def test_each_item_shows_source_and_links_to_map_detail(self):
        self.assertIn('href="/?kind=omatsuri&amp;qid=Q1"', self.html)
        self.assertIn('日程の出典: <a href="https://example.jp/oct"', self.html)
        self.assertIn('11月3日（予定）', self.next_month)

    def test_spanning_occurrence_appears_in_both_months(self):
        self.assertIn('月またぎ祭', self.this_month)
        self.assertIn('月またぎ祭', self.next_month)
        self.assertIn('10月31日〜11月2日', self.this_month)

    def test_december_rolls_into_january(self):
        html = render(FESTIVALS, date(2026, 12, 1))
        self.assertIn('2026年12月', html)
        self.assertIn('2027年1月', html)
        self.assertIn('師走祭', html)

    def test_page_carries_visit_log_and_canonical(self):
        self.assertIn('data-site="midokoro-map"', self.html)
        self.assertIn('<link rel="canonical" href="https://midokoro-map.ats030.workers.dev/festivals">', self.html)


if __name__ == '__main__':
    unittest.main()
