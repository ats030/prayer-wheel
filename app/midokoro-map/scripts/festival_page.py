"""Render one static page per festival from dated, sourced facts only (no generated text)."""
from datetime import date
from html import escape
from urllib.parse import quote, urlsplit

from festival_calendar import ORIGIN, period


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

    html = (
        "<!doctype html>\n"
        "<html lang=\"ja\">\n"
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{escape(label_ja)}｜みどころマップ</title>\n"
        f'<link rel="canonical" href="{ORIGIN}/festivals/{quote(qid)}">\n'
        '<script src="http://ubuntu-server-app:8526/v.js" data-site="midokoro-map" defer></script>\n'
        "</head>\n"
        "<body>\n"
        f"<h1>{escape(label_ja)}</h1>\n"
        f"<p>{escape(prefecture)}</p>\n"
        f"{occ_html}"
        f"{desc_html}"
        f'<a href="/?kind=omatsuri&amp;qid={quote(qid)}">地図で見る</a>\n'
        '<a href="/festivals">今月・来月の祭り</a>\n'
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
