"""Render one static page per festival from dated, sourced facts only (no generated text)."""
import json
from datetime import date
from html import escape
from urllib.parse import quote, urlsplit

ORIGIN = 'https://midokoro-map.ats030.workers.dev'


def period(start, end, status):
    text = f'{start.month}月{start.day}日'
    if end != start:
        text += f'〜{end.month}月{end.day}日' if end.month != start.month else f'〜{end.day}日'
    return text + ('（予定）' if status == 'scheduled' else '')


def render_page(festival, today):
    label_ja = festival["label_ja"]
    qid = festival["qid"]
    prefecture = festival["prefecture"]

    rows = []
    for occ in festival.get("occurrences", []):
        try:
            start = date.fromisoformat(occ["start"])
        except (ValueError, KeyError, TypeError):
            continue
        end_raw = occ.get("end") or occ["start"]
        try:
            end = date.fromisoformat(end_raw)
        except (ValueError, KeyError, TypeError):
            continue
        source = occ.get("source", "")
        if urlsplit(source).scheme not in ("http", "https"):
            continue
        if end < today:
            continue
        status = occ.get("status", "")
        rows.append((start, end, status, source))

    rows.sort(key=lambda r: r[0])

    if rows:
        occ_html = "<ul>\n"
        for start, end, status, source in rows:
            hostname = escape(urlsplit(source).hostname or "")
            occ_html += f'<li>{period(start, end, status)} <a href="{escape(source)}" rel="noopener">{hostname}</a></li>\n'
        occ_html += "</ul>\n"
    else:
        occ_html = "<p>次回の日程は確認できていません。</p>\n"

    desc_html = ""
    description = festival.get("description", "")
    description_source = festival.get("description_source", "")
    if description and urlsplit(description_source).scheme in ("http", "https"):
        hostname = escape(urlsplit(description_source).hostname or "")
        desc_html = f'<p>{escape(description)} <a href="{escape(description_source)}" rel="noopener">{hostname}</a></p>\n'

    canonical = f"{ORIGIN}/festivals/{quote(qid)}"
    summary = escape(f"{label_ja}（{prefecture}）の開催日程と出典。日程が確定し出典のあるものだけを載せています。")
    # 検索結果の催し表示用。載せるのは本文と同じ確定日程・所在地だけ
    events = [{
        "@context": "https://schema.org", "@type": "Event", "name": label_ja,
        "startDate": start.isoformat(), "endDate": end.isoformat(), "url": canonical,
        "eventStatus": "https://schema.org/EventScheduled",
        "location": {"@type": "Place", "name": prefecture,
                     "address": {"@type": "PostalAddress", "addressRegion": prefecture, "addressCountry": "JP"}},
    } for start, end, status, source in rows]
    payload = json.dumps(events, ensure_ascii=False).replace("<", "\\u003c")
    json_ld = f'<script type="application/ld+json">{payload}</script>\n' if events else ""
    html = (
        "<!doctype html>\n"
        "<html lang=\"ja\">\n"
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
        f"<title>{escape(label_ja)}｜みどころマップ</title>\n"
        f'<meta name="description" content="{summary}">\n'
        f'<link rel="canonical" href="{canonical}">\n'
        '<meta property="og:type" content="article">\n'
        f'<meta property="og:title" content="{escape(label_ja)}">\n'
        f'<meta property="og:description" content="{summary}">\n'
        f'<meta property="og:url" content="{canonical}">\n'
        '<meta property="og:site_name" content="みどころマップ">\n'
        '<link rel="icon" href="/favicon.svg" type="image/svg+xml">\n'
        '<link rel="stylesheet" href="/tokens.css">\n'
        '<link rel="stylesheet" href="/app.css">\n'
        '<link rel="stylesheet" href="/stories/story.css">\n'
        '<script src="http://ubuntu-server-app:8526/v.js" data-site="midokoro-map" defer></script>\n'
        f"{json_ld}"
        "</head>\n"
        '<body class="story-page"><a class="skip-link" href="#festival-main">本文へ</a>'
        '<header class="site-header"><a class="brand" href="/"><img src="/favicon.svg" alt="" width="28" height="28">'
        '<span>みどころマップ</span></a><nav class="story-nav" aria-label="サイト">'
        '<a href="/?kind=omatsuri">祭りの地図</a></nav></header>\n'
        '<main id="festival-main"><section class="story-lead">\n'
        f'<p class="place-kicker">{escape(prefecture)}</p>\n'
        f"<h1>{escape(label_ja)}</h1>\n"
        "</section>\n"
        '<section class="story-reading" aria-label="開催日程">\n'
        f"{occ_html}"
        f"{desc_html}"
        f'<p><a href="/?kind=omatsuri&amp;qid={quote(qid)}">地図で見る</a></p>\n'
        "</section></main>\n"
        "</body>\n"
        "</html>"
    )
    return html


def page_qids(festivals):
    qids = set()
    for festival in festivals:
        qid = festival.get("qid", "")
        if not qid:
            continue
        for occ in festival.get("occurrences", []):
            try:
                date.fromisoformat(occ["start"])
            except (ValueError, KeyError, TypeError):
                continue
            source = occ.get("source", "")
            if urlsplit(source).scheme in ("http", "https"):
                qids.add(qid)
                break
    return sorted(qids)


def sitemap_entries(qids):
    return "".join(f"<url><loc>{ORIGIN}/festivals/{quote(qid)}</loc></url>\n" for qid in qids)
