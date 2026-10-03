"""保存済み年表を人手の正解集合と照合する。モデルは呼ばず、DBは読み取り専用で開く。

uv run python quality_eval.py [--db label=path ...] [--out report.json] [--fetch-sources]
"""
import argparse
import json
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

import timeline

ROOT = Path(__file__).resolve().parent
GOLD_PATH = ROOT / 'quality_gold.json'
DEFAULT_DBS = [
    ('v1', ROOT / 'data' / 'quality-before-3fxm4.sqlite3'),
    ('v2', ROOT / 'data' / 'quality-before-source-review-3fxm4.sqlite3'),
    ('current', ROOT / 'data' / 'timelines.sqlite3'),
]
ENCYCLOPEDIA_HOSTS = ('wikipedia.org', 'kotobank.jp', 'britannica.com')
PERSONAL_HOSTS = ('fc2.com', 'cocolog-nifty.com', 'hatenablog.com', 'hatenablog.jp', 'hateblo.jp', 'ameblo.jp',
                  'note.com', 'livedoor.jp', 'livedoor.blog', 'seesaa.net', 'goo.ne.jp', 'blogspot.com')
SOURCE_KINDS = ('一次/当事者', '百科(二次)', '個人投稿', '未分類')


def normalize(text):
    return unicodedata.normalize('NFKC', str(text or '')).casefold()


def domain(url):
    host = (urlsplit(url or '').hostname or '').lower()
    return host[4:] if host.startswith('www.') else host


def host_matches(host, suffixes):
    return any(host == s or host.endswith('.' + s) for s in suffixes)


def source_kind(url, primary_domains):
    host = domain(url)
    if host_matches(host, primary_domains):
        return '一次/当事者'
    if host_matches(host, ENCYCLOPEDIA_HOSTS):
        return '百科(二次)'
    if host_matches(host, PERSONAL_HOSTS):
        return '個人投稿'
    return '未分類'


def event_text(event):
    return normalize(f"{event.get('title', '')} {event.get('description', '')}")


def in_years(year, years):
    if not years:
        return True
    try:
        return years[0] <= int(year) <= years[1]
    except (TypeError, ValueError):
        return False


def matches(event, item):
    """正解項目または既知の誤りに一致するか。語・年・日付のすべてを満たす必要がある。"""
    text = event_text(event)
    if not any(normalize(k) in text for k in item['keywords']):
        return False
    if not in_years(event.get('year'), item.get('years')):
        return False
    if item.get('dates') and not any(normalize(d) in normalize(event.get('date')) for d in item['dates']):
        return False
    return not any(normalize(u) in text for u in item.get('unless', []))


def parse_period(period):
    """保存結果の period 表記（例: 1980年 〜 終了指定なし）を年の範囲にする。旧版の期間指定結果用。"""
    def year(part):
        match = re.search(r'(紀元前)?(\d{1,4})年', part)
        return None if match is None else (-int(match[2]) if match[1] else int(match[2]))
    if not period or '〜' not in period:
        return None, None
    start, end = period.split('〜', 1)
    return year(start), year(end)


def in_period(item, start, end):
    years = item.get('years')
    if not years:
        return True
    return (start is None or years[1] >= start) and (end is None or years[0] <= end)


def find_theme(gold, result, query):
    name = (result or {}).get('theme') or ''
    if name in gold['themes']:
        return name
    candidates = [t for t in gold['themes'] if t in (query or '')]
    return max(candidates, key=len) if candidates else None


def duplicates(events):
    """同じ年・同じ出典で題名が包含関係にある組を返す。"""
    pairs = []
    for i, a in enumerate(events):
        for b in events[i + 1:]:
            ta, tb = normalize(a.get('title')), normalize(b.get('title'))
            same_source = (a.get('source') or {}).get('url') == (b.get('source') or {}).get('url')
            if a.get('year') == b.get('year') and same_source and ta and tb and (ta in tb or tb in ta):
                pairs.append([a.get('title'), b.get('title')])
    return pairs


def source_stats(events, primary_domains):
    domains = {}
    kinds = dict.fromkeys(SOURCE_KINDS, 0)
    for event in events:
        url = (event.get('source') or {}).get('url', '')
        domains[domain(url)] = domains.get(domain(url), 0) + 1
        kinds[source_kind(url, primary_domains)] += 1
    top = max(domains.items(), key=lambda kv: kv[1]) if domains else (None, 0)
    return {
        'distinct_domains': len(domains),
        'top_domain': top[0],
        'top_domain_share': round(top[1] / len(events), 2) if events else None,
        'domains': dict(sorted(domains.items(), key=lambda kv: -kv[1])),
        'kinds': kinds,
    }


