"""確認済みの年表だけを静的HTMLとして公開する（ats030-udy41）。

    python3 publish.py candidates <db>              # 承認できる年表を一覧する
    python3 publish.py approve <db> <job_id> <slug> # 1件を承認して公開対象に加える
    python3 publish.py withdraw <slug>              # 公開対象から外す
    python3 publish.py build <out_dir>              # 承認済みの年表から静的サイトを書き出す

公開側は書き出したHTMLを配るだけで、生成キューにも保存DBにも触れない。
出典はWikipediaの記事に限る。SearXNG経由の検索結果は商用公開の許可がないため（ats030-3l22f）。
承認した年表は再生成で戻らないため ~/data に置く。
"""
import argparse
import html
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

APP_DIR = Path(__file__).resolve().parent
APPROVED_DIR = Path(os.environ.get('TIMELINE_PUBLIC_DIR', Path.home() / 'data' / 'timeline-public'))
ALLOWED_HOSTS = {'ja.wikipedia.org', 'en.wikipedia.org'}
SLUG = re.compile(r'[a-z0-9][a-z0-9-]{0,62}')
ASSETS = ('tokens.css', 'styles.css', 'favicon.svg')


class PublishError(Exception):
    pass


def wikipedia_url(url):
    try:
        parts = urlsplit(url)
    except (TypeError, ValueError):
        return False
    return parts.scheme == 'https' and parts.hostname in ALLOWED_HOSTS and parts.path.startswith('/wiki/')


def load_job(db, job_id):
    with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as conn:
        row = conn.execute('select state, result from jobs where id = ?', (job_id,)).fetchone()
    if row is None:
        raise PublishError(f'ジョブ {job_id} がありません')
    state, result = row
    if state != 'complete' or not result:
        raise PublishError(f'ジョブ {job_id} は完了していません（{state}）')
    return json.loads(result)


def public_record(result, job_id, slug):
    """公開に必要な項目だけを取り出す。根拠の引用や生成の内部記録は出さない。"""
    if result.get('kind') != 'result' or not result.get('events'):
        raise PublishError('出来事のない年表は公開できません')
    if result.get('source_mode') != 'wikipedia':
        raise PublishError('Wikipedia限定の生成記録が必要です。出典URLだけでは検索経路を確認できません。')
    events = []
    for event in result['events']:
        source = event.get('source') or {}
        if not wikipedia_url(source.get('url')):
            raise PublishError(f'出典がWikipediaの記事ではありません: {event.get("date")} {event.get("title")} {source.get("url")}')
        events.append({'year': event['year'], 'date': event['date'], 'title': event['title'], 'description': event['description'],
                       'source': {'url': source['url'], 'title': source.get('title') or source['url']}})
    return {'slug': slug, 'theme': result['theme'], 'period': result.get('period'), 'events': events,
            'source_mode': result['source_mode'],
            'pipeline_version': result.get('pipeline_version'), 'searched_at': result.get('searched_at'),
            'job_id': job_id, 'approved_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}


def approve(db, job_id, slug, approved_dir=APPROVED_DIR):
    if not SLUG.fullmatch(slug):
        raise PublishError('slug は英小文字・数字・ハイフンで指定してください')
    record = public_record(load_job(db, job_id), job_id, slug)
    approved_dir.mkdir(parents=True, exist_ok=True)
    path = approved_dir / f'{slug}.json'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(path)
    return path


def withdraw(slug, approved_dir=APPROVED_DIR):
    path = approved_dir / f'{slug}.json'
    if not SLUG.fullmatch(slug) or not path.exists():
        raise PublishError(f'公開対象に {slug} はありません')
    path.unlink()


def approved(approved_dir=APPROVED_DIR):
    records = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(approved_dir.glob('*.json'))] if approved_dir.exists() else []
    for record in records:
        # 承認後に手で編集された記録も、出典とslugの条件を満たさなければ書き出さない。
        if not SLUG.fullmatch(str(record.get('slug'))):
            raise PublishError(f'slug が不正です: {record.get("slug")!r}')
        public_record({'kind': 'result', **record}, record['job_id'], record['slug'])
    return sorted(records, key=lambda r: r['theme'])


def e(text):
    return html.escape(str(text), quote=True)


LICENSE = ('各出来事の題名と説明は、生成AIがWikipedia（日本語版・英語版）の記事をもとに要約・改変したものです。'
           '<a href="https://creativecommons.org/licenses/by-sa/4.0/deed.ja">CC BY-SA 4.0</a> で提供します。'
           '原文の著者は各出典記事の履歴を参照してください。'
           'このライセンス表示の対象は年表本文です。サイトのロゴ・UI・広告素材は含みません。'
           'WikipediaおよびWikimedia Foundationによる公認・推薦を示すものではありません。')


