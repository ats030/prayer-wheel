#!/usr/bin/env python3
"""Export verified four-choice questions read-only; build editorial artifacts.

Default: rebuild committed snapshots without connecting to the bank.
First export: --export-bank ~/data/exam-trainer/bank.sqlite
Revisions: --export-bank PATH --replace-drafts (refuses reviewed products).
No generation, network fetch, learner history export, or release approval.
"""

import argparse
import csv
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from exam_trainer import kouko, products
from build_kouko import render_book

LETTERS = "ABCD"


def round_robin(questions: list[dict], limit: int) -> list[dict]:
    groups = defaultdict(list)
    for q in questions:
        groups[q["category"]].append(q)
    ordered = []
    while any(groups.values()) and len(ordered) < limit:
        for group in groups.values():
            if group and len(ordered) < limit:
                ordered.append(group.pop(0))
    return ordered


def snapshot(conn: sqlite3.Connection, product_id: str, exported_at: str) -> dict:
    exam = conn.execute("SELECT * FROM exam WHERE name=?", (products.EXAMS[product_id],)).fetchone()
    if exam is None:
        raise ValueError(f"試験がありません: {products.EXAMS[product_id]}")
    nodes = {r["path"]: r["title"] for r in conn.execute(
        "SELECT path,title FROM syllabus_node WHERE exam_id=?", (exam["id"],))}
    titles = {r["url"]: r["title"] for r in conn.execute(
        "SELECT url,title FROM material WHERE exam_id=? ORDER BY id", (exam["id"],)) if r["title"]}
    sources = {}
    questions = []
    eligible = conn.execute("SELECT * FROM question WHERE exam_id=? AND status='verified' ORDER BY id", (exam["id"],))
    for row in eligible:
        choices, refs = json.loads(row["choices"]), json.loads(row["source_refs"])
        if (len(choices) != 4 or len(set(choices)) != 4 or not 0 <= row["answer"] < 4
                or not row["explanation"].strip() or not refs):
            continue
        if any(urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).hostname
               or urlsplit(url).username or urlsplit(url).password for url in refs):
            continue
        keys = []
        for url in dict.fromkeys(refs):
            key = next((k for k, s in sources.items() if s["url"] == url), None)
            if key is None:
                key = f"S{len(sources) + 1:03d}"
                sources[key] = {"url": url, "title": titles.get(url, f"参考資料 ({urlsplit(url).hostname})"),
                                "checked_at": exported_at,
                                "date_label": "バンクからの書き出し日（本文再確認なし）"}
            keys.append(key)
        questions.append({"id": row["id"], "category": nodes.get(row["node_path"], row["node_path"]),
                          "node_path": row["node_path"], "stem": row["stem"], "choices": choices,
                          "answer": row["answer"], "explanation": row["explanation"],
                          "source": keys[0], "source_keys": keys,
                          "provenance": {"bank_question_id": row["id"], "status_at_export": row["status"],
                                         "origin": row["origin"], "created_at": row["created_at"],
                                         "evidence": row["evidence"],
                                         "source_details": json.loads(row["source_details"])}})
    questions = round_robin(questions, 50)
    if len(questions) < 10:
        raise ValueError(f"{exam['name']}: 四択・出典付きの検証済み問題が10問未満です")
    for number, question in enumerate(questions, 1):
        question["id"] = number
    used = {key for q in questions for key in q["source_keys"]}
    return {"title": f"{exam['name']} 練習問題と解説", "exam_name": exam["name"],
            "subtitle": f"四択{len(questions)}問・解説と参考資料付き", "version": "0.1", "price_yen": None,
            "checked_at": exported_at,
            "scope_note": "既存バンクの検証済み問題から作った未校閲の教材です。出題範囲の網羅性、"
                          "本試験との難易度の一致、合格は保証しません。出典本文と利用条件の再確認が必要です。",
            "contents": list(dict.fromkeys(q["category"] for q in questions)),
            "free_ids": [q["id"] for q in round_robin(questions, 10)], "questions": questions,
            "sources": {key: value for key, value in sources.items() if key in used},
            "provenance": {"bank_exam_id": exam["id"], "exported_at": exported_at,
                           "selection": "verified・四択・出典付き。分野ごとの順番で最大50問。",
                           "human_review": "未校閲", "source_terms": "未確認"}}


