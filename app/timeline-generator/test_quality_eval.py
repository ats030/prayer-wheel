"""Offline quality evaluation against the hand-curated gold set."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import quality_eval as q


def event(year, title, description='', url='https://example.org/a', date=None):
    return {'year': year, 'date': date or f'{year}年', 'title': title, 'description': description,
            'source': {'url': url, 'title': 'x'}, 'quote': ''}


GOLD = {
    'version': 1, 'verified_at': '2026-10-02',
    'themes': {
        'ラーメン': {
            'primary_domains': ['raumen.co.jp'],
            'milestones': [
                {'id': 'rairaiken', 'label': '来々軒', 'years': [1910, 1910], 'keywords': ['来々軒', '來々軒']},
                {'id': 'chicken', 'label': 'チキンラーメン', 'years': [1958, 1958], 'keywords': ['チキンラーメン']},
            ],
            'known_errors': [],
        },
        'インターネット': {
            'primary_domains': [],
            'milestones': [
                {'id': 'arpanet', 'label': 'ARPANET', 'years': [1969, 1969], 'keywords': ['ARPANET']},
                {'id': 'www', 'label': 'WWW', 'years': [1989, 1993], 'keywords': ['WWW']},
            ],
            'known_errors': [{'id': 'vienna', 'label': '断定', 'years': [1683, 1683], 'keywords': ['ウィーン'],
                              'unless': ['伝説']}],
        },
        'Claude Code': {
            'primary_domains': ['anthropic.com'],
            'milestones': [{'id': 'ga', 'label': 'GA', 'years': [2025, 2025], 'dates': ['5月22日'], 'keywords': ['一般']}],
            'known_errors': [],
        },
    },
}


class MatchTests(unittest.TestCase):
    def test_keyword_year_and_date_must_all_match(self):
        item = GOLD['themes']['Claude Code']['milestones'][0]
        self.assertTrue(q.matches(event(2025, '一般提供開始', date='2025年5月22日'), item))
        self.assertFalse(q.matches(event(2025, '一般提供開始', date='2025年'), item))
        self.assertFalse(q.matches(event(2024, '一般提供開始', date='2024年5月22日'), item))

    def test_width_variants_match_but_unless_suppresses(self):
        www = GOLD['themes']['インターネット']['milestones'][1]
        self.assertTrue(q.matches(event(1991, 'ＷＷＷの公開'), www))
        error = GOLD['themes']['インターネット']['known_errors'][0]
        self.assertTrue(q.matches(event(1683, 'ウィーン初のカフェ'), error))
        self.assertFalse(q.matches(event(1683, 'ウィーン初のカフェ', '伝説によれば'), error))

    def test_period_excludes_milestones_outside_requested_range(self):
        self.assertEqual(q.parse_period('1980年 〜 終了指定なし'), (1980, None))
        self.assertEqual(q.parse_period('全期間'), (None, None))
        result = {'theme': 'インターネット', 'period': '1980年 〜 終了指定なし', 'events': [event(1991, 'WWW公開')]}
        report = q.evaluate_result(GOLD, result, 'インターネット 1980年以降')
        self.assertEqual(report['recall'], 1.0)
        self.assertEqual([m['id'] for m in report['found']], ['www'])


class ReportTests(unittest.TestCase):
    def test_recall_sources_and_duplicates(self):
        result = {'theme': 'ラーメン', 'period': '全期間', 'events': [
            event(1910, '淺草 來々軒の開店', url='https://www.raumen.co.jp/x'),
            event(1910, '來々軒', url='https://www.raumen.co.jp/x'),
            event(2000, '個人の感想', url='https://foo.blog.fc2.com/1'),
        ]}
        report = q.evaluate_result(GOLD, result, 'ラーメン')
        self.assertEqual(report['recall'], 0.5)
        self.assertEqual([m['id'] for m in report['missing']], ['chicken'])
        self.assertEqual(len(report['duplicates']), 1)
        self.assertEqual(report['sources']['kinds']['一次/当事者'], 2)
        self.assertEqual(report['sources']['kinds']['個人投稿'], 1)
        self.assertEqual(report['sources']['top_domain'], 'raumen.co.jp')

    def test_missing_stage_requires_keyword_and_year_in_one_passage(self):
        result = {'theme': 'ラーメン', 'period': '全期間', 'events': []}
        pages = {'https://a': ['1958年 日清がチキンラーメンを発売'], 'https://b': ['来々軒は有名', '1910年の話']}
        report = q.evaluate_result(GOLD, result, 'ラーメン', pages)
        stages = {m['id']: m['stage'] for m in report['missing']}
        self.assertTrue(stages['chicken'].startswith('出典内にあり'))
        self.assertTrue(stages['rairaiken'].startswith('出典になし'))

    def test_failed_job_without_result_and_unknown_theme(self):
        self.assertIsNone(q.evaluate_result(GOLD, None, 'AI')['theme'])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'jobs.sqlite3'
            connection = sqlite3.connect(path)
            connection.execute('CREATE TABLE jobs (id INTEGER, query TEXT, state TEXT, result TEXT)')
            connection.execute('INSERT INTO jobs VALUES (1, ?, ?, ?)', ('AI', 'failed', None))
            connection.execute('INSERT INTO jobs VALUES (2, ?, ?, ?)', ('ラーメン', 'complete', json.dumps(
                {'theme': 'ラーメン', 'period': '全期間', 'events': [event(1958, 'チキンラーメン発売')]})))
            connection.commit()
            connection.close()
            report = q.evaluate(GOLD, [('t', path)])
        jobs = report['snapshots'][0]['jobs']
        self.assertEqual(jobs[0]['events'], 0)
        self.assertEqual(jobs[1]['recall'], 0.5)
        self.assertIn('再現率=50%', q.render(report))

    def test_job_quality_for_detail_page(self):
        self.assertIsNone(q.job_quality({'query': 'AI', 'result': None}, GOLD))
        known = q.job_quality({'query': 'ラーメン', 'result': {'theme': 'ラーメン', 'period': '全期間',
                               'events': [event(1958, 'チキンラーメン発売')]}}, GOLD)
        self.assertEqual((known['recall'], known['gold_verified_at']), (0.5, '2026-10-02'))
        other = q.job_quality({'query': '昭和', 'result': {'theme': '昭和', 'period': '全期間',
                               'events': [event(1964, '東京五輪', url='https://ja.wikipedia.org/x')]}}, GOLD)
        self.assertIsNone(other['theme'])
        self.assertNotIn('recall', other)
        self.assertEqual(other['sources']['kinds']['百科(二次)'], 1)

    def test_axes_carry_targets_only_from_the_gold_set(self):
        gold = json.loads(json.dumps(GOLD))
        gold['themes']['ラーメン']['target_recall'] = 1.0
        events = [event(1958, 'チキンラーメン発売', url='https://www.raumen.co.jp/a'),
                  event(1958, 'チキンラーメン', url='https://www.raumen.co.jp/a'),
                  event(1971, 'カップヌードル発売', url='https://note.com/x'),
                  event(1994, '新横浜ラーメン博物館開館', url='https://ja.wikipedia.org/x')]
        known = q.job_quality({'query': 'ラーメン', 'result': {'theme': 'ラーメン', 'period': '全期間', 'events': events,
                               'elapsed_seconds': 1800, 'stop_reason': 'time_limit'}}, gold)
        axes = {a['key']: a for a in known['axes']}
        self.assertEqual((axes['recall']['value'], axes['recall']['target'], axes['recall']['passed']), (0.5, 1.0, False))
        self.assertIn('来々軒', axes['recall']['note'])
        self.assertTrue(axes['known_errors']['passed'])
        self.assertEqual((axes['duplicates']['value'], axes['duplicates']['passed']), (0.25, False))
        self.assertEqual((axes['primary']['value'], axes['personal']['value']), (0.5, 0.25))
        self.assertEqual((axes['concentration']['value'], axes['events']['display']), (0.5, '4 / 100件'))
        self.assertEqual(axes['elapsed']['value'], 0.5)
        self.assertEqual(axes['elapsed']['note'], '時間上限で終了（当時の短い上限）')
        same = [event(1958, 'チキンラーメン', url='https://www.raumen.co.jp/a')] * 4
        clamped = {a['key']: a for a in q.job_quality({'query': 'ラーメン', 'result': {'theme': 'ラーメン', 'events': same}}, gold)['axes']}
        self.assertEqual((clamped['duplicates']['value'], clamped['duplicates']['display']), (1.0, '6組'))
        self.assertTrue(all(a['passed'] is None for k, a in axes.items() if k not in ('recall', 'known_errors', 'duplicates')))
        other = q.job_quality({'query': '昭和', 'result': {'theme': '昭和', 'events': []}}, gold)
        recall = other['axes'][0]
        self.assertEqual((recall['key'], recall['value'], recall['display']), ('recall', None, '正解集合の対象外'))
        self.assertNotIn('known_errors', [a['key'] for a in other['axes']])
        self.assertIsNone(next(a for a in other['axes'] if a['key'] == 'primary')['value'])

    def test_bundled_gold_set_is_well_formed(self):
        gold = json.loads(q.GOLD_PATH.read_text(encoding='utf-8'))
        for name, theme in gold['themes'].items():
            self.assertTrue(theme['milestones'], name)
            self.assertEqual(theme['target_recall'], 1.0, name)
            for item in theme['milestones'] + theme['known_errors']:
                self.assertTrue(item['keywords'] and item['evidence'], item['id'])
                if 'years' in item:
                    self.assertLessEqual(item['years'][0], item['years'][1], item['id'])


if __name__ == '__main__':
    unittest.main()
