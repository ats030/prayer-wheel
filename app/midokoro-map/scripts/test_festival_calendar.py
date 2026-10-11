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


def month(html, key):
    start = html.index(f'<section class="story-reading" id="m-{key}"')
    return html[start:html.index('</section>', start)]


class CalendarChecks(unittest.TestCase):
    def setUp(self):
        self.html = render(FESTIVALS, date(2026, 10, 11))
        self.this_month = month(self.html, '2026-10')
        self.next_month = month(self.html, '2026-11')

    def test_lists_only_dated_sourced_current_occurrences(self):
        self.assertIn('十月祭', self.this_month)
        self.assertIn('霜月祭', self.next_month)
        self.assertIn('師走祭', month(self.html, '2026-12'))
        for absent in ('未定祭', '終了祭', '出典なし祭', 'スクリプト祭'):
            self.assertNotIn(absent, self.html)

    def test_items_carry_end_date_for_reader_side_expiry(self):
        self.assertIn('<li data-end="2026-11-02">', self.this_month)

    def test_builds_twelve_months_but_omits_empty_later_months(self):
        self.assertIn('id="m-2026-10"', self.html)
        self.assertIn('id="m-2026-11"', self.html)
        self.assertNotIn('id="m-2027-01"', self.html)
        late = FESTIVALS + [festival('Q9', '晩夏祭', {'year': 2027, 'start': '2027-09-10', 'source': 'https://example.jp/sep'}),
                            festival('Q10', '翌秋祭', {'year': 2027, 'start': '2027-10-10', 'source': 'https://example.jp/oct27'})]
        html = render(late, date(2026, 10, 11))
        self.assertIn('晩夏祭', month(html, '2027-09'))
        self.assertNotIn('翌秋祭', html)

    def test_empty_this_and_next_month_still_render_with_note(self):
        html = render([], date(2026, 10, 11))
        self.assertIn('この月に日程が確定している祭りはまだ登録されていません。</p>', month(html, '2026-10'))
        self.assertIn('id="m-2026-11"', html)
        self.assertIn('<p class="calendar-empty" hidden>', self.this_month)

    def test_page_loads_reader_date_script(self):
        self.assertIn('<script src="/festivals/calendar.js" defer></script>', self.html)
        self.assertIn('href="#m-2026-10">今月（2026年10月）', self.html)

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
