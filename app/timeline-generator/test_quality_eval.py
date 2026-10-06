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
                {'id': 'www', 'label': 'WWW', 'years': [1989, 1993], 'keywords': ['WWW', 'ワールドワイドウェブ']},
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
        self.assertTrue(q.matches(event(1991, 'ワールド・ワイド・ウェブの発明'), www))
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
        pages = {'https://a': [('1958年日清がチキンラーメンを発売', 'k1')], 'https://b': [('来々軒は有名', 'k2'), ('1910年の話', 'k3')]}
        report = q.evaluate_result(GOLD, result, 'ラーメン', pages)
        stages = {m['id']: m['stage'] for m in report['missing']}
        self.assertTrue(stages['chicken'].startswith('出典内にあり'))
        self.assertTrue(stages['rairaiken'].startswith('出典になし'))

    def test_trace_splits_missing_items_into_processing_stages(self):
        pages = {'https://a': [('1958年日清がチキンラーメンを発売', 'k1'), ('1910年来々軒が開店', 'k2')],
                 'https://b': [('1910年來々軒の創業', 'k3')]}
        trace = {'batches_total': 3, 'batches_processed': 1, 'sources': ['https://a', 'https://b'],
                 'batches': [{'passages': [[0, 'k1']], 'processed': True}, {'passages': [[1, 'k3']], 'processed': False},
                             {'passages': [[0, 'k2']], 'processed': False}],
                 'rejected': []}
        result = {'theme': 'ラーメン', 'period': '全期間', 'events': [], 'trace': trace, 'stop_reason': 'time_limit'}
        stages = {m['id']: m for m in q.evaluate_result(GOLD, result, 'ラーメン', pages)['missing']}
        self.assertEqual(stages['chicken']['stage'], '候補に出ず')
        self.assertEqual(stages['rairaiken']['stage'], '未処理（時間上限）')
        self.assertIn('第2組', stages['rairaiken']['reason'])
        stages = {m['id']: m for m in q.evaluate_result(GOLD, {**result, 'stop_reason': 'event_limit'}, 'ラーメン', pages)['missing']}
        self.assertEqual(stages['rairaiken']['stage'], '未処理（件数上限）')
        trace['batches'][0]['error'] = 'モデル応答が不正'
        stages = {m['id']: m for m in q.evaluate_result(GOLD, result, 'ラーメン', pages)['missing']}
        self.assertEqual(stages['chicken']['stage'], '処理失敗')
        self.assertIn('モデル応答が不正', stages['chicken']['reason'])
        del trace['batches'][0]['error']
        trace['batches'][2]['processed'] = True
        trace['rejected'] = [{'batch': 1, 'year': 1958, 'date': '1958年', 'title': 'チキンラーメン発売', 'stage': '検証', 'reason': '年が違う'}]
        stages = {m['id']: m for m in q.evaluate_result(GOLD, result, 'ラーメン', pages)['missing']}
        self.assertEqual(stages['chicken']['stage'], '検証で除外')
        self.assertIn('年が違う', stages['chicken']['reason'])
        self.assertEqual(stages['rairaiken']['stage'], '候補に出ず')
        # 題名に語がなくても、説明に語があれば却下候補として一致させる（ats030-1gqzq）
        trace['rejected'] = [{'batch': 1, 'year': 1958, 'date': '1958年', 'title': '即席麺の誕生', 'description': '日清がチキンラーメンを発売した。', 'stage': '検査', 'reason': '年が引用・段落に書かれていない'}]
        stages = {m['id']: m for m in q.evaluate_result(GOLD, result, 'ラーメン', pages)['missing']}
        self.assertEqual((stages['chicken']['stage'], stages['chicken']['candidate']), ('検証で除外', '即席麺の誕生'))
        # 説明のない旧記録は段階を変えず、該当段落の組で年が合う却下候補を手がかりに示すだけにする
        trace['rejected'] = [{'batch': 1, 'year': 1958, 'date': '1958年', 'title': '即席麺の誕生', 'stage': '検査', 'reason': '年が引用・段落に書かれていない'},
                             {'batch': 1, 'year': 1910, 'date': '1910年', 'title': '浅草の店', 'stage': '検査', 'reason': '該当段落のない組'}]
        stages = {m['id']: m for m in q.evaluate_result(GOLD, result, 'ラーメン', pages)['missing']}
        self.assertEqual(stages['chicken']['stage'], '候補に出ず')
        self.assertIn('同組・同年の却下候補: 即席麺の誕生（検査）', stages['chicken']['reason'])
        self.assertNotIn('浅草', stages['rairaiken']['reason'])
        trace['batches'] = []
        stages = {m['id']: m for m in q.evaluate_result(GOLD, result, 'ラーメン', pages)['missing']}
        self.assertEqual(stages['rairaiken']['stage'], 'どの組にも一致しない')
        self.assertTrue(q.evaluate_result(GOLD, {**result, 'trace': None}, 'ラーメン', pages)['missing'][0]['stage'].startswith('出典内にあり'))

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

    def test_running_job_of_a_gold_theme_has_no_recall(self):
        # 実行中のジョブは result が null でも query から正解テーマが決まる。
        report = q.evaluate_result(GOLD, None, 'ラーメン')
        self.assertEqual((report['theme'], report.get('recall'), report['events']), ('ラーメン', None, 0))

    def test_replay_counts_only_events_adopted_within_the_cutoff(self):
        result = {'period': '全期間', 'events': [event(1910, '来々軒開業'), event(1958, 'チキンラーメン発売')],
                  'trace': {'batches': [{'processed': True, 'seconds': 100.0, 'passages': [], 'adopted': [[1910, '来々軒開業']]},
                                        {'processed': True, 'seconds': 50.5, 'passages': [], 'adopted': [[1958, 'チキンラーメン発売'], [1990, '関連度で外れた']]},
                                        {'processed': False, 'passages': []}]}}
        replay = q.replay(GOLD, result, 'ラーメン', (1, 2))
        self.assertEqual((replay['method'], replay['unplaced']), ('trace', 0))
        self.assertEqual([(r['recall'], r['found'], r['batch_seconds']) for r in replay['cutoffs']],
                         [(0.5, ['rairaiken'], 100.0), (1.0, ['rairaiken', 'chicken'], 150.5)])

    def test_replay_credits_a_repeated_year_and_title_to_the_later_batch(self):
        # 年と題だけでは同名の出来事を区別できないので、早い打ち切りの再現率を過大にしない側へ寄せる。
        result = {'period': '全期間', 'events': [event(1958, 'チキンラーメン発売')],
                  'trace': {'batches': [{'processed': True, 'passages': [], 'adopted': [[1958, 'チキンラーメン発売']]},
                                        {'processed': True, 'passages': [], 'adopted': [[1958, 'チキンラーメン発売']]}]}}
        self.assertEqual([r['found'] for r in q.replay(GOLD, result, 'ラーメン', (1, 2))['cutoffs']], [[], ['chicken']])

    def test_replay_cutoffs_must_be_positive_integers(self):
        self.assertEqual(q.cutoff_list('2, 4,8'), (2, 4, 8))
        for text in ('0', '-1', 'a', ''):
            with self.assertRaises(q.argparse.ArgumentTypeError):
                q.cutoff_list(text)

    def test_replay_estimates_batches_for_old_traces_by_quote(self):
        first, second = event(1910, '来々軒開業'), event(1958, 'チキンラーメン発売')
        first['quote'], second['quote'] = '浅草に来々軒が開業した。', '日清食品がチキンラーメンを発売した。'
        result = {'period': '全期間', 'events': [first, second, event(1970, '出典不明')],
                  'trace': {'batches': [{'processed': True, 'passages': [[0, '浅草に来々軒が開業した。']]},
                                        {'processed': True, 'passages': [[0, '日清食品がチキンラーメンを発売した。']]}]}}
        replay = q.replay(GOLD, result, 'ラーメン', (1,))
        self.assertEqual((replay['method'], replay['unplaced']), ('estimated', 1))
        self.assertEqual(replay['cutoffs'][0]['found'], ['rairaiken'])
        self.assertIsNone(replay['cutoffs'][0]['batch_seconds'])
        self.assertIsNone(q.replay(GOLD, {**result, 'trace': None}, 'ラーメン', (1,)))

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
        self.assertEqual((axes['concentration']['value'], axes['events']['display']), (0.5, '4 / 50件'))
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

    def test_bundled_gold_credits_year_only_claude_code_release_and_ga(self):
        # 年だけの採用項目も、研究プレビューと一般提供を取り違えずに一致させる（ats030-1gqzq）
        gold = json.loads(q.GOLD_PATH.read_text(encoding='utf-8'))
        result = {'theme': 'Claude Code', 'period': '全期間', 'events': [
            event(2025, 'Claude Codeのリリース', 'ターミナルから使うエージェント型ツールが公開された。', date='2025年'),
            event(2025, 'Claude Codeの一般提供開始', 'リサーチプレビューから一般提供へと移行した。', date='2025年'),
            event(2025, 'Web版の導入', 'Claude CodeのWeb版をリリースした。', date='2025年10月20日')]}
        found = {f['id']: f['event'] for f in q.evaluate_result(gold, result, 'Claude Code')['found']}
        self.assertEqual(found['preview'], 'Claude Codeのリリース')
        self.assertEqual(found['ga'], 'Claude Codeの一般提供開始')
        result['events'] = result['events'][1:]
        self.assertNotIn('preview', {f['id'] for f in q.evaluate_result(gold, result, 'Claude Code')['found']})

    def test_bundled_gold_credits_istanbul_from_the_1550s_wording(self):
        # Wikipediaは「1550年代」とだけ書き、生成は年代の開始年1550を出す。1554年説の資料がなくても一致させる（ats030-elou2）
        gold = json.loads(q.GOLD_PATH.read_text(encoding='utf-8'))
        result = {'theme': 'コーヒー', 'period': '全期間', 'events': [
            event(1550, 'イスタンブールでのコーヒー店開店', '1550年代にイスタンブールにコーヒーを提供する店舗が開かれた。', date='1550年')]}
        self.assertIn('istanbul', {f['id'] for f in q.evaluate_result(gold, result, 'コーヒー')['found']})
        page = {'passages': [{'heading': '歴史', 'text': '1550年代にはイスタンブールにもコーヒーを提供する店舗が開かれた。'}]}
        item = next(m for m in gold['themes']['コーヒー']['milestones'] if m['id'] == 'istanbul')
        self.assertTrue(q.locate_in_sources(item, {'https://ja.wikipedia.org/wiki/x': q.page_passages(page)}))

    def test_bundled_gold_credits_brazil_from_the_1726_wording(self):
        # Wikipediaは導入を「1726年ブラジルへ持ち込まれ」、パレータの伝承を1727年と書く。どちらの年でも一致させる（ats030-9hjg8）
        gold = json.loads(q.GOLD_PATH.read_text(encoding='utf-8'))
        result = {'theme': 'コーヒー', 'period': '全期間', 'events': [
            event(1726, 'ブラジルへのコーヒー持ち込みと大規模栽培への展開', '1726年にブラジルへコーヒーが持ち込まれ、その後の大規模な栽培へとつながった。')]}
        self.assertIn('brazil', {f['id'] for f in q.evaluate_result(gold, result, 'コーヒー')['found']})

    def test_bundled_gold_credits_java_from_the_1680_wording(self):
        # Wikipediaは苗木の移植を1680年、バタヴィアの農園設置を1696年と書く。どちらの年でも一致させる（ats030-ira82）
        gold = json.loads(q.GOLD_PATH.read_text(encoding='utf-8'))
        result = {'theme': 'コーヒー', 'period': '全期間', 'events': [
            event(1680, 'ジャワ島へのコーヒーの木移植', '1680年にオランダがイエメンから取り寄せたコーヒーの木をジャワ島に移植した。')]}
        self.assertIn('java', {f['id'] for f in q.evaluate_result(gold, result, 'コーヒー')['found']})

    def test_bundled_gold_credits_tcpip_from_the_complete_switch_wording(self):
        # 「TCP/IPへの完全な切り替え」のように修飾語が挟まっても、1983年のARPANET移行として数える
        gold = json.loads(q.GOLD_PATH.read_text(encoding='utf-8'))
        result = {'theme': 'インターネット', 'period': '全期間', 'events': [
            event(1983, 'ARPANETのTCP/IPへの完全な切り替え', '1983年1月1日、ARPANETはTCP/IPへ完全に切り替えられた。')]}
        self.assertIn('tcpip', {f['id'] for f in q.evaluate_result(gold, result, 'インターネット')['found']})

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