def page(title, body, root):
    return f'''<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>{e(title)}</title>
  <link rel="icon" href="{root}favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="{root}styles.css">
</head>
<body>
  <a class="skip-link" href="#page-heading">本文へ</a>
  <header class="masthead"><a class="wordmark" href="{root}">タイムラインジェネレーター<span>Timeline Generator</span></a></header>
  <main class="app-main">
{body}
  </main>
  <footer><p>{LICENSE}</p></footer>
</body>
</html>
'''


def timeline_page(record):
    rows = '\n'.join(
        f'      <li class="event"><div class="event-date">{e(ev["date"])}</div><h3 class="event-title">{e(ev["title"])}</h3>'
        f'<p class="event-description">{e(ev["description"])}</p>'
        f'<a class="source-link" href="{e(ev["source"]["url"])}" title="{e(ev["source"]["title"])}" rel="noopener">出典 ↗</a></li>'
        for ev in record['events'])
    sources = sorted({ev['source']['url']: ev['source']['title'] for ev in record['events']}.items(), key=lambda s: s[1])
    source_items = '\n'.join(f'        <li><a href="{e(url)}" rel="noopener">{e(title)}</a></li>' for url, title in sources)
    body = f'''    <div class="page-head"><h1 id="page-heading" tabindex="-1">{e(record["theme"])}の年表</h1></div>
    <p class="notice">生成AIがWikipediaの記事から出来事を抜き出し、運用者が確認して公開した年表です。誤りが残る可能性があるため、気になる出来事は出典も確認してください。</p>
    <section class="result-section" aria-labelledby="page-heading">
      <div class="timeline-columns" aria-hidden="true"><span>年代</span><span>出来事</span><span>説明</span><span>出典</span></div>
      <ol class="timeline">
{rows}
      </ol>
    </section>
    <section aria-labelledby="sources-heading">
      <h2 id="sources-heading">出典</h2>
      <ul>
{source_items}
      </ul>
    </section>'''
    return page(f'{record["theme"]}の年表 · タイムラインジェネレーター', body, '../')


def index_page(records):
    items = '\n'.join(f'      <li><a href="{e(r["slug"])}/">{e(r["theme"])}</a>（{len(r["events"])}件）</li>' for r in records)
    listing = f'    <ul>\n{items}\n    </ul>' if records else '    <p>公開している年表はまだありません。</p>'
    body = f'''    <div class="page-head"><h1 id="page-heading" tabindex="-1">タイムラインジェネレーター</h1></div>
    <p>テーマごとの主要な出来事を、Wikipediaの記事を出典として年表にまとめています。</p>
{listing}'''
    return page('タイムラインジェネレーター', body, '')


def build(out_dir, approved_dir=APPROVED_DIR):
    records = approved(approved_dir)
    out = Path(out_dir)
    # 取り下げた年表のページを残さないよう、毎回空の書き出し先から作る。
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for name in ASSETS:
        shutil.copyfile(APP_DIR / name, out / name)
    (out / 'index.html').write_text(index_page(records), encoding='utf-8')
    for record in records:
        (out / record['slug']).mkdir(exist_ok=True)
        (out / record['slug'] / 'index.html').write_text(timeline_page(record), encoding='utf-8')
    return records


def candidates(db):
    with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as conn:
        rows = conn.execute("select id, result from jobs where state = 'complete' and result is not null").fetchall()
    for job_id, result in rows:
        result = json.loads(result)
        try:
            public_record(result, job_id, 'check')
            verdict = '承認可'
        except PublishError as error:
            verdict = f'不可: {error}'
        print(job_id, result.get('theme'), f'{len(result.get("events") or [])}件', result.get('pipeline_version'), verdict)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('candidates').add_argument('db')
    p = sub.add_parser('approve')
    p.add_argument('db'); p.add_argument('job_id'); p.add_argument('slug')
    sub.add_parser('withdraw').add_argument('slug')
    sub.add_parser('build').add_argument('out_dir')
    args = parser.parse_args(argv)
    try:
        if args.command == 'candidates':
            candidates(args.db)
        elif args.command == 'approve':
            print(approve(args.db, args.job_id, args.slug))
        elif args.command == 'withdraw':
            withdraw(args.slug)
        else:
            print(f'{len(build(args.out_dir))}件の年表を書き出しました: {args.out_dir}')
    except PublishError as error:
        print(f'できません: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