def export_bank(path: Path, replace: bool = False) -> None:
    # Prepare every snapshot before writing files; never create an empty bank.
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        prepared = {key: snapshot(conn, key, date.today().isoformat()) for key in products.EXAMS}
    finally:
        conn.close()
    for key in prepared:
        target = products.PRODUCT_DIR / f"{key}.json"
        if target.exists() and (not replace or products.release_state(key)["reviewed"]):
            raise ValueError(f"既存教材を保護しました: {key}（未校閲教材の更新には--replace-drafts）")
    for key, product in prepared.items():
        (products.PRODUCT_DIR / f"{key}.json").write_text(json.dumps(product, ensure_ascii=False, indent=2) + "\n")
        release = products.PRODUCT_DIR / f"{key}-release.json"
        if not release.exists():
            release.write_text(json.dumps({"reviewed_sha256": "", "reviewer": "", "reviewed_at": "",
                                           "source_terms_checked": False, "booth_url": ""}, indent=2) + "\n")


def write_text_artifacts(key: str, product: dict, output: Path) -> bool:
    digest = products.content_digest(key)
    qs = product["questions"]
    manuscript = [f'# {product["title"]}', '', '校閲用原稿 / 未校閲 / 販売不可', '',
                  f'教材SHA-256: `{digest}`', '', product["scope_note"], '']
    audit = [f'# {product["exam_name"]} 根拠確認の記録', '',
             f'書き出し日：{product["checked_at"]}。出典本文の再確認は行っていません。', '',
             'バンクのverifiedは機械検証・既存の登録状態です。人による校閲や商用利用の許諾を意味しません。', '',
             '| 問 | バンクID | 分野 | 出典 | 保存済み根拠 | 校閲 |', '|---|---|---|---|---|---|']
    for q in qs:
        manuscript += [f'## 問{q["id"]} {q["category"]}', '', q["stem"], '']
        manuscript += [f'{LETTERS[i]}. {choice}' for i, choice in enumerate(q["choices"])]
        manuscript += ['', f'正解：{LETTERS[q["answer"]]}', '', q["explanation"], '']
        for source_key in q["source_keys"]:
            source = product["sources"][source_key]
            manuscript += [f'参考：[{source_key}] {source["url"]}', '']
        bank_id = q["provenance"]["bank_question_id"]
        manuscript += [f'バンク問題ID：{bank_id} / 登録状態：verified / 人による校閲：未確認', '']
        refs = ', '.join(product["sources"][s]["url"] for s in q["source_keys"])
        evidence = '抜粋あり・再確認待ち' if q["provenance"]["evidence"].strip() else '抜粋なし・本文の確認が必要'
        audit.append(f'| {q["id"]} | {bank_id} | {q["category"].replace("|", "/")} | {refs} | {evidence} | 未確認 |')
    audit += ['', '## 販売前の確認', '', '全問の正誤、誤答の一意性、出題範囲と難易度、出典本文と利用条件を確認します。',
              '未確認の記述を一次情報で確認済みと表示しません。exam-trainer利用者への原稿共有と、販売の承認は別です。', '']
    (output / 'manuscript.md').write_text('\n'.join(manuscript))
    (output / 'claim-audit.md').write_text('\n'.join(audit))
    review = output / f'review-{digest[:12]}.csv'
    if not review.exists():
        with review.open('w', newline='') as f:
            writer = csv.writer(f, lineterminator='\n')
            writer.writerow(['id', 'category', 'correct_choice', 'source_urls', 'exported_at', 'review_status', 'reviewer', 'notes'])
            for q in qs:
                writer.writerow([q['id'], q['category'], q['choices'][q['answer']],
                                 ' '.join(product['sources'][s]['url'] for s in q['source_keys']),
                                 product['checked_at'], '未確認', '', ''])
    # Draft copy can be edited by a human; a rebuild must not overwrite it.
    copy = output / 'sales-copy.md'
    copy_created = not copy.exists()
    if copy_created:
        copy.write_text(f'''# {product["exam_name"]} BOOTH商品説明の原稿

未校閲・未出品の販売原稿です。販売価格は未定です。

## 商品名
{product["title"]}

## 商品説明案
四択{len(qs)}問、解答欄、解答一覧、全問解説と参考資料を収録したPDFです。
無料体験の10問を含みます。印刷して解き直すための練習教材です。
{product["exam_name"]}主催者の公式教材・認定教材ではありません。
本試験の全範囲対応、難易度の一致、合格は保証しません。
個人学習用に保存・印刷できます。再配布・再販売はできません。

## SNS投稿案
{product["exam_name"]}の練習問題を10問試せます。回答後に正誤と解説を確認できます。
教材は校閲中です。公開先URLを確認してから投稿してください。

## 出品前に埋める項目
校閲結果、参照先の利用条件、販売価格、PDFページ数、版、BOOTH商品URLを確認します。
検証済みバンクからの書き出しだけでは販売可能になりません。
''')
    (output / 'release-guide.md').write_text(f'''# {product["exam_name"]} 校閲から販売まで

## 利用者への共有
紹介：/products/{key}
無料体験：/products/{key}/trial
資料一覧：/products/{key}/materials
固定された7種類の資料だけを閲覧・保存できます。既存exam-trainerのアクセス範囲は変更しません。
noindexは認証機能ではありません。全問PDFはアプリに到達できる利用者が保存できます。

## 校閲
review-{digest[:12]}.csvに全問の確認結果・校閲者・修正内容を記録します。
出典本文、正誤、選択肢、検定の出題範囲・難易度、出典の利用条件を人が確認します。
本教材は既存バンクのコピーです。学習履歴を変更せず、更新は教材JSONに反映します。

## 更新と再構築
src/exam_trainer/products/{key}.jsonがこの版の教材データです。
`~/.venv/bin/python app/exam-trainer/scripts/build_products.py`でPDF・原稿を再構築します。
内容変更後はSHAが変わり、販売の承認は失効します。CSVは版ごとに作り、既存の校閲記録を上書きしません。
販売説明の手修正も上書きしません。問題数や説明の変更時は販売原稿を合わせて確認します。
artifact-state.jsonは教材SHAと各資料のファイルSHAを記録します。旧版・手修正後の未確認資料は更新待ちとなり配信を止めます。
販売原稿が現在の版に合うことを確認したら、再構築に--confirm-sales-copyを付けて記録します。
この確認は販売原稿の版の照合であり、問題の校閲・販売の承認ではありません。

## 販売
全問の校閲と出典条件の確認後、{key}-release.jsonにreviewed_sha256、reviewer、reviewed_atを記録します。
source_terms_checkedをtrueにし、BOOTHへの出品後にhttpsのBOOTH商品URLをbooth_urlに設定します。
価格は未定です。価格を教材JSONに設定した場合も、変更後のSHAに対して承認します。
承認のSHAが現在の教材と一致し、条件確認済みで有効な商品URLがあるときだけ購入リンクが表示されます。
PDFを再構築し、保存版の表示・版・全問数を確認してから販売します。
''')
    return copy_created


