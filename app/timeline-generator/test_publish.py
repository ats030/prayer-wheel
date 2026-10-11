import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import publish


def event(year, url='https://ja.wikipedia.org/wiki/%E6%98%AD%E5%92%8C', title='東京オリンピック'):
    return {'year': year, 'date': f'{year}年', 'title': title, 'description': '説明', 'quote': '根拠の引用',
            'source': {'url': url, 'title': '昭和', 'context_heading': '戦後'}}


def save(db, job_id, result, state='complete'):
    with sqlite3.connect(db) as conn:
        conn.execute('create table if not exists jobs (id text primary key, state text, result text)')
        conn.execute('insert into jobs values (?, ?, ?)', (job_id, state, json.dumps(result, ensure_ascii=False)))


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.db = self.dir / 'jobs.sqlite3'
        self.approved = self.dir / 'approved'

    def tearDown(self):
        self.tmp.cleanup()

    def result(self, *events):
        return {'kind': 'result', 'theme': '昭和', 'period': None, 'events': list(events), 'trace': {'sources': []}, 'pipeline_version': 8, 'source_mode': 'wikipedia'}

    def test_wikipedia_urls_do_not_prove_the_search_route(self):
        for mode in (None, 'searxng'):
            result = self.result(event(1964))
            result.pop('source_mode') if mode is None else result.update(source_mode=mode)
            with self.subTest(mode=mode), self.assertRaises(publish.PublishError):
                publish.public_record(result, '1', 'showa')

    def test_build_rechecks_missing_route_in_legacy_approval(self):
        save(self.db, '1', self.result(event(1964)))
        path = publish.approve(self.db, '1', 'showa', self.approved)
        record = json.loads(path.read_text())
        record.pop('source_mode')
        path.write_text(json.dumps(record))
        with self.assertRaises(publish.PublishError):
            publish.build(self.dir / 'site', self.approved)

    def test_approve_keeps_only_public_fields(self):
        save(self.db, '1', self.result(event(1964)))
        path = publish.approve(self.db, '1', 'showa', self.approved)
        record = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(record['slug'], 'showa')
        self.assertNotIn('trace', record)
        self.assertNotIn('quote', record['events'][0])
        self.assertNotIn('context_heading', record['events'][0]['source'])

    def test_approve_rejects_non_wikipedia_sources(self):
        for url in ('https://example.com/wiki/a', 'http://ja.wikipedia.org/wiki/a', 'https://ja.wikipedia.org.evil.test/wiki/a',
                    'https://de.wikipedia.org/wiki/a', 'javascript:alert(1)', None):
            with self.subTest(url=url):
                save(self.db, str(url), self.result(event(1964), event(1972, url=url)))
                with self.assertRaises(publish.PublishError):
                    publish.approve(self.db, str(url), 'showa', self.approved)
        self.assertFalse(self.approved.exists())

    def test_approve_rejects_unfinished_jobs_and_bad_slugs(self):
        save(self.db, '1', self.result(event(1964)), state='running')
        save(self.db, '2', self.result(event(1964)))
        with self.assertRaises(publish.PublishError):
            publish.approve(self.db, '1', 'showa', self.approved)
        for slug in ('../x', 'Showa', '', '昭和'):
            with self.subTest(slug=slug), self.assertRaises(publish.PublishError):
                publish.approve(self.db, '2', slug, self.approved)

    def test_build_escapes_text_and_links_every_source(self):
        save(self.db, '1', self.result(event(1964, title='<script>alert(1)</script>'), event(1972, url='https://en.wikipedia.org/wiki/Okinawa')))
        publish.approve(self.db, '1', 'showa', self.approved)
        out = self.dir / 'site'
        publish.build(out, self.approved)
        page = (out / 'showa' / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn('<script>alert', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('href="https://en.wikipedia.org/wiki/Okinawa"', page)
        self.assertIn('CC BY-SA 4.0', page)
        self.assertIn('改変', page)
        self.assertIn('href="showa/"', (out / 'index.html').read_text(encoding='utf-8'))
        self.assertTrue((out / 'styles.css').exists() and (out / 'tokens.css').exists())

    def test_build_refuses_a_hand_edited_record_with_a_foreign_source(self):
        save(self.db, '1', self.result(event(1964)))
        path = publish.approve(self.db, '1', 'showa', self.approved)
        record = json.loads(path.read_text(encoding='utf-8'))
        record['events'][0]['source']['url'] = 'https://example.com/'
        path.write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaises(publish.PublishError):
            publish.build(self.dir / 'site', self.approved)

    def test_build_refuses_a_hand_edited_slug(self):
        save(self.db, '1', self.result(event(1964)))
        path = publish.approve(self.db, '1', 'showa', self.approved)
        record = json.loads(path.read_text(encoding='utf-8'))
        record['slug'] = '../x'
        path.write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaises(publish.PublishError):
            publish.build(self.dir / 'site', self.approved)

    def test_withdraw_removes_the_timeline_from_the_next_build(self):
        save(self.db, '1', self.result(event(1964)))
        publish.approve(self.db, '1', 'showa', self.approved)
        out = self.dir / 'site'
        publish.build(out, self.approved)
        publish.withdraw('showa', self.approved)
        self.assertEqual(publish.build(out, self.approved), [])
        self.assertIn('まだありません', (out / 'index.html').read_text(encoding='utf-8'))
        self.assertFalse((out / 'showa').exists())


if __name__ == '__main__':
    unittest.main()