def locate_in_sources(item, pages):
    """欠落項目の語と年が、引用元ページの同じ段落にあるか。pages は出典URL→正規化した段落の列。"""
    years = [str(y) for y in range(item['years'][0], item['years'][1] + 1)]
    for url, passages in pages.items():
        for text in passages or []:
            if any(normalize(k) in text for k in item['keywords']) and any(y in text for y in years):
                return url
    return None


def page_passages(page):
    passages = [normalize(' '.join(str(p.get(k) or '') for k in ('date_heading', 'heading', 'text')))
                for p in page.get('passages') or []]
    return passages or [normalize(page.get('text'))]


def fetch_pages(urls, timeout=60):
    reader = timeline.WebReader(time.monotonic() + timeout)
    pages = {}
    for url in urls:
        try:
            page = reader.fetch({'url': url})
            pages[url] = page_passages(page) if page else None
        except Exception:
            pages[url] = None
    return pages


def evaluate_result(gold, result, query, pages=None):
    theme_name = find_theme(gold, result, query)
    events = (result or {}).get('events') or []
    report = {
        'theme': theme_name,
        'events': len(events),
        'stop_reason': (result or {}).get('stop_reason'),
        'elapsed_seconds': (result or {}).get('elapsed_seconds'),
        'pipeline_version': (result or {}).get('pipeline_version'),
        'review_notes': len((result or {}).get('review_notes') or []),
        'duplicates': duplicates(events),
    }
    if theme_name is None:
        return report
    theme = gold['themes'][theme_name]
    period = result.get('period')
    start, end = parse_period(period)
    targets = [m for m in theme['milestones'] if in_period(m, start, end)]
    found, missing = [], []
    for item in targets:
        hit = next((e for e in events if matches(e, item)), None)
        if hit:
            found.append({'id': item['id'], 'label': item['label'], 'event': hit.get('title'), 'year': hit.get('year')})
        else:
            entry = {'id': item['id'], 'label': item['label']}
            if pages is not None:
                url = locate_in_sources(item, pages)
                entry['stage'] = '出典内にあり（候補生成・検査で欠落）' if url else '出典になし（検索・資料選択で欠落）'
                if url:
                    entry['source'] = url
            missing.append(entry)
    errors = [{'id': item['id'], 'label': item['label'], 'event': e.get('title'), 'year': e.get('year')}
              for item in theme['known_errors'] for e in events if matches(e, item)]
    report.update({
        'period': period,
        'recall': round(len(found) / len(targets), 2) if targets else None,
        'found': found,
        'missing': missing,
        'known_errors': errors,
        'sources': source_stats(events, theme.get('primary_domains', [])),
    })
    return report


def axis(key, label, value, display, better, target=None, passed=None, note=''):
    return {'key': key, 'label': label, 'value': value, 'display': display, 'better': better,
            'target': target, 'passed': passed, 'note': note}


def axes(report, theme=None):
    """画面に並べる評価軸。value は0〜1の割合で、None は対象外。合否は目標がある軸だけに付け、総合点は作らない。"""
    count = report['events']
    ratio = (lambda n: round(n / count, 2)) if count else (lambda n: None)
    kinds = (report.get('sources') or {}).get('kinds') or {}
    rows = []
    if theme is None:
        rows.append(axis('recall', '主要項目の再現率', None, '正解集合の対象外', 'high', note='このテーマは人手の主要項目がないため評価しません。'))
    else:
        total = len(report['found']) + len(report['missing'])
        target = theme.get('target_recall')
        recall = report['recall']
        rows.append(axis('recall', '主要項目の再現率', recall,
                         f"{len(report['found'])} / {total}件" if total else '期間内の主要項目なし', 'high', target,
                         None if target is None or recall is None else recall >= target,
                         '欠落：' + '、'.join(m['label'] for m in report['missing']) if report['missing'] else ''))
        errors = len(report['known_errors'])
        rows.append(axis('known_errors', '既知の誤りへの一致', None, f'{errors}件', 'low', passed=errors == 0,
                         note='、'.join(f"{e['label']}（{e['year']} {e['event']}）" for e in report['known_errors'])))
    pairs = len(report['duplicates'])
    # 組数は件数の2乗で増えうるため、棒が枠を超えないよう件数で頭打ちにする。
    rows.append(axis('duplicates', '重複の疑い', ratio(min(pairs, count)), f'{pairs}組', 'low', passed=pairs == 0))
    rows.append(axis('primary', '一次/当事者の出典', ratio(kinds.get('一次/当事者', 0)), f"{kinds.get('一次/当事者', 0)}件", 'high',
                     note='' if theme and theme.get('primary_domains') else 'このテーマは一次出典のサイトを定義していません。'))
    rows.append(axis('personal', '個人投稿の出典', ratio(kinds.get('個人投稿', 0)), f"{kinds.get('個人投稿', 0)}件", 'low'))
    src = report.get('sources') or {}
    rows.append(axis('concentration', '最多サイトへの集中', src.get('top_domain_share'),
                     f"{src.get('top_domain') or '-'}・全{src.get('distinct_domains', 0)}サイト", 'low'))
    rows.append(axis('events', '収録件数', round(min(count, timeline.MAX_EVENTS) / timeline.MAX_EVENTS, 2),
                     f'{count} / {timeline.MAX_EVENTS}件', 'high'))
    elapsed = report.get('elapsed_seconds')
    stop = {'time_limit': '時間上限で終了', 'processing_error': '途中終了', 'event_limit': '件数上限で終了',
            'sources_exhausted': '資料を使い切って終了'}.get(report.get('stop_reason'), report.get('stop_reason') or '')
    if report.get('stop_reason') == 'time_limit' and elapsed is not None and elapsed < timeline.TIME_LIMIT * 0.9:
        stop += '（当時の短い上限）'  # 上限が20分だった頃の結果。棒は現在の上限に対する割合で示す。
    rows.append(axis('elapsed', '処理時間', None if elapsed is None else round(min(elapsed, timeline.TIME_LIMIT) / timeline.TIME_LIMIT, 2),
                     '-' if elapsed is None else f'{elapsed / 60:.0f}分 / 上限{timeline.TIME_LIMIT // 60}分', 'low', note=stop))
    return rows


