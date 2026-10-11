"""Render the static "this month / next month" festival page from dated occurrences only."""
from datetime import date
from html import escape
from urllib.parse import quote, urlsplit

ORIGIN = 'https://midokoro-map.ats030.workers.dev'


def month_bounds(day):
    first = day.replace(day=1)
    following = first.replace(year=first.year + 1, month=1) if first.month == 12 else first.replace(month=first.month + 1)
    return first, following


def entries(festivals, first, following, today):
    """Occurrences overlapping [first, following) that have a source and have not ended before today."""
    rows = []
    for f in festivals:
        if not f.get('qid'):
            continue
        for o in f.get('occurrences') or []:
            try:
                start = date.fromisoformat(o['start'])
                end = date.fromisoformat(o.get('end') or o['start'])
            except (KeyError, TypeError, ValueError):
                continue
            if urlsplit(o.get('source') or '').scheme not in ('http', 'https') or end < today or end < first or start >= following:
                continue
            rows.append((start, end, f, o))
    rows.sort(key=lambda r: (r[0], r[1], r[2].get('prefecture', ''), r[2]['label_ja']))
    return rows


def period(start, end, status):
    text = f'{start.month}月{start.day}日'
    if end != start:
        text += f'〜{end.month}月{end.day}日' if end.month != start.month else f'〜{end.day}日'
    return text + ('（予定）' if status == 'scheduled' else '')


def section(title, anchor, rows):
    items = []
    for start, end, f, o in rows:
        href = f"/?kind=omatsuri&amp;qid={quote(f['qid'])}"
        source = escape(o['source'])
        host = escape(urlsplit(o['source']).hostname or o['source'])
        items.append(
            f'<li><p class="place-kicker">{escape(f.get("prefecture") or "所在地不明")}</p>'
            f'<h3><a href="{href}">{escape(f["label_ja"])}</a></h3>'
            f'<p><time datetime="{start.isoformat()}">{period(start, end, o.get("status"))}</time></p>'
            f'<p class="calendar-source">日程の出典: <a href="{source}" rel="noopener">{host}</a></p></li>')
    body = f'<ol class="calendar-list">{"".join(items)}</ol>' if items else '<p>この月に日程が確定している祭りはまだ登録されていません。</p>'
    return f'<section class="story-reading" id="{anchor}" aria-labelledby="{anchor}-title"><h2 id="{anchor}-title">{title}</h2>{body}</section>'


def render(festivals, today):
    this_first, next_first = month_bounds(today)
    _, after_next = month_bounds(next_first)
    this_rows = entries(festivals, this_first, next_first, today)
    next_rows = entries(festivals, next_first, after_next, today)
    label = lambda d: f'{d.year}年{d.month}月'
    description = f'{label(this_first)}・{label(next_first)}に開催される祭りの一覧。日程が確定し出典のあるものだけを載せています。'
    return f'''<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>今月・来月の祭り｜みどころマップ</title>
  <meta name="description" content="{description}">
  <link rel="canonical" href="{ORIGIN}/festivals">
  <meta property="og:type" content="website">
  <meta property="og:title" content="今月・来月の祭り">
  <meta property="og:description" content="{description}">
  <meta property="og:url" content="{ORIGIN}/festivals">
  <meta property="og:site_name" content="みどころマップ">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/app.css">
  <link rel="stylesheet" href="/stories/story.css">
  <script src="http://ubuntu-server-app:8526/v.js" data-site="midokoro-map" defer></script>
</head>
<body class="story-page"><a class="skip-link" href="#calendar-main">本文へ</a><header class="site-header"><a class="brand" href="/"><img src="/favicon.svg" alt="" width="28" height="28"><span>みどころマップ</span></a><nav class="story-nav" aria-label="サイト"><a href="/?kind=omatsuri">祭りの地図</a></nav></header><main id="calendar-main"><section class="story-lead"><p class="eyebrow">時期から探す</p><h1>今月・来月の祭り</h1><p class="lead-copy">日程が確定し、出典を確かめられる祭りだけを載せています。<br>日付が未定の祭りは<a href="/?kind=omatsuri">地図</a>から探せます。</p><p class="place-kicker"><time datetime="{today.isoformat()}">{today.year}年{today.month}月{today.day}日</time>時点 · <a href="#this-month">{label(this_first)}</a> · <a href="#next-month">{label(next_first)}</a></p></section>{section(label(this_first), 'this-month', this_rows)}{section(label(next_first), 'next-month', next_rows)}</main></body></html>
'''