def build(confirm_sales_copy: bool = False) -> None:
    from playwright.sync_api import sync_playwright
    from pypdf import PdfWriter

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for key in products.EXAMS:
            product = products.load_product(key)
            output = products.ARTIFACT_DIR / key
            output.mkdir(parents=True, exist_ok=True)
            copy_created = write_text_artifacts(key, product, output)
            for suffix, qs, sample in [('review', product['questions'], False),
                                       ('sample', kouko.sample_questions(product), True)]:
                path = output / f'{key}-{suffix}.html'
                path.write_text(render_book(product, qs, sample, reviewed=products.release_state(key)['reviewed'],
                                            groups=product['contents'], exam_name=product['exam_name']))
                page.goto(path.as_uri())
                raw = page.pdf(format='A4', print_background=True, display_header_footer=True,
                               header_template='<span></span>',
                               footer_template='<div style="width:100%;font-size:9px;text-align:center;">exam-trainer · <span class="pageNumber"></span> / <span class="totalPages"></span></div>')
                stamp = date.fromisoformat(product['checked_at']).strftime('D:%Y%m%d000000Z')
                writer = PdfWriter(clone_from=BytesIO(raw))
                writer.add_metadata({'/CreationDate': stamp, '/ModDate': stamp,
                                     '/Subject': 'Content SHA-256: ' + products.content_digest(key)})
                writer.write(output / f'{key}-{suffix}.pdf')
            kouko.record_artifacts(output, products.content_digest(key), len(product['questions']), key,
                                   products.release_state(key)['reviewed'],
                                   preserve=set() if confirm_sales_copy or copy_created else {'sales-copy'})
            print(f'{key}: {len(product["questions"])} questions, 10 trial, 7 artifacts')
        browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export-bank', type=Path)
    parser.add_argument('--replace-drafts', action='store_true')
    parser.add_argument('--confirm-sales-copy', action='store_true',
                        help='手修正の販売原稿が現在の教材の版に合うことを確認済みとして記録')
    args = parser.parse_args()
    if args.export_bank:
        export_bank(args.export_bank, args.replace_drafts)
    build(args.confirm_sales_copy)