def job_quality(job, gold=None):
    """詳細画面用。保存結果からその場で計算し、保存しない。正解集合外のテーマは出典集計だけを返す。"""
    result = job.get('result')
    if not result:
        return None
    gold = gold or json.loads(GOLD_PATH.read_text(encoding='utf-8'))
    report = evaluate_result(gold, result, job.get('query'))
    if report['theme'] is None:
        report['sources'] = source_stats(result.get('events') or [], [])
    report['axes'] = axes(report, gold['themes'].get(report['theme']))
    report['gold_verified_at'] = gold['verified_at']
    return report


def load_jobs(path):
    connection = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        rows = connection.execute('SELECT id, query, state, result FROM jobs ORDER BY id').fetchall()
    finally:
        connection.close()
    return [(job_id, query, state, json.loads(result) if result else None) for job_id, query, state, result in rows]


def evaluate(gold, dbs, fetch_sources=False):
    snapshots = []
    for label, path in dbs:
        jobs = []
        for job_id, query, state, result in load_jobs(path):
            pages = None
            if fetch_sources and result:
                urls = sorted({(e.get('source') or {}).get('url') for e in result.get('events') or []} - {None, ''})
                pages = fetch_pages(urls)
            jobs.append({'id': job_id, 'query': query, 'state': state, **evaluate_result(gold, result, query, pages)})
        snapshots.append({'label': label, 'db': str(path), 'jobs': jobs})
    return {'gold_version': gold['version'], 'gold_verified_at': gold['verified_at'],
            'fetched_sources': fetch_sources, 'snapshots': snapshots}


def render(report):
    lines = []
    for snapshot in report['snapshots']:
        lines.append(f"== {snapshot['label']} ({snapshot['db']})")
        for job in snapshot['jobs']:
            recall = '-' if job.get('recall') is None else f"{job['recall']:.0%}"
            src = job.get('sources') or {}
            share = src.get('top_domain_share')
            lines.append(f"#{job['id']} {job['query']} [{job['state']}/{job['stop_reason']}] "
                         f"件数={job['events']} 再現率={recall} 既知誤り={len(job.get('known_errors', []))} "
                         f"重複={len(job['duplicates'])} ドメイン数={src.get('distinct_domains', '-')} "
                         f"最多={src.get('top_domain')}:{'-' if share is None else f'{share:.0%}'} "
                         f"時間={job['elapsed_seconds']}s")
            for item in job.get('missing', []):
                lines.append(f"    欠落 {item['label']}" + (f" … {item['stage']}" if 'stage' in item else ''))
            for item in job.get('known_errors', []):
                lines.append(f"    誤り {item['label']} ← {item['year']} {item['event']}")
    if not report['fetched_sources']:
        lines.append('欠落段階は --fetch-sources で出典本文を照合したときだけ分類する。候補生成と検査の区別は処理経過の記録がないため付けられない。')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', action='append', metavar='LABEL=PATH', help='評価するDB。省略時は v1/v2/current')
    parser.add_argument('--gold', default=str(GOLD_PATH))
    parser.add_argument('--out', help='JSONの出力先')
    parser.add_argument('--fetch-sources', action='store_true', help='出典ページを再取得して欠落段階を分類する')
    args = parser.parse_args(argv)
    gold = json.loads(Path(args.gold).read_text(encoding='utf-8'))
    dbs = [tuple(value.split('=', 1)) for value in args.db] if args.db else [(l, p) for l, p in DEFAULT_DBS if p.exists()]
    report = evaluate(gold, dbs, args.fetch_sources)
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(render(report))
    return 0


if __name__ == '__main__':
    sys.exit(main())
