#!/usr/bin/env python3
"""Build private review artifacts with the project's existing Playwright.

Run with ~/.venv/bin/python app/exam-trainer/scripts/build_kouko.py.
No network, bank mutations, approval changes, or uploads are performed.
"""

import argparse
import csv
import html
import sys
from collections import Counter
from datetime import date
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from exam_trainer import kouko  # noqa: E402

OUTPUT = ROOT / "docs" / "kouko"
LETTERS = "ABCD"
GROUPS = ["考古資料の見方と旧石器", "縄文の集落と交流", "弥生の農具と集落",
          "古墳と土器生産", "古代の宮殿、木簡、壁画"]


def escape(value):
    return html.escape(str(value))


def chunks(items, size=5):
    return [items[i:i + size] for i in range(0, len(items), size)]


def render_book(product, questions, sample=False, *, reviewed=None, groups=None, exam_name="考古検定"):
    if reviewed is None:
        reviewed = kouko.release_state()["reviewed"]
    groups = GROUPS if groups is None else groups
    label = f"見本{len(questions)}問" if sample else f"{len(questions)}問"
    stamp = "" if reviewed else "校閲用原稿 / 未校閲 / 販売不可"
    pages = []
    def page(title, body, kind=''):
        pages.append(f'<section class="page {kind}"><p class="stamp">{stamp}</p><h2>{title}</h2>{body}</section>')
    page(escape(product['title']), f'<p class="subtitle">{escape(product["subtitle"])}</p>'
         f'<p>四択{label} / 解答と解説 / 参考資料付き</p><p>exam-trainer<br>第{escape(product["version"])}版</p>'
         '<h3>使い方</h3><ol><li>問題を解き、解答欄にA〜Dを記入する。</li><li>解答一覧で採点する。</li>'
         '<li>解説と参考資料を読み、迷った問題を解き直す。</li></ol>'
         f'<p>{escape(product["scope_note"])}</p><p>{escape(exam_name)}主催者の公式教材、認定教材ではありません。'
         '本試験の問題を転載した教材ではありません。</p><h3>目次</h3><ol>'
         + ''.join(f'<li>{escape(t)}</li>' for t in groups) + '</ol>'
         '<p>個人の学習用に保存、印刷できます。ファイルの再配布、再販売はできません。</p>')
    # Two columns keep the 50-row answer sheet on one page.
    tables = []
    for group in chunks(questions, 25):
        cells = ''.join(f'<tr><td>{q["id"]}</td><td></td><td></td><td></td></tr>' for q in group)
        tables.append('<table><thead><tr><th>問</th><th>1回目</th><th>2回目</th><th>3回目</th></tr></thead><tbody>' + cells + '</tbody></table>')
    page('解答記入欄', '<p>回答した日：__________________</p><div class="answer-grid">' + ''.join(tables) + '</div>')
    for group in chunks(questions):
        body = ''
        for q in group:
            body += f'<article><h3>問{q["id"]}　{escape(q["category"])}</h3><p>{escape(q["stem"])}</p><ol type="A">'
            body += ''.join(f'<li>{escape(c)}</li>' for c in q['choices']) + '</ol></article>'
        page('問題', body, 'questions')
    page('解答一覧', '<div class="key-grid">' + ''.join(
        f'<p>問{q["id"]}：{LETTERS[q["answer"]]}</p>' for q in questions) + '</div>')
    for group in chunks(questions):
        body = ''
        for q in group:
            body += f'<article><h3>問{q["id"]}　正解：{LETTERS[q["answer"]]} {escape(q["choices"][q["answer"]])}</h3>'
            body += f'<p>{escape(q["explanation"])}</p>'
            for key in q.get('source_keys', [q['source']]):
                source = product['sources'][key]
                body += f'<p class="reference">参考 [{escape(key)}]：<a href="{escape(source["url"])}">{escape(source["title"])}</a></p>'
            body += '</article>'
        page('解説', body)
    used = sorted({key for q in questions for key in q.get('source_keys', [q['source']])})
    for group in chunks(used):
        body = ''
        for key in group:
            source = product['sources'][key]
            body += f'<article><h3>[{key}] {escape(source["title"])}</h3><p class="reference"><a href="{escape(source["url"])}">{escape(source["url"])}</a></p>'
            body += f'<p class="reference">{escape(source.get("date_label", "確認日"))}：{escape(source["checked_at"])}</p></article>'
        page('参考資料', body)
    return '''<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><title>練習問題と解説</title><style>
@page { size: A4; margin: 17mm 18mm; }
* { box-sizing: border-box; } body { font-family: "Noto Sans CJK JP", sans-serif; color: #202020; font-size: 11pt; line-height: 1.65; }
.page { break-after: page; } .page:last-child { break-after: auto; } h2 { font-size: 22pt; margin: 6mm 0; } h3 { font-size: 11pt; margin: 0 0 2mm; }
article { margin: 0 0 5mm; break-inside: avoid; } article p { margin: 0 0 2mm; } ol { margin: 0; padding-left: 7mm; }
.questions article { font-size: 10.5pt; line-height: 1.4; margin-bottom: 4mm; } .questions h3 { line-height: 1.4; }
.stamp { color: #9a2929; font-size: 9pt; } .subtitle { font-size: 16pt; } .reference { font-size: 8pt; overflow-wrap: anywhere; }
a { color: #303030; } .answer-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8mm; } table { border-collapse: collapse; width: 100%; font-size: 9pt; }
th,td { border: 1px solid #aaa; padding: 1mm 2mm; height: 7mm; } .key-grid { display: grid; grid-template-columns: repeat(5,1fr); gap: 1mm; } .key-grid p { margin: 1mm 0; }
</style></head><body>''' + ''.join(pages) + '</body></html>'


def main(confirm_copy=False):
    from playwright.sync_api import sync_playwright
    from pypdf import PdfWriter

    OUTPUT.mkdir(parents=True, exist_ok=True)
    product = kouko.load_product()
    questions = product['questions']
    markdown = [f'# {product["title"]}', '', '校閲用原稿です。全問を確認してから販売します。', '',
                f'教材SHA-256: `{kouko.content_digest()}`', '', product['scope_note'], '']
    for q in questions:
        s = product['sources'][q['source']]
        markdown += [f'## 問{q["id"]} {q["category"]}', '', q['stem'], '']
        markdown += [f'{LETTERS[i]}. {c}' for i,c in enumerate(q['choices'])]
        markdown += ['', f'正解：{LETTERS[q["answer"]]}', '', q['explanation'], '',
                     f'参考：[{s["title"]}]({s["url"]})', '',
                     f'資料の要旨：{s["support"]}', '', '校閲状態：未確認', '']
    (OUTPUT / 'manuscript.md').write_text('\n'.join(markdown))
    # Never overwrite a human's annotations on a rebuild. Each content revision
    # gets its own sheet, and review decisions cannot silently follow edits.
    review_path = OUTPUT / f'review-{kouko.content_digest()[:12]}.csv'
    if not review_path.exists():
        with review_path.open('w', newline='') as f:
            writer = csv.writer(f, lineterminator='\n')
            writer.writerow(['id','category','correct_choice','source_url','checked_at','review_status','reviewer','notes'])
            for q in questions:
                s = product['sources'][q['source']]
                writer.writerow([q['id'], q['category'], q['choices'][q['answer']], s['url'], s['checked_at'], '未確認','',''])
    audit = ['# 根拠確認記録', '', '確認日：2026-10-06。出典本文の要約であり、引用文ではありません。', '',
             '| 問 | claim | status | evidence | source | risk | action |', '|---|---|---|---|---|---|---|']
    for q in questions:
        s = product['sources'][q['source']]
        audit.append(f'| {q["id"]} | {q["choices"][q["answer"]]} | 一次資料に記述あり | {s["support"]} | [{q["source"]}]({s["url"]}) | 難易度と選択肢は人による校閲待ち | assert（原稿）、公開保留 |')
    audit += ['', '## Contradictions', '', '本試験範囲の網羅性は未確認。上級向けの細かな分類や年代は本原稿で扱わない。', '',
              '## Required research', '', '全問の正誤、誤答選択肢の一意性、入門クラスへの適合を校閲する。',
              '参照先の利用条件を確認する。写真、図版、公式問題、出典本文の転載は行っていない。', '',
              '## Drafting stop decision', '', '基礎教材の校閲用原稿を作成。合格保証、予想的中、全範囲対応の主張は省略する。一般公開と販売は校閲完了まで保留する。', '']
    (OUTPUT / 'claim-audit.md').write_text('\n'.join(audit))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for name, qs, sample in [('kouko-review', questions, False),
                                 ('kouko-sample', kouko.sample_questions(product), True)]:
            path = OUTPUT / f'{name}.html'
            path.write_text(render_book(product, qs, sample))
            page.goto(path.as_uri())
            raw_pdf = page.pdf(format='A4', print_background=True,
                               display_header_footer=True, header_template='<span></span>',
                               footer_template='<div style="width:100%;font-size:9px;text-align:center;">exam-trainer · <span class="pageNumber"></span> / <span class="totalPages"></span></div>')
            # Chromium embeds wall-clock times. Freeze those to the editorial
            # edition date so unchanged content produces unchanged artifacts.
            edition_date = date.fromisoformat(product['checked_at']).strftime('D:%Y%m%d000000Z')
            writer = PdfWriter(clone_from=BytesIO(raw_pdf))
            writer.add_metadata({'/CreationDate': edition_date, '/ModDate': edition_date,
                                 '/Subject': 'Content SHA-256: ' + kouko.content_digest()})
            writer.write(OUTPUT / f'{name}.pdf')
        browser.close()
    kouko.record_artifacts(OUTPUT, kouko.content_digest(), 50, "kouko", kouko.release_state()["reviewed"],
                           preserve=set() if confirm_copy else {"sales-copy", "release-guide"})
    print(f'Built {len(questions)} questions, answers={dict(Counter(q["answer"] for q in questions))}, digest={kouko.content_digest()}')
    print(f'Artifacts: {OUTPUT}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-copy', action='store_true',
                        help='手作成の販売原稿と販売手順が現在の教材の版に合うことを確認済みとして記録')
    main(parser.parse_args().confirm_copy)
